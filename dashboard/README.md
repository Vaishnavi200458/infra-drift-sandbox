# Infra Drift Dashboard

A web dashboard that shows everything the **Infrastructure Drift Check** GitHub workflow does, live:

| Panel | Shows | Source |
|---|---|---|
| **KPIs** | Infra health, latest run, success rate, drift auto-corrected | all of the below |
| **Workflow run** | Every job and step of a run with status, timing bars, and live progress | GitHub Actions API |
| **Step logs** | Full log of the job, jumping to the clicked step, with search | GitHub Actions API (needs token) |
| **Remediation pipeline** | Check → Drift → Correct → Verify for that run, which resources drifted, and the terraform output | `logs/runs.jsonl`, written by `scripts/auto_remediate.py` |
| **Live infrastructure** | Containers/network from `main.tf` vs what Docker is actually running | `docker ps` + `main.tf` |
| **Run history** | Duration of each run, coloured by result | GitHub Actions API |
| **Drift history** | Timestamped audit log | `logs/drift_history.log` |
| **▶ Run drift check** | Triggers the workflow (`workflow_dispatch`) | GitHub Actions API (needs token) |

The page refreshes automatically, every 5 s while a run is in progress.

**No installs needed:** it uses only the Python standard library (Python 3.8+).

## Run it (on the laptop with Docker + Terraform + the runner)

1. Pull the latest code into the folder the workflow uses
   (`C:\Users\Vaishnavi\Desktop\devops\infra-drift`).

2. Create the config file:

   ```powershell
   copy dashboard\config.example.json dashboard\config.json
   ```

   Edit `dashboard\config.json`:
   - `GITHUB_REPO`: `owner/repo-name` of this repository
   - `GITHUB_TOKEN`: a token (see below). You can leave it out for public repos, but you then get no step logs, no Run button, and only 60 API requests per hour.
   - `INFRA_DIR`: the folder the workflow runs in (where `logs\` and `main.tf` are)

   `config.json` is in `.gitignore`, so the token is never committed.

3. Start it:

   ```powershell
   python dashboard\server.py
   ```

   Then open **http://localhost:8000**

### Creating the GitHub token

GitHub → Settings → Developer settings → **Fine-grained personal access tokens** → Generate new token:

- **Repository access:** only this repository
- **Permissions → Actions:** *Read and write* (read = runs/logs, write = the Run button)
- **Permissions → Metadata:** *Read* (selected automatically)

## How it fits together

```text
 GitHub Actions ──(REST API)──┐
                              ▼
 self-hosted runner     dashboard/server.py  ──►  browser (index.html)
   └─ auto_remediate.py       ▲       ▲
        └─ logs/runs.jsonl ───┘       └── docker ps / main.tf
        └─ logs/current_run.json
        └─ logs/drift_history.log
```

- `scripts/auto_remediate.py` now also writes structured stage data (`logs/runs.jsonl`,
  `logs/current_run.json`) and a summary table on the GitHub run page. Its console output,
  `drift_history.log` and exit codes are unchanged.
- The server listens on `127.0.0.1` only. The token stays on the server and is never sent to the browser.

## Troubleshooting

| Symptom | Fix |
|---|---|
| "GitHub repository not set" | Set `GITHUB_REPO` in `config.json` |
| `GitHub: Not Found` | Repo name is wrong, or the repo is private and there is no token or it lacks access |
| `API rate limit exceeded` | Add a `GITHUB_TOKEN` |
| Run stuck on "Queued" | The self-hosted runner is offline. Start it (`run.cmd` in the runner folder) |
| Docker shows "Unknown" | Docker Desktop is not running, or the CLI is not found. Set `"DOCKER_PATH": "C:\\DockerCLI\\docker.exe"` in `config.json` |
| Remediation pipeline empty | No run of the updated `auto_remediate.py` has happened yet in `INFRA_DIR` |
