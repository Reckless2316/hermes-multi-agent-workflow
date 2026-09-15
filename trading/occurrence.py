"""Trading occurrence dedup that does not permanently suppress repeat setups."""
from __future__ import annotations

from typing import Any, Iterable

# These states represent an occurrence still being evaluated by Hermes.  Once a
# proposal has moved past this workflow phase, exact-open broker/paper checks are
# the authoritative protection against simultaneous duplicate positions.
ACTIVE_WORKFLOW_STATUSES = {
    "triage",
    "research",
    "routed",
    "awaiting_approval",
    "awaiting_redraft",
}


def find_active_occurrence(
    candidate_id: str,
    items: Iterable[tuple[str, dict[str, Any]]],
) -> str | None:
    """Return the slug of an active item with the same deterministic candidate id."""
    for slug, frontmatter in items:
        if str(frontmatter.get("candidate_id") or "") != candidate_id:
            continue
        if str(frontmatter.get("status") or "") in ACTIVE_WORKFLOW_STATUSES:
            return slug
    return None
