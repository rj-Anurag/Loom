"""Project summary coverage, citations, and incremental compaction."""

import uuid
from types import SimpleNamespace

import pytest

from loom.models import ContextUnitType
from loom.services.context.project_summary import _fallback, _response, _summarize_updates


def unit(content: str, type_: ContextUnitType = ContextUnitType.message):
    return SimpleNamespace(id=uuid.uuid4(), content=content, type=type_)


async def test_summary_reads_long_history_in_bounded_batches_and_carries_previous_state():
    history = [unit(f"Turn {i}: " + "x" * 5000) for i in range(12)]
    history[-1].content += " END_OF_HISTORY"
    numbers = {str(item.id): i for i, item in enumerate(history, 2)}
    numbers["earlier-source"] = 1
    calls = []

    class Provider:
        async def summarize(self, inputs):
            calls.append(inputs)
            return "## Overview\n- Earlier constraint survives [1].\n- Updated facts [2]."

    summary = await _summarize_updates(
        Provider(), history, numbers, "Earlier constraint survives [1]."
    )
    assert len(calls) > 1
    assert all(call[0]["type"] == "summary" for call in calls)
    assert all("Earlier constraint survives" in call[0]["content"] for call in calls)
    assert all(sum(len(item["content"]) for item in call) < 23000 for call in calls)
    fragments = [item["content"] for call in calls for item in call if item["type"] != "summary"]
    assert "END_OF_HISTORY" in fragments[-1]
    assert all(
        any(f"[{numbers[str(item.id)]}]" in fragment for fragment in fragments) for item in history
    )
    assert "[1]" in summary


@pytest.mark.parametrize(
    "generated",
    [
        "",
        "Uncited assertion",
        "## Overview\n- Invented source [999]",
        "Cited but unstructured [1]",
        "## Overview\n- Cited [1]\n- Uncited",
        "## Overview\n- Cited [1]\n## Sources\n- Source [1]",
    ],
)
async def test_summary_rejects_missing_or_invented_citations(generated):
    item = unit("Aurora is teal")

    class Provider:
        async def summarize(self, inputs):
            return generated

    with pytest.raises(ValueError, match="cite its original evidence|structured sections"):
        await _summarize_updates(Provider(), [item], {str(item.id): 1})


def test_fallback_preserves_older_decision_and_exposes_only_referenced_sources():
    decision = unit("Retry limit is seven", ContextUnitType.decision)
    history = [decision, *(unit(f"Recent turn {i}") for i in range(12))]
    numbers = {str(item.id): i for i, item in enumerate(history, 1)}
    summary = _fallback(history, numbers)
    assert summary.startswith("## Overview\n- ")
    assert "Retry limit is seven" in summary
    assert "Recent turn 11" in summary
    response = _response(
        summary,
        [{"id": str(item.id), "number": numbers[str(item.id)]} for item in history],
        None,
        "extractive",
    )
    assert response["context_count"] == 13
    assert len(response["citations"]) == 9
    assert response["citations"][0]["id"] == str(decision.id)
