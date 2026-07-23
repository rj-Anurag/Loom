"""Integration tests for the core database schema.

These tests verify:
- All tables exist with correct columns and constraints
- Immutability of the event_log (append-only trigger)
- UNIQUE constraint on client_uuid for idempotency
- CHECK constraints on resolution field
- Foreign key referential integrity
"""

import uuid

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from loom.models import (
    Agent,
    ContextUnit,
    ContextUnitType,
    EventLog,
    EventType,
    PendingBranch,
    Project,
    TrustTier,
)


# ── Helpers ──────────────────────────────────────────────────────────────────


async def _table_exists(db_session: AsyncSession, table: str) -> bool:
    result = await db_session.execute(
        text(
            "SELECT EXISTS ("
            "  SELECT FROM information_schema.tables "
            "  WHERE table_schema = 'public' AND table_name = :table"
            ")"
        ),
        {"table": table},
    )
    return bool(result.scalar())


async def _project(db_session: AsyncSession) -> Project:
    p = Project(name="Test Project")
    db_session.add(p)
    await db_session.commit()
    await db_session.refresh(p)
    return p


async def _agent(db_session: AsyncSession, project: Project) -> Agent:
    a = Agent(project_id=project.id, kind="local")
    db_session.add(a)
    await db_session.commit()
    await db_session.refresh(a)
    return a


# ── Schema Existence ─────────────────────────────────────────────────────────


@pytest.mark.parametrize("table", ["projects", "agents", "context_units", "context_edges", "event_log", "pending_branches"])
@pytest.mark.asyncio
async def test_table_exists(db_session: AsyncSession, table: str) -> None:
    """All 6 core tables must exist."""
    assert await _table_exists(db_session, table), f"Table '{table}' does not exist"


@pytest.mark.asyncio
async def test_context_units_has_all_columns(db_session: AsyncSession) -> None:
    """context_units must have all required columns including trust_tier and client_uuid."""
    result = await db_session.execute(
        text(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_schema = 'public' AND table_name = 'context_units'"
        )
    )
    columns = {row.column_name for row in result}
    required = {
        "id", "project_id", "agent_id", "client_uuid", "type",
        "trust_tier", "content", "embedding", "version", "branch_id", "created_at",
    }
    missing = required - columns
    assert not missing, f"Missing columns in context_units: {missing}"


@pytest.mark.asyncio
async def test_client_uuid_is_unique(db_session: AsyncSession) -> None:
    """client_uuid has a UNIQUE constraint for idempotency."""
    result = await db_session.execute(
        text(
            "SELECT COUNT(*) FROM information_schema.table_constraints tc "
            "JOIN information_schema.constraint_column_usage ccu "
            "  ON tc.constraint_name = ccu.constraint_name "
            "WHERE tc.table_schema = 'public' "
            "  AND tc.table_name = 'context_units' "
            "  AND tc.constraint_type = 'UNIQUE' "
            "  AND ccu.column_name = 'client_uuid'"
        )
    )
    count = result.scalar()
    assert count and int(count) > 0, "client_uuid is not UNIQUE"


@pytest.mark.asyncio
async def test_context_units_has_foreign_keys(db_session: AsyncSession) -> None:
    """context_units has FKs: project_id → projects, agent_id → agents."""
    result = await db_session.execute(
        text(
            "SELECT kcu.column_name, ccu.table_name AS ref_table "
            "FROM information_schema.table_constraints tc "
            "JOIN information_schema.key_column_usage kcu "
            "  ON tc.constraint_name = kcu.constraint_name "
            "  AND tc.table_schema = kcu.table_schema "
            "  AND tc.table_name = kcu.table_name "
            "JOIN information_schema.constraint_column_usage ccu "
            "  ON tc.constraint_name = ccu.constraint_name "
            "  AND tc.table_schema = ccu.table_schema "
            "WHERE tc.table_schema = 'public' "
            "  AND tc.table_name = 'context_units' "
            "  AND tc.constraint_type = 'FOREIGN KEY'"
        )
    )
    refs = {row.column_name: row.ref_table for row in result}
    assert refs.get("project_id") == "projects"
    assert refs.get("agent_id") == "agents"


# ── CRUD Operations ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_create_context_unit(db_session: AsyncSession) -> None:
    """Insert a context_unit and verify defaults and fields."""
    proj = await _project(db_session)
    ag = await _agent(db_session, proj)

    unit = ContextUnit(
        project_id=proj.id,
        agent_id=ag.id,
        client_uuid=uuid.uuid4(),
        type=ContextUnitType.decision,
        content="Use bcrypt for password hashing",
    )
    db_session.add(unit)
    await db_session.commit()
    await db_session.refresh(unit)

    assert unit.id is not None
    assert unit.trust_tier == TrustTier.agent
    assert unit.version == 1
    assert unit.content == "Use bcrypt for password hashing"
    assert unit.created_at is not None


@pytest.mark.asyncio
async def test_create_all_context_unit_types(db_session: AsyncSession) -> None:
    """All ContextUnitType enum values can be inserted."""
    proj = await _project(db_session)
    ag = await _agent(db_session, proj)

    for unit_type in ContextUnitType:
        unit = ContextUnit(
            project_id=proj.id,
            agent_id=ag.id,
            client_uuid=uuid.uuid4(),
            type=unit_type,
            content=f"Test {unit_type.value}",
        )
        db_session.add(unit)
    await db_session.commit()

    result = await db_session.execute(
        text("SELECT COUNT(*) FROM context_units WHERE project_id = :pid"),
        {"pid": proj.id},
    )
    assert result.scalar() == len(list(ContextUnitType))


@pytest.mark.asyncio
async def test_trust_tier_default(db_session: AsyncSession) -> None:
    """Default trust_tier should be 'agent'."""
    proj = await _project(db_session)
    ag = await _agent(db_session, proj)

    unit = ContextUnit(
        project_id=proj.id,
        agent_id=ag.id,
        client_uuid=uuid.uuid4(),
        type=ContextUnitType.message,
        content="Hello",
    )
    db_session.add(unit)
    await db_session.commit()
    await db_session.refresh(unit)
    assert unit.trust_tier == TrustTier.agent


# ── Immutability ─────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_event_log_cannot_update(db_session: AsyncSession) -> None:
    """UPDATE on event_log must be prevented by trigger."""
    proj = await _project(db_session)
    event = EventLog(
        project_id=proj.id,
        event_type=EventType.write,
        payload={"test": True},
    )
    db_session.add(event)
    await db_session.commit()
    await db_session.refresh(event)

    with pytest.raises(Exception):
        await db_session.execute(
            text("UPDATE event_log SET payload = '{}' WHERE id = :eid"),
            {"eid": event.id},
        )
        await db_session.commit()


@pytest.mark.asyncio
async def test_event_log_cannot_delete(db_session: AsyncSession) -> None:
    """DELETE on event_log must be prevented by trigger."""
    proj = await _project(db_session)
    event = EventLog(
        project_id=proj.id,
        event_type=EventType.write,
        payload={"test": True},
    )
    db_session.add(event)
    await db_session.commit()
    await db_session.refresh(event)

    with pytest.raises(Exception):
        await db_session.execute(
            text("DELETE FROM event_log WHERE id = :eid"),
            {"eid": event.id},
        )
        await db_session.commit()


# ── Idempotency ──────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_duplicate_client_uuid_fails(db_session: AsyncSession) -> None:
    """Inserting with the same client_uuid twice should fail."""
    proj = await _project(db_session)
    ag = await _agent(db_session, proj)
    client_uuid = uuid.uuid4()

    unit1 = ContextUnit(
        project_id=proj.id,
        agent_id=ag.id,
        client_uuid=client_uuid,
        type=ContextUnitType.message,
        content="First write",
    )
    db_session.add(unit1)
    await db_session.commit()

    unit2 = ContextUnit(
        project_id=proj.id,
        agent_id=ag.id,
        client_uuid=client_uuid,
        type=ContextUnitType.message,
        content="Duplicate write",
    )
    db_session.add(unit2)
    with pytest.raises(Exception):
        await db_session.commit()
    await db_session.rollback()


# ── Pending Branches Constraints ─────────────────────────────────────────────


@pytest.mark.asyncio
async def test_pending_branches_valid_resolution_values(db_session: AsyncSession) -> None:
    """Valid resolution values should be accepted."""
    proj = await _project(db_session)
    ag = await _agent(db_session, proj)

    unit = ContextUnit(
        project_id=proj.id,
        agent_id=ag.id,
        client_uuid=uuid.uuid4(),
        type=ContextUnitType.decision,
        content="Test",
    )
    db_session.add(unit)
    await db_session.commit()
    await db_session.refresh(unit)

    for resolution in ("pending", "auto_merged", "resolved"):
        branch = PendingBranch(
            context_unit_id=unit.id,
            conflict_type="test",
            resolution=resolution,
        )
        db_session.add(branch)
        await db_session.commit()


@pytest.mark.asyncio
async def test_pending_branches_invalid_resolution_fails(db_session: AsyncSession) -> None:
    """Invalid resolution value should be rejected."""
    proj = await _project(db_session)
    ag = await _agent(db_session, proj)

    unit = ContextUnit(
        project_id=proj.id,
        agent_id=ag.id,
        client_uuid=uuid.uuid4(),
        type=ContextUnitType.decision,
        content="Test",
    )
    db_session.add(unit)
    await db_session.commit()
    await db_session.refresh(unit)

    branch = PendingBranch(
        context_unit_id=unit.id,
        conflict_type="test",
        resolution="invalid_value",
    )
    db_session.add(branch)
    with pytest.raises(Exception):
        await db_session.commit()
    await db_session.rollback()
