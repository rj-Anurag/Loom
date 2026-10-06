"""Prompt-specific, cited context bundles for coding harnesses."""

from __future__ import annotations

import asyncio
import logging
import math
import re
import uuid
from collections import defaultdict
from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from loom.config import settings
from loom.models import ContextEdge, ContextUnit
from loom.services.context.service import _validate_context_reader
from loom.services.retrieval.providers import from_llm_config
from loom.services.retrieval.search import encode_query, vector_search

logger = logging.getLogger(__name__)
_STOP = {
    "about",
    "after",
    "again",
    "agent",
    "could",
    "from",
    "have",
    "into",
    "loom",
    "please",
    "that",
    "them",
    "there",
    "these",
    "this",
    "what",
    "when",
    "where",
    "which",
    "with",
    "would",
    "your",
    "fix",
    "add",
    "implement",
    "update",
    "check",
    "make",
    "code",
    "issue",
    "project",
    "using",
    "work",
}


def _terms(prompt: str) -> list[str]:
    return list(
        dict.fromkeys(
            word for word in re.findall(r"[a-z0-9_]{3,}", prompt.lower()) if word not in _STOP
        )
    )[:16]


def _source_key(unit: ContextUnit) -> tuple[str, str]:
    return (unit.source_type, unit.source_url or unit.source_session_id or str(unit.id))


def _unit_dict(unit: ContextUnit, citation: int) -> dict[str, Any]:
    return {
        "citation": citation,
        "id": str(unit.id),
        "type": unit.type.value,
        "content": unit.content,
        "source_type": unit.source_type,
        "source_url": unit.source_url,
        "source_session_id": unit.source_session_id,
        "occurred_at": unit.occurred_at.isoformat(),
    }


def _fallback_brief(evidence: list[dict[str, Any]]) -> str:
    lines = ["Relevant Loom history (historical evidence):"]
    for item in evidence[:5]:
        excerpt = " ".join(item["content"].split())[:160]
        lines.append(f"[{item['citation']}] {excerpt}")
    return "\n".join(lines)


async def build_context_bundle(
    session: AsyncSession,
    project_id: uuid.UUID,
    agent_id: uuid.UUID | None,
    *,
    prompt: str,
    budget: int = 4096,
) -> dict[str, Any]:
    """Search one project, expand matching sources and links, and pack cited evidence."""
    await _validate_context_reader(session, project_id, agent_id)
    budget = min(max(budget, 1), 32000)
    terms = _terms(prompt)
    if not terms:
        return {"brief": "", "evidence": [], "total_tokens": 0, "truncated": False}

    # OR semantics keep a long user prompt from requiring every word to match.
    query = " | ".join(terms)
    rank = func.ts_rank(
        func.to_tsvector("english", ContextUnit.content),
        func.to_tsquery("english", query),
    )
    rows = await session.execute(
        select(ContextUnit, rank.label("rank"))
        .where(ContextUnit.project_id == project_id, rank > 0)
        .order_by(rank.desc(), ContextUnit.occurred_at.desc())
        .limit(80)
    )
    matches = list(rows.all())
    semantic_scores: dict[uuid.UUID, float] = {}
    if settings.embedding_provider != "stub":
        try:
            embedding = await asyncio.wait_for(encode_query(prompt), timeout=2)
            if embedding is not None:
                vector_matches = await vector_search(session, project_id, embedding)
                semantic_scores = {
                    uuid.UUID(item["id"]): item["vector_score"]
                    for item in vector_matches[:16]
                    if item["vector_score"] >= 0.55
                }
                semantic_ids = list(semantic_scores)
                if semantic_ids:
                    semantic_rows = await session.execute(
                        select(ContextUnit).where(
                            ContextUnit.project_id == project_id,
                            ContextUnit.id.in_(semantic_ids),
                        )
                    )
                    seen_ids = {unit.id for unit, _ in matches}
                    matches.extend(
                        (unit, 0.0) for unit in semantic_rows.scalars() if unit.id not in seen_ids
                    )
        except Exception:
            logger.warning("Semantic bundle lookup failed; using text matches", exc_info=True)
    if not matches:
        return {"brief": "", "evidence": [], "total_tokens": 0, "truncated": False}

    def relevance(unit: ContextUnit, lexical_rank: float) -> float:
        words = set(re.findall(r"[a-z0-9_]{3,}", unit.content.lower()))
        overlap = len(words.intersection(terms)) / len(terms)
        return overlap + min(float(lexical_rank), 1.0) * 0.1

    matches.sort(
        key=lambda row: max(relevance(row[0], row[1]), semantic_scores.get(row[0].id, 0)),
        reverse=True,
    )
    seeds = [unit for unit, _ in matches[:8]]
    seed_ids = {unit.id for unit in seeds}
    selected: dict[uuid.UUID, ContextUnit] = {unit.id: unit for unit in seeds}

    # Capture the adjacent turns of each matched conversation, bounded per source.
    for seed in seeds:
        if not (seed.source_url or seed.source_session_id):
            continue
        source_filter = (
            ContextUnit.source_url == seed.source_url
            if seed.source_url
            else ContextUnit.source_session_id == seed.source_session_id
        )
        for comparison, direction in (
            (ContextUnit.occurred_at <= seed.occurred_at, "before"),
            (ContextUnit.occurred_at >= seed.occurred_at, "after"),
        ):
            statement = select(ContextUnit).where(
                ContextUnit.project_id == project_id,
                ContextUnit.source_type == seed.source_type,
                source_filter,
                comparison,
            )
            statement = (
                statement.order_by(ContextUnit.occurred_at.desc(), ContextUnit.id.desc())
                if direction == "before"
                else statement.order_by(ContextUnit.occurred_at, ContextUnit.id)
            )
            neighbor_rows = await session.execute(statement.limit(3))
            for neighbor in neighbor_rows.scalars():
                selected[neighbor.id] = neighbor

    # Both ends of a decision/result link are useful, but never cross projects.
    edge_rows = await session.execute(
        select(ContextEdge.parent_id, ContextEdge.child_id).where(
            or_(ContextEdge.parent_id.in_(seed_ids), ContextEdge.child_id.in_(seed_ids))
        )
    )
    linked_ids = {
        linked
        for parent, child in edge_rows
        for linked in (parent, child)
        if linked not in selected
    }
    if linked_ids:
        linked_rows = await session.execute(
            select(ContextUnit)
            .where(
                ContextUnit.project_id == project_id,
                ContextUnit.id.in_(linked_ids),
            )
            .limit(32)
        )
        for unit in linked_rows.scalars():
            if unit.type.value in {"decision", "task_result", "summary"}:
                selected[unit.id] = unit

    groups: dict[tuple[str, str], list[ContextUnit]] = defaultdict(list)
    for unit in selected.values():
        groups[_source_key(unit)].append(unit)
    ordered = sorted(
        groups.values(),
        key=lambda units: (
            not any(unit.id in seed_ids for unit in units),
            min(
                (
                    next((index for index, seed in enumerate(seeds) if seed.id == unit.id), 99)
                    for unit in units
                ),
                default=99,
            ),
        ),
    )

    # Reserve space for the brief and formatting added by the harness hook.
    header_allowance = min(200, max(100, budget * 4 // 8))
    brief_allowance = min(1200, max(100, budget * 4 // 4))
    evidence_limit = max(0, budget * 4 - header_allowance - brief_allowance)
    evidence: list[dict[str, Any]] = []
    used = 0
    truncated = False
    for group in ordered:
        for unit in sorted(group, key=lambda item: (item.occurred_at, item.id)):
            item = _unit_dict(unit, len(evidence) + 1)
            overhead = (
                len(item["id"])
                + len(item["source_type"])
                + 2 * len(item["source_url"] or item["source_session_id"] or "")
                + 120
            )
            remaining = evidence_limit - used - overhead
            if remaining <= 0:
                truncated = True
                break
            if len(item["content"]) > remaining:
                item["content"] = item["content"][:remaining]
                truncated = True
            evidence.append(item)
            used += len(item["content"]) + overhead
        if truncated:
            break

    if not evidence:
        return {"brief": "", "evidence": [], "total_tokens": 0, "truncated": True}
    brief = _fallback_brief(evidence)
    if settings.summarization_provider != "stub":
        try:
            provider = from_llm_config()
            generated = await asyncio.wait_for(
                provider.summarize(
                    [
                        {
                            "id": f"[{item['citation']}]",
                            "type": item["type"],
                            "content": f"[{item['citation']}] {item['content']}",
                            "trust_tier": "external_tool",
                        }
                        for item in evidence
                    ]
                ),
                timeout=2,
            )
            if generated.strip():
                brief = (
                    generated.strip()[:600]
                    + "\nSources: "
                    + ", ".join(f"[{item['citation']}]" for item in evidence[:8])
                )
        except Exception:
            logger.warning("Bundle summarization failed; using deterministic brief", exc_info=True)
    brief = brief[: max(0, budget * 4 - used - header_allowance)]
    return {
        "brief": brief,
        "evidence": evidence,
        "total_tokens": math.ceil((len(brief) + used + header_allowance) / 4),
        "truncated": truncated,
    }
