"""Exact candidate selection from a deterministic scanner JSON sidecar."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any


class SidecarSelectionError(ValueError):
    pass


def select_candidate(sidecar: dict[str, Any], candidate_id: str) -> dict[str, Any]:
    matches = [
        candidate
        for candidate in (sidecar.get("candidates") or [])
        if isinstance(candidate, dict)
        and str(candidate.get("candidate_id") or "") == candidate_id
    ]
    if len(matches) != 1:
        raise SidecarSelectionError(
            f"Expected exactly one candidate_id={candidate_id!r}; found {len(matches)}"
        )
    return matches[0]


def load_candidate(path: str | Path, candidate_id: str) -> dict[str, Any]:
    sidecar = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(sidecar, dict):
        raise SidecarSelectionError("Sidecar root must be a JSON object")
    return select_candidate(sidecar, candidate_id)


def write_candidate(
    sidecar_path: str | Path,
    candidate_id: str,
    output_path: str | Path,
) -> Path:
    candidate = load_candidate(sidecar_path, candidate_id)
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    temp = output.with_suffix(output.suffix + ".tmp")
    temp.write_text(
        json.dumps(candidate, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temp.replace(output)
    return output
