# Automated Infrastructure Drift Detection and Correction System

## Overview

Infrastructure drift occurs when the actual state of infrastructure becomes different from its intended configuration. This project demonstrates an automated system that detects infrastructure drift, corrects it, and verifies that the infrastructure has returned to its desired state.

The project uses **Terraform, Docker, Python, and GitHub Actions** to provide automated infrastructure management and self-remediation.

## Objectives

- Define infrastructure using Terraform.
- Deploy containerized infrastructure using Docker.
- Detect unexpected infrastructure changes automatically.
- Correct detected drift using Terraform.
- Verify infrastructure after remediation.
- Maintain timestamped drift history logs.
- Automate the process using GitHub Actions.

## Technologies Used

- **Terraform** — Infrastructure as Code and drift detection
- **Docker** — Containerized infrastructure
- **Python** — Drift detection and remediation automation
- **GitHub Actions** — CI/CD and automated drift checks
- **Git** — Version control

## Infrastructure

The Terraform configuration creates:

- Nginx web server container (`drift-web`)
- Redis cache container (`drift-cache`)
- Docker network (`drift-network`)
- Nginx and Redis Docker images

The Nginx service is exposed on port `8080`.

## Project Structure

```text
infra-drift/
├── .github/
│   └── workflows/
│       └── drift-check.yml
├── dashboard/
│   ├── server.py
│   ├── index.html
│   ├── config.example.json
│   └── README.md
├── scripts/
│   ├── detect_drift.py
│   ├── correct_drift.py
│   └── auto_remediate.py
├── main.tf
├── .terraform.lock.hcl
├── .gitignore
└── README.md
```

Generated Terraform state, logs, reports, and local Terraform working files are excluded from Git using `.gitignore`.

## How It Works

The system follows this workflow:

```text
Terraform Desired State
        |
        v
Docker Infrastructure
        |
        v
Unexpected / Manual Change
        |
        v
Terraform Drift Detection
        |
        v
Python Automation
        |
        v
Automatic Terraform Correction
        |
        v
Verification
        |
        v
Infrastructure Restored
```

Terraform compares the desired configuration with the actual infrastructure.

The Python automation uses:

```text
terraform plan -detailed-exitcode
```

Terraform returns:

- `0` — No infrastructure drift
- `2` — Infrastructure drift detected
- Other/error status — Infrastructure check failed

When drift is detected, the automation executes Terraform to restore the desired configuration and performs another check to verify the result.

## Drift Scenarios Tested

### 1. Stopped Redis Container

The Redis container was manually stopped.

The system detected the drift and automatically restored the container.

### 2. Deleted Nginx Container

The Nginx container was manually removed.

Terraform detected the missing resource and recreated it.

### 3. Incorrect Container Configuration

An Nginx container was manually created using an incorrect host port.

Terraform detected that the actual infrastructure did not match the desired configuration.

## Automatic Remediation

The main automation script is:

```text
scripts/auto_remediate.py
```

It performs:

1. Infrastructure state check
2. Drift detection
3. Automatic correction
4. Post-remediation verification
5. Timestamped history logging

If correction or verification fails, the script returns an error so that the GitHub Actions workflow reports a failure.

## GitHub Actions

The workflow is located at:

```text
.github/workflows/drift-check.yml
```

A self-hosted Windows GitHub Actions runner is used because the Docker infrastructure being monitored runs on the local machine.

The workflow can run automatically after repository changes or can be triggered manually.

During execution, GitHub Actions:

1. Checks out the repository.
2. Verifies Terraform.
3. Verifies Docker.
4. Initializes Terraform.
5. Runs the automatic drift-management script.
6. Detects and corrects infrastructure drift.
7. Verifies the restored infrastructure.

## Web Dashboard

A live web dashboard shows every workflow run, each step with its logs, the remediation
stages (check → drift → correct → verify), drifted resources, live Docker containers versus `main.tf`,
and the drift history. It can also trigger the workflow.

```bash
python dashboard/server.py      # then open http://localhost:8000
```

It needs no extra packages. See [dashboard/README.md](dashboard/README.md) for setup (repo name and GitHub token).

## Drift History

The automation maintains timestamped history such as:

```text
[2026-10-04 03:35:17] Infrastructure drift detected.
[2026-10-04 03:35:20] Drift correction completed.
[2026-10-04 03:35:23] Verification successful - infrastructure restored.
```

This provides a simple audit history of infrastructure health and remediation events.

## Verification

After remediation, infrastructure can be verified using:

```bash
docker ps
terraform plan
```

A successfully restored environment produces:

```text
No changes. Your infrastructure matches the configuration.
```

## Result

The project successfully demonstrates automated infrastructure drift management. Unexpected changes to Terraform-managed Docker infrastructure can be detected, automatically corrected, and verified through a GitHub Actions workflow.

This reduces manual recovery effort and demonstrates practical Infrastructure as Code, automation, CI/CD, and self-remediation concepts.