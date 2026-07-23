---
title: "Phase 3.4 — Compliance & Data Governance"
description: "Retention policy engine, data archival, audit export, PII scanning, and GDPR erasure workflows."
status: pending
dependencies: ["phase-1/04-event-log.md"]
---

# Compliance & Data Governance

## Description
Implement data governance for enterprise compliance: configurable retention policies, automatic archival, audit trail export, PII scanning, and data deletion workflows.

## Retention Policy Engine
Each project has a policy: `retention_days`, `archive_after_days`, `delete_after_days`. A daily job moves old context units to cold storage and optionally redacts expired content. Certain types (decision, summary) can be exempted.

## Cold Storage Archival
Old units are serialized to JSONL and stored in object storage. Their content is replaced with a pointer: `{"_archived": true, "_archive_key": "path/to/archive.jsonl"}`.

## Audit Trail Export
`GET /v1/projects/{id}/export/audit` — exports all event log entries as JSON or NDJSON. Includes full payload for each event.

## PII Scanning
On write, scan content for PII patterns (email, phone, SSN, credit card). Flagged findings are stored in metadata but content is preserved. PII report endpoint: `GET /v1/projects/{id}/pii-report`.

## Data Erasure (GDPR Right to Erasure)
`POST /v1/projects/{id}/agents/{agent_id}/erase` — anonymizes agent records, redacts their content, preserves graph integrity.

## File Targets
- `services/compliance/__init__.py`
- `services/compliance/retention.py` — retention policy engine
- `services/compliance/audit.py` — audit trail export
- `services/compliance/pii_scanner.py` — PII scanning
- `services/compliance/erasure.py` — data erasure
- `scripts/run-retention-job.sh` — daily retention job

## Acceptance Criteria
- [ ] Retention policy archives units older than threshold
- [ ] Archived units have content replaced with cold storage pointer
- [ ] Audit export produces complete event list
- [ ] PII scan detects email, phone, SSN, credit card patterns
- [ ] Data erasure anonymizes without breaking graph integrity
- [ ] All compliance ops are logged in the event log

## TDD Instructions
```python
async def test_retention_archives_old_units(compliance, sample_old_units):
    await compliance.enforce_retention(project_id="test")
    archived = await db.fetch("SELECT * FROM context_units WHERE content @> '{\"_archived\": true}'")
    assert len(archived) > 0

async def test_pii_scan_detects_email(compliance):
    findings = await compliance.scan_for_pii("Contact me at test@example.com")
    assert any(f["type"] == "email" for f in findings)
```

## Dependencies
- Phase 1.4 (event log is the audit trail foundation)
