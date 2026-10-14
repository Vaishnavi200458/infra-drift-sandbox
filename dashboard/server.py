"""
Infra Drift Dashboard - local web server.

Shows everything the "Infrastructure Drift Check" GitHub workflow does:
  * GitHub Actions runs, their steps and step logs (GitHub REST API)
  * Remediation stages of each run (logs/runs.jsonl, logs/current_run.json)
  * Live Docker containers vs. the containers defined in main.tf
  * Drift history (logs/drift_history.log)

Uses only the Python standard library - no pip install needed.

    python dashboard/server.py
    open http://localhost:8000

Configuration (environment variables or dashboard/config.json):
    GITHUB_REPO   owner/name of the repository (auto-detected from git remote)
    GITHUB_TOKEN  token with Actions read (and write, for the Run button) access
    INFRA_DIR     folder the workflow runs in (where logs/ and main.tf live)
    WORKFLOW_FILE workflow to show (default drift-check.yml)
    PORT          port to listen on (default 8000)
"""

import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse, parse_qs

DASHBOARD_DIR = Path(__file__).resolve().parent
PROJECT_DIR = DASHBOARD_DIR.parent
API = "https://api.github.com"


def load_config():
    config = {}
    config_file = DASHBOARD_DIR / "config.json"
    if config_file.exists():
        config = json.loads(config_file.read_text(encoding="utf-8"))
    for key in ("GITHUB_REPO", "GITHUB_TOKEN", "INFRA_DIR", "PORT", "DOCKER_PATH", "WORKFLOW_FILE"):
        if os.environ.get(key):
            config[key] = os.environ[key]
    config.setdefault("INFRA_DIR", str(PROJECT_DIR))
    config.setdefault("PORT", 8000)
    config.setdefault("WORKFLOW_FILE", "drift-check.yml")
    if not config.get("GITHUB_REPO"):
        config["GITHUB_REPO"] = detect_repo(config["INFRA_DIR"]) or detect_repo(PROJECT_DIR)
    return config


def detect_repo(folder):
    """Read owner/name from `git remote get-url origin`."""
    try:
        url = subprocess.run(["git", "remote", "get-url", "origin"], cwd=folder,
                             capture_output=True, text=True, timeout=5).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return None
    match = re.search(r"github\.com[:/]([^/]+/[^/]+?)(?:\.git)?$", url)
    return match.group(1) if match else None


CONFIG = load_config()
INFRA_DIR = Path(CONFIG["INFRA_DIR"])
LOG_DIR = INFRA_DIR / "logs"
WORKFLOW_FILE = CONFIG["WORKFLOW_FILE"]


# --------------------------------------------------------------------------- #
# GitHub API (with ETag caching - 304 responses don't count against the limit)
# --------------------------------------------------------------------------- #

class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


_cache = {}
_cache_lock = threading.Lock()
rate_limit = {"remaining": None, "limit": None, "reset": None}


def github_headers():
    headers = {"Accept": "application/vnd.github+json",
               "X-GitHub-Api-Version": "2022-11-28",
               "User-Agent": "infra-drift-dashboard"}
    if CONFIG.get("GITHUB_TOKEN"):
        headers["Authorization"] = f"Bearer {CONFIG['GITHUB_TOKEN']}"
    return headers


def github_get(path, min_age=3):
    """GET a GitHub API path, returning parsed JSON. Cached by ETag."""
    url = API + path
    with _cache_lock:
        cached = _cache.get(url)
    if cached and time.time() - cached["at"] < min_age:
        return cached["data"]

    headers = github_headers()
    if cached:
        headers["If-None-Match"] = cached["etag"]
    request = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            track_rate_limit(response.headers)
            data = json.loads(response.read().decode("utf-8"))
            etag = response.headers.get("ETag")
    except urllib.error.HTTPError as error:
        track_rate_limit(error.headers)
        if error.code == 304 and cached:
            cached["at"] = time.time()
            return cached["data"]
        raise GitHubError(error.code, error.read().decode("utf-8", "replace"))

    with _cache_lock:
        _cache[url] = {"data": data, "etag": etag, "at": time.time()}
    return data


def github_job_logs(job_id):
    """Logs endpoint redirects to a signed URL that must be fetched without auth."""
    url = f"{API}/repos/{CONFIG['GITHUB_REPO']}/actions/jobs/{job_id}/logs"
    opener = urllib.request.build_opener(NoRedirect)
    try:
        opener.open(urllib.request.Request(url, headers=github_headers()), timeout=15)
        raise GitHubError(500, "Expected a redirect from the logs endpoint")
    except urllib.error.HTTPError as error:
        track_rate_limit(error.headers)
        if error.code not in (301, 302, 307, 308):
            raise GitHubError(error.code, error.read().decode("utf-8", "replace"))
        location = error.headers["Location"]
    with urllib.request.urlopen(location, timeout=30) as response:
        return response.read().decode("utf-8", "replace")


def github_dispatch(ref):
    url = f"{API}/repos/{CONFIG['GITHUB_REPO']}/actions/workflows/{WORKFLOW_FILE}/dispatches"
    body = json.dumps({"ref": ref}).encode("utf-8")
    headers = github_headers()
    headers["Content-Type"] = "application/json"
    request = urllib.request.Request(url, data=body, headers=headers, method="POST")
    try:
        urllib.request.urlopen(request, timeout=15).close()
    except urllib.error.HTTPError as error:
        raise GitHubError(error.code, error.read().decode("utf-8", "replace"))
    with _cache_lock:
        _cache.clear()


def track_rate_limit(headers):
    if headers and headers.get("X-RateLimit-Remaining") is not None:
        rate_limit["remaining"] = int(headers["X-RateLimit-Remaining"])
        rate_limit["limit"] = int(headers.get("X-RateLimit-Limit", 0))
        rate_limit["reset"] = int(headers.get("X-RateLimit-Reset", 0))


class GitHubError(Exception):
    def __init__(self, status, body):
        try:
            message = json.loads(body).get("message", body)
        except ValueError:
            message = body
        super().__init__(message)
        self.status = status


# --------------------------------------------------------------------------- #
# Local data: logs written by scripts/auto_remediate.py, docker, main.tf
# --------------------------------------------------------------------------- #

HISTORY_LINE = re.compile(r"^\[(.+?)\] (.*)$")


def read_history(limit=200):
    path = LOG_DIR / "drift_history.log"
    if not path.exists():
        return []
    entries = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        match = HISTORY_LINE.match(line.strip())
        if match:
            entries.append({"time": match.group(1), "message": match.group(2)})
    return entries[-limit:][::-1]


def read_runs(limit=100):
    path = LOG_DIR / "runs.jsonl"
    if not path.exists():
        return []
    runs = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            runs.append(json.loads(line))
        except ValueError:
            continue
    return runs[-limit:][::-1]


def read_current():
    path = LOG_DIR / "current_run.json"
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except ValueError:  # file is mid-write
        return None


def find_docker():
    if CONFIG.get("DOCKER_PATH"):
        return CONFIG["DOCKER_PATH"]
    found = shutil.which("docker")
    if found:
        return found
    for candidate in (r"C:\DockerCLI\docker.exe",
                      r"C:\Program Files\Docker\Docker\resources\bin\docker.exe"):
        if Path(candidate).exists():
            return candidate
    return None


def expected_resources():
    """Containers and networks declared in main.tf."""
    path = INFRA_DIR / "main.tf"
    if not path.exists():
        path = PROJECT_DIR / "main.tf"
    if not path.exists():
        return {"containers": [], "networks": []}
    text = path.read_text(encoding="utf-8")
    result = {"containers": [], "networks": []}
    for kind, key in (("docker_container", "containers"), ("docker_network", "networks")):
        for match in re.finditer(r'resource\s+"%s"\s+"(\w+)"\s*\{(.*?)\n\}' % kind, text, re.S):
            body = match.group(2)
            name = re.search(r'^\s*name\s*=\s*"([^"]+)"', body, re.M)
            entry = {"resource": f"{kind}.{match.group(1)}",
                     "name": name.group(1) if name else match.group(1)}
            ports = re.findall(r"internal\s*=\s*(\d+)\s*\n\s*external\s*=\s*(\d+)", body)
            if ports:
                entry["ports"] = [f"{ext}->{internal}" for internal, ext in ports]
            image = re.search(r"image\s*=\s*docker_image\.(\w+)", body)
            if image:
                image_name = re.search(
                    r'resource\s+"docker_image"\s+"%s"\s*\{[^}]*?name\s*=\s*"([^"]+)"' % image.group(1),
                    text, re.S)
                entry["image"] = image_name.group(1) if image_name else image.group(1)
            result[key].append(entry)
    return result


def infra_status():
    expected = expected_resources()
    docker = find_docker()
    status = {"docker": bool(docker), "expected": expected,
              "containers": [], "networks": [], "error": None}
    if not docker:
        status["error"] = "Docker CLI not found on this machine"
        return status
    try:
        ps = subprocess.run([docker, "ps", "-a", "--no-trunc", "--format", "{{json .}}"],
                            capture_output=True, text=True, timeout=10)
        if ps.returncode != 0:
            status["error"] = (ps.stderr or "docker ps failed").strip()
            return status
        for line in ps.stdout.splitlines():
            item = json.loads(line)
            status["containers"].append({
                "name": item.get("Names"), "image": item.get("Image"),
                "state": item.get("State"), "status": item.get("Status"),
                "ports": item.get("Ports"), "created": item.get("CreatedAt"),
            })
        nets = subprocess.run([docker, "network", "ls", "--format", "{{json .}}"],
                              capture_output=True, text=True, timeout=10)
        for line in nets.stdout.splitlines():
            item = json.loads(line)
            status["networks"].append({"name": item.get("Name"), "driver": item.get("Driver")})
    except (OSError, subprocess.SubprocessError, ValueError) as error:
        status["error"] = str(error)
    return status


# --------------------------------------------------------------------------- #
# HTTP server
# --------------------------------------------------------------------------- #

class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        pass  # keep the console quiet; errors are reported in the UI

    def send_json(self, data, status=200):
        body = json.dumps(data).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def send_text(self, text, content_type="text/plain; charset=utf-8", status=200):
        body = text.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def require_repo(self):
        if not CONFIG.get("GITHUB_REPO"):
            self.send_json({"error": "GitHub repository not configured. Set GITHUB_REPO "
                                     "(owner/name) in dashboard/config.json."}, 400)
            return False
        return True

    def do_GET(self):
        url = urlparse(self.path)
        path = url.path
        query = parse_qs(url.query)
        repo = CONFIG.get("GITHUB_REPO")
        try:
            if path in ("/", "/index.html"):
                self.send_text((DASHBOARD_DIR / "index.html").read_text(encoding="utf-8"),
                               "text/html; charset=utf-8")
            elif path == "/api/config":
                self.send_json({"repo": repo, "token": bool(CONFIG.get("GITHUB_TOKEN")),
                                "infra_dir": str(INFRA_DIR), "workflow": WORKFLOW_FILE,
                                "rate_limit": rate_limit})
            elif path == "/api/github/runs":
                if self.require_repo():
                    per_page = int(query.get("per_page", ["25"])[0])
                    data = github_get(f"/repos/{repo}/actions/workflows/{WORKFLOW_FILE}"
                                      f"/runs?per_page={per_page}")
                    self.send_json({"runs": data.get("workflow_runs", []),
                                    "total": data.get("total_count", 0),
                                    "rate_limit": rate_limit})
            elif re.fullmatch(r"/api/github/runs/\d+/jobs", path):
                if self.require_repo():
                    run_id = path.split("/")[4]
                    data = github_get(f"/repos/{repo}/actions/runs/{run_id}/jobs")
                    self.send_json({"jobs": data.get("jobs", [])})
            elif re.fullmatch(r"/api/github/jobs/\d+/logs", path):
                if self.require_repo():
                    if not CONFIG.get("GITHUB_TOKEN"):
                        self.send_json({"error": "Viewing step logs needs a GITHUB_TOKEN "
                                                 "(GitHub requires login for logs)."}, 401)
                    else:
                        self.send_text(github_job_logs(path.split("/")[4]))
            elif path == "/api/local/runs":
                self.send_json({"runs": read_runs(), "current": read_current()})
            elif path == "/api/local/history":
                self.send_json({"history": read_history()})
            elif path == "/api/local/infra":
                self.send_json(infra_status())
            else:
                self.send_json({"error": "Not found"}, 404)
        except GitHubError as error:
            self.send_json({"error": f"GitHub: {error}", "status": error.status}, 502)
        except urllib.error.URLError as error:
            self.send_json({"error": f"Cannot reach GitHub: {error.reason}"}, 502)
        except Exception as error:  # noqa: BLE001 - surface any failure in the UI
            self.send_json({"error": f"{type(error).__name__}: {error}"}, 500)

    def do_POST(self):
        # Custom header forces a CORS preflight, so other websites can't trigger runs.
        if self.headers.get("X-Dashboard") != "1":
            self.send_json({"error": "Forbidden"}, 403)
            return
        if self.path != "/api/github/dispatch":
            self.send_json({"error": "Not found"}, 404)
            return
        if not self.require_repo():
            return
        if not CONFIG.get("GITHUB_TOKEN"):
            self.send_json({"error": "Triggering a run needs a GITHUB_TOKEN with "
                                     "Actions: Read and write permission."}, 401)
            return
        length = int(self.headers.get("Content-Length") or 0)
        payload = json.loads(self.rfile.read(length) or b"{}")
        try:
            github_dispatch(payload.get("ref") or "main")
            self.send_json({"ok": True})
        except GitHubError as error:
            self.send_json({"error": f"GitHub: {error}"}, 502)


def main():
    port = int(CONFIG["PORT"])
    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    print("Infra Drift Dashboard")
    print("---------------------")
    print(f"Repository : {CONFIG.get('GITHUB_REPO') or 'NOT SET (see dashboard/README.md)'}")
    print(f"Token      : {'configured' if CONFIG.get('GITHUB_TOKEN') else 'not set (read-only, 60 req/h)'}")
    print(f"Infra dir  : {INFRA_DIR}")
    print(f"Docker CLI : {find_docker() or 'not found'}")
    print(f"\nOpen http://localhost:{port}  (Ctrl+C to stop)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")
        sys.exit(0)


if __name__ == "__main__":
    main()
