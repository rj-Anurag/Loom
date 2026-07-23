---
title: "Phase 2.6 — Multi-Agent Concurrent Demo"
description: "End-to-end demo with 3 agents (local, cloud, browser) working on the same project simultaneously. Demonstrates branch/merge in action."
status: pending
dependencies: ["phase-2/01-full-coordination.md", "phase-2/05-interactive-ui.md"]
---

# Multi-Agent Concurrent Demo

## Description
Create a demonstration that runs 3 agents (one local, one cloud-simulated, one browser-chat-simulated) on the same project simultaneously. Each agent works on a different aspect of the same feature, demonstrating branch/merge, conflict detection, and resolution.

## Demo Scenario

**Project**: "Build a User Authentication System"

**Agent A (Local)** — Works on "Password hashing and storage"
- Researches bcrypt vs argon2
- Writes a decision to use bcrypt
- Writes implementation plan

**Agent B (Cloud)** — Works on "Session management"
- Researches JWT vs session cookies
- Writes a decision to use JWT
- Writes implementation plan

**Agent C (Browser)** — Works on "UI login form"
- Designs the login form layout
- Writes the HTML/CSS spec

All three agents work concurrently, occasionally writing to shared parents (the project spec). The demo shows:
1. Agents working in parallel
2. Auto-merge of non-overlapping writes
3. Conflict detection if agents write overlapping decisions
4. Conflict resolution via the browser UI

## Demo Script

Create `scripts/demo-multi-agent.sh` that:

```bash
#!/bin/bash
# Start Loom services
docker-compose up -d

# Create a demo project
python -m scripts.create_demo_project

# Start the browser UI
open web/index.html

# Start all 3 agents concurrently
python -m agents.local.agent \
    --project $(cat /tmp/demo_project_id) \
    --task "Design password hashing" \
    --name "Agent A (Local)" &

python -m agents.cloud.agent \
    --project $(cat /tmp/demo_project_id) \
    --task "Design session management" \
    --name "Agent B (Cloud)" &

python -m agents.browser.agent \
    --project $(cat /tmp/demo_project_id) \
    --task "Design login form" \
    --name "Agent C (Browser)" &

wait
echo "Demo complete! Open the browser UI to see results."
```

## Demo Visualization

The browser UI should highlight:
- Which agent wrote which context unit (color-coded)
- Branch structure (which units are on which branch)
- Merge points (where branches were merged)
- Conflicts (which units conflicted and how they were resolved)

A "Demo Mode" overlay in the UI shows:
- Animation of agents writing in real time
- Branch visualization
- Conflict resolution steps

## File Targets
- `scripts/demo-multi-agent.sh` — demo runner script
- `scripts/create_demo_project.py` — creates a demo project with sample data
- `agents/browser/agent.py` — simple browser agent stub (simulated)
- `agents/cloud/agent.py` — simple cloud agent stub (simulated)
- `web/demo-mode.js` — demo visualization overlay

## Acceptance Criteria
- [ ] All 3 agents start and work concurrently
- [ ] Each agent writes at least 3 context units
- [ ] Non-overlapping writes are auto-merged
- [ ] Overlapping writes are detected and flagged
- [ ] Conflicts are resolvable via the browser UI
- [ ] The demo can be re-run (idempotent)
- [ ] The demo completes in under 2 minutes

## TDD Instructions
```python
@pytest.mark.asyncio
async def test_multi_agent_demo_runs(demo_runner):
    result = await demo_runner.run()
    assert result.agents_completed == 3
    assert result.total_writes >= 9
    assert result.auto_merges >= 1

@pytest.mark.asyncio
async def test_demo_is_idempotent(demo_runner):
    result1 = await demo_runner.run()
    result2 = await demo_runner.run()
    # Second run creates a fresh project
    assert result1.project_id != result2.project_id
```

## Dependencies
- Phase 2.1 (full coordination with branch/merge)
- Phase 2.5 (interactive UI with conflict resolution)
