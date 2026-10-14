import os
import re
import sys
import json
import subprocess
from datetime import datetime
from pathlib import Path

log_dir = Path("logs")
log_dir.mkdir(exist_ok=True)

log_file = log_dir / "drift_history.log"

# Structured output consumed by the web dashboard (dashboard/server.py)
runs_file = log_dir / "runs.jsonl"
current_file = log_dir / "current_run.json"

PLAN_CHANGE = re.compile(r"^\s*# (\S+) (?:will be|must be) (.+?)\s*$")


def now():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def log(message):
    with open(log_file, "a", encoding="utf-8") as file:
        file.write(f"[{now()}] {message}\n")


def parse_plan_changes(output):
    """Extract '# docker_container.web will be created' style lines from a plan."""
    changes = []
    for line in output.splitlines():
        match = PLAN_CHANGE.match(line)
        if match:
            changes.append({"resource": match.group(1), "action": match.group(2)})
    return changes


run = {
    "id": datetime.now().strftime("%Y%m%d%H%M%S"),
    "started": now(),
    "finished": None,
    "status": "running",
    "result": None,
    "drift": [],
    "stages": [],
    "github": {
        "run_id": os.environ.get("GITHUB_RUN_ID"),
        "run_number": os.environ.get("GITHUB_RUN_NUMBER"),
        "actor": os.environ.get("GITHUB_ACTOR"),
        "sha": os.environ.get("GITHUB_SHA"),
        "event": os.environ.get("GITHUB_EVENT_NAME"),
    },
}


def save_current():
    with open(current_file, "w", encoding="utf-8") as file:
        json.dump(run, file, indent=2)


def stage_start(key, name):
    stage = {"key": key, "name": name, "status": "running",
             "started": now(), "finished": None, "exit_code": None, "output": ""}
    run["stages"].append(stage)
    save_current()
    return stage


def stage_end(stage, status, result=None):
    stage["status"] = status
    stage["finished"] = now()
    if result is not None:
        stage["exit_code"] = result.returncode
        stage["output"] = (result.stdout or "") + (result.stderr or "")
    save_current()


def terraform(*args):
    return subprocess.run(["terraform", *args], capture_output=True, text=True)


def finish(result, exit_code=0):
    run["status"] = "failed" if exit_code else "success"
    run["result"] = result
    run["finished"] = now()
    save_current()
    with open(runs_file, "a", encoding="utf-8") as file:
        file.write(json.dumps(run) + "\n")
    write_step_summary()
    sys.exit(exit_code)


def write_step_summary():
    """Show the result on the GitHub Actions run page as well."""
    summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
    if not summary_path:
        return
    lines = ["## Infrastructure Drift Check", "",
             f"**Result:** `{run['result']}`", "",
             "| Stage | Status | Started | Finished |", "|---|---|---|---|"]
    for stage in run["stages"]:
        lines.append(f"| {stage['name']} | {stage['status']} | {stage['started']} | {stage['finished']} |")
    if run["drift"]:
        lines += ["", "### Drifted resources", ""]
        lines += [f"- `{d['resource']}` {d['action']}" for d in run["drift"]]
    with open(summary_path, "a", encoding="utf-8") as file:
        file.write("\n".join(lines) + "\n")


print("Automated Infrastructure Drift Management")
print("-----------------------------------------")

print("Checking infrastructure state...")

stage = stage_start("check", "Check infrastructure state")
plan = terraform("plan", "-detailed-exitcode", "-no-color")

if plan.returncode == 0:
    stage_end(stage, "success", plan)
    print("STATUS: Infrastructure is healthy. No drift detected.")
    log("Infrastructure healthy - no drift detected.")
    finish("healthy")

elif plan.returncode == 2:
    stage_end(stage, "drift", plan)
    run["drift"] = parse_plan_changes(plan.stdout)
    print("STATUS: Drift detected.")
    log("Infrastructure drift detected.")

    print("Starting automatic correction...")

    stage = stage_start("correct", "Automatic correction (terraform apply)")
    apply = terraform("apply", "-auto-approve", "-no-color")

    if apply.returncode == 0:
        stage_end(stage, "success", apply)
        print("STATUS: Drift correction completed.")
        log("Drift correction completed.")

        stage = stage_start("verify", "Post-remediation verification")
        verify = terraform("plan", "-detailed-exitcode", "-no-color")

        if verify.returncode == 0:
            stage_end(stage, "success", verify)
            print("VERIFICATION: Infrastructure restored successfully.")
            log("Verification successful - infrastructure restored.")
            finish("corrected")
        else:
            stage_end(stage, "failed", verify)
            print("VERIFICATION: Infrastructure still has differences.")
            log("Verification failed - infrastructure still has differences.")
            finish("verify_failed", 1)

    else:
        stage_end(stage, "failed", apply)
        print("STATUS: Automatic correction failed.")
        print(apply.stderr)
        log("Automatic correction failed.")
        finish("correction_failed", 1)

else:
    stage_end(stage, "failed", plan)
    print("STATUS: Error while checking infrastructure.")
    print(plan.stderr)
    log("Error while checking infrastructure.")
    finish("error", 1)
