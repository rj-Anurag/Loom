---
title: "Phase 0.3 — CI/CD Pipeline"
description: "GitHub Actions workflows for continuous integration, security scanning, and deployment readiness."
status: completed
framework: "GitHub Actions + FastAPI + pgvector service containers"
dependencies: ["phase-0/01-project-scaffold.md", "phase-0/02-dev-environment.md"]
---

# CI/CD Pipeline

## Description
Set up GitHub Actions workflows that enforce code quality, run tests, scan for vulnerabilities, and prepare for deployment.

## Deliverables

### 1. CI Workflow (`.github/workflows/ci.yml`)

Triggers: `push` to any branch, `pull_request` to `main`.

Jobs:
- **lint**: ruff (Python), mypy (type-check)
- **test**: pytest with PostgreSQL service container (pgvector)
  - Matrix: Python 3.11, 3.12
  - Upload coverage report
- **security**: safety (dependency vulnerabilities), bandit (static analysis)

Each job runs in parallel. All must pass before merge.

### 2. Deploy Workflow (`.github/workflows/deploy.yml`)

Triggers: `push` to `main` (only after CI passes).

Stub that:
- Builds Docker images
- Pushes to registry (stub action)
- Runs database migrations (stub)
- Deploys (stub — echo commands)

### 3. Security Scan Workflow (`.github/workflows/security-scan.yml`)

Scheduled: daily at 2am, also on `pull_request` to `main`.

Runs:
- `safety check` — known vulnerabilities in dependencies
- `bandit` — Python static security analysis
- `trivy` — container image scanning (stub)

## Acceptance Criteria

- [ ] CI workflow appears in GitHub Actions after push
- [ ] `lint` job runs ruff and mypy, fails on any violation
- [ ] `test` job runs pytest with pgvector service container
- [ ] Coverage report is uploaded as an artifact
- [ ] Deploy workflow is triggered by push to main (stub is OK)
- [ ] Security scan runs on schedule and on PR to main

## TDD Instructions

**Before implementing:** Write a test that validates workflow files are valid YAML:

```python
def test_ci_workflow_is_valid_yaml():
    import yaml
    with open(".github/workflows/ci.yml") as f:
        config = yaml.safe_load(f)
    assert "jobs" in config
    assert "test" in config["jobs"]

def test_security_workflow_has_schedule():
    import yaml
    with open(".github/workflows/security-scan.yml") as f:
        config = yaml.safe_load(f)
    assert "schedule" in config["on"]
```

## Dependencies
- Phase 0.1 (project scaffold)
- Phase 0.2 (dev environment — validates pgvector is available for CI)
