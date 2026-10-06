"""Incremental project overviews, rebuilt when their source evidence is removed."""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import re
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from loom.models import ChatLink, ContextUnit, ContextUnitType, Project
from loom.services.retrieval.providers import (
    LLMProvider,
    effective_llm_provider_name,
    from_llm_config,
)

logger = logging.getLogger(__name__)
SUMMARY_FORMAT_REVISION = "structured-v1"


@dataclass(frozen=True)
class LinkedChatRecord:
    id: uuid.UUID
    content: str
    created_at: datetime
    source_url: str
    type: ContextUnitType = ContextUnitType.artifact_ref
    source_type: str = "browser_chat"
    source_session_id: str | None = None
    agent_id: uuid.UUID | None = None


SummaryRecord = ContextUnit | LinkedChatRecord


def _response(
    content: str,
    citations: list[dict[str, Any]],
    updated_at: datetime | None,
    mode: str,
    context_count: int | None = None,
) -> dict[str, Any]:
    referenced = {int(number) for number in re.findall(r"\[(\d+)\]", content)}
    return {
        "summary": content,
        "citations": [item for item in citations if item["number"] in referenced],
        "context_count": context_count if context_count is not None else len(citations),
        "updated_at": updated_at.isoformat() if updated_at else None,
        "mode": mode,
    }


def _fallback(units: Sequence[SummaryRecord], numbers: dict[str, int]) -> str:
    if not units:
        return "## Overview\n- No project memory has been captured yet."
    important = [
        unit
        for unit in units
        if unit.type
        in {
            ContextUnitType.decision,
            ContextUnitType.task_result,
        }
    ][-4:]
    selected = {unit.id: unit for unit in [*important, *units[-8:]]}
    return "## Overview\n" + "\n".join(
        f"- {' '.join(unit.content.split())[:240]} [{numbers[str(unit.id)]}]"
        for unit in selected.values()
    )


async def _summarize_updates(
    provider: LLMProvider,
    units: Sequence[SummaryRecord],
    numbers: dict[str, int],
    previous: str = "",
) -> str:
    """Feed all new content in bounded batches, carrying the prior summary forward."""
    summary = previous
    batch: list[dict[str, Any]] = []
    size = 0
    allowed = set(numbers.values())
    batch_limit = getattr(provider, "SUMMARY_BATCH_CHARS", 18000)
    timeout = getattr(provider, "SUMMARY_TIMEOUT_SECONDS", 30)

    async def summarize_batch() -> str:
        inputs = []
        if summary:
            inputs.append(
                {
                    "type": "summary",
                    "trust_tier": "external_tool",
                    "output_format": "project_summary",
                    "content": (
                        "Previous project summary; update with the following history:\n" + summary
                    ),
                }
            )
        current_batch = [*batch]
        if not inputs:
            current_batch[0] = {**current_batch[0], "output_format": "project_summary"}
        request = [*inputs, *current_batch]

        def validate(generated: str) -> str:
            generated = generated.strip()[:3500]
            references = {int(number) for number in re.findall(r"\[(\d+)\]", generated)}
            if not generated or not references or not references.issubset(allowed):
                raise ValueError("Project summary must cite its original evidence")
            bullets = re.findall(r"(?m)^- .+", generated)
            if (
                not re.search(r"(?m)^## Overview\s*$", generated)
                or not bullets
                or any(not re.search(r"\[\d+\]", bullet) for bullet in bullets)
                or re.search(r"(?im)^## Sources\s*$", generated)
            ):
                raise ValueError("Project summary must have structured sections")
            return generated

        generated = await asyncio.wait_for(provider.summarize(request), timeout=timeout)
        try:
            return validate(generated)
        except ValueError:
            retry = [
                {**item, "output_format": "project_summary_retry"}
                if item.get("output_format") == "project_summary"
                else item
                for item in request
            ]
            generated = await asyncio.wait_for(provider.summarize(retry), timeout=timeout)
            return validate(generated)

    for unit in units:
        for offset in range(0, len(unit.content), 3000):
            content = f"[{numbers[str(unit.id)]}] {unit.content[offset : offset + 3000]}"
            if batch and size + len(content) > batch_limit:
                summary = await summarize_batch()
                batch = []
                size = 0
            batch.append(
                {
                    "id": str(unit.id),
                    "type": unit.type.value,
                    "trust_tier": "external_tool",
                    "content": content,
                }
            )
            size += len(content)
    if batch:
        summary = await summarize_batch()
    return summary


async def _last_removal(session: AsyncSession, project_id: uuid.UUID) -> datetime | None:
    return (
        await session.execute(
            text("SELECT max(removed_at) FROM removed_sources WHERE project_id = :project_id"),
            {"project_id": project_id},
        )
    ).scalar_one_or_none()


async def get_project_summary(session: AsyncSession, project_id: uuid.UUID) -> dict[str, Any]:
    """Return or refresh the overview; concurrent workers share one generation lock."""
    count, latest = (
        await session.execute(
            select(func.count(ContextUnit.id), func.max(ContextUnit.created_at)).where(
                ContextUnit.project_id == project_id,
                ContextUnit.removed_at.is_(None),
                ContextUnit.type != ContextUnitType.summary,
            )
        )
    ).one()
    link_count, latest_link = (
        await session.execute(
            select(func.count(ChatLink.id), func.max(ChatLink.linked_at)).where(
                ChatLink.project_id == project_id,
                ChatLink.removed_at.is_(None),
            )
        )
    ).one()
    removed_at = await _last_removal(session, project_id)
    provider_name = effective_llm_provider_name()
    digest = hashlib.sha256(
        f"{count}:{latest}:{link_count}:{latest_link}:{removed_at}".encode()
    ).hexdigest()
    revision = f":{provider_name}:{SUMMARY_FORMAT_REVISION}:{digest}"
    cached = (
        (
            await session.execute(
                text(
                    "SELECT source_revision, content, citations, updated_at FROM project_summaries "
                    "WHERE project_id = :project_id"
                ),
                {"project_id": project_id},
            )
        )
        .mappings()
        .first()
    )
    if cached and cached["source_revision"].endswith(revision):
        mode = cached["source_revision"].split(":", 1)[0]
        retry_due = (
            mode == "fallback" and (datetime.now(UTC) - cached["updated_at"]).total_seconds() >= 60
        )
        if not retry_due:
            return _response(
                cached["content"], cached["citations"], cached["updated_at"], mode, count
            )

    locked = (
        await session.execute(
            text(
                "SELECT pg_try_advisory_xact_lock(hashtext('loom-project-summary'), hashtext(:id))"
            ),
            {"id": str(project_id)},
        )
    ).scalar_one()
    if not locked:
        return _response("Updating project summary…", [], None, "pending")

    units = list(
        (
            await session.execute(
                select(ContextUnit)
                .where(
                    ContextUnit.project_id == project_id,
                    ContextUnit.removed_at.is_(None),
                    ContextUnit.type != ContextUnitType.summary,
                )
                .order_by(ContextUnit.created_at, ContextUnit.id)
            )
        )
        .scalars()
        .all()
    )
    links = list(
        (
            await session.execute(
                select(ChatLink)
                .where(
                    ChatLink.project_id == project_id,
                    ChatLink.removed_at.is_(None),
                )
                .order_by(ChatLink.linked_at, ChatLink.id)
            )
        )
        .scalars()
        .all()
    )
    records: list[SummaryRecord] = sorted(
        [
            *units,
            *(
                LinkedChatRecord(
                    id=link.id,
                    content=f"Linked browser conversation: {link.title or 'Untitled conversation'} "
                    f"({link.platform or 'browser'}) at {link.chat_url}",
                    created_at=link.linked_at,
                    source_url=link.chat_url,
                )
                for link in links
            ),
        ],
        key=lambda item: (item.created_at, item.id),
    )
    current_ids = {str(item.id) for item in records}
    prior_citations = list(cached["citations"]) if cached else []
    prior_ids = {item["id"] for item in prior_citations}
    incremental = bool(
        cached
        and cached["source_revision"].startswith(f"ai:{provider_name}:{SUMMARY_FORMAT_REVISION}:")
        and prior_ids.issubset(current_ids)
        and (removed_at is None or cached["updated_at"] > removed_at)
    )
    citations = prior_citations if incremental else []
    numbers = {item["id"]: item["number"] for item in citations}
    for unit in records:
        if str(unit.id) in numbers:
            continue
        number = len(citations) + 1
        numbers[str(unit.id)] = number
        item = {
            "number": number,
            "id": str(unit.id),
            "source_type": unit.source_type,
            "excerpt": unit.content[:500],
        }
        if unit.agent_id is not None:
            item["agent_id"] = str(unit.agent_id)
        if unit.source_type == "browser_chat" and unit.source_url:
            item["source_url"] = unit.source_url
        elif unit.source_session_id:
            item["source_session_id"] = unit.source_session_id
        citations.append(item)

    summary = _fallback(records, numbers)
    mode = "extractive" if records else "empty"
    if records and provider_name != "stub":
        try:
            updates = [unit for unit in records if not incremental or str(unit.id) not in prior_ids]
            summary = await _summarize_updates(
                from_llm_config(),
                updates,
                numbers,
                cached["content"] if incremental and cached else "",
            )
            mode = "ai"
        except Exception:
            mode = "fallback"
            logger.warning(
                "Project summary provider failed; retaining source highlights", exc_info=True
            )

    # Deletion during an LLM call must not publish a summary of the deleted evidence.
    await session.get(Project, project_id, with_for_update={"read": True})
    if await _last_removal(session, project_id) != removed_at:
        await session.rollback()
        return _response("Updating project summary…", [], None, "pending")
    updated_at = datetime.now(UTC)
    await session.execute(
        text(
            "INSERT INTO project_summaries "
            "(project_id, source_revision, content, citations, updated_at) "
            "VALUES (:project_id, :revision, :content, CAST(:citations AS jsonb), :updated_at) "
            "ON CONFLICT (project_id) DO UPDATE SET "
            "source_revision = EXCLUDED.source_revision, content = EXCLUDED.content, "
            "citations = EXCLUDED.citations, updated_at = EXCLUDED.updated_at"
        ),
        {
            "project_id": project_id,
            "revision": mode + revision,
            "content": summary,
            "citations": json.dumps(citations),
            "updated_at": updated_at,
        },
    )
    await session.commit()
    return _response(summary, citations, updated_at, mode, len(units))
