"""Scoring — turn a candidate into a number, decide if it clears the bar.

The engine supports TWO scoring modes (the template ships both; pick per domain):

1. LLM mode (recommended for production, general):
   The orchestrator reads the rubric, judges each dimension itself, and returns a
   per-dimension breakdown. `score_from_breakdown()` validates that breakdown
   against the configured maxes and applies the threshold. Use `rubric_prompt()`
   to build the instruction you hand the orchestrator.

   This mode is fully general — it works for ANY rubric you put in triage.yaml,
   because the judgment lives in the model, not in code.

2. Heuristic mode (deterministic, testable, reference-domain only):
   `score_candidate_heuristic()` scores from structured candidate fields with no
   model call. It is keyed to the REFERENCE rubric dimensions and is meant as a
   deterministic fallback and a test fixture. If you change the rubric
   dimensions, this function will not understand the new keys — either update it
   or rely on LLM mode. It will warn (via metadata) when it sees unknown keys.

Both return a `ScoreResult`. Both read maxes/threshold from `triage.yaml`.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .config import Rubric


@dataclass
class ScoreResult:
    total: int
    breakdown: dict[str, int]
    advance: bool
    notes: list[str] = field(default_factory=list)


# --------------------------------------------------------------------------- #
# LLM mode
# --------------------------------------------------------------------------- #


def rubric_prompt(rubric: Rubric) -> str:
    """Build the scoring instruction handed to the orchestrator.

    The orchestrator returns a JSON object mapping each dimension key to an
    integer 0..max. Feed that dict to `score_from_breakdown()`.
    """
    lines = [
        "Score this candidate against the rubric below. For EACH dimension return",
        "an integer from 0 to its max. Be honest and conservative — inflating",
        "scores to keep weak items alive wastes the human's one approval.",
        "",
        "Return a JSON object: {\"<key>\": <int>, ...}. Dimensions:",
        "",
    ]
    for d in rubric.dimensions:
        hint = f" — {d.hint}" if d.hint else ""
        lines.append(f"- {d.key} (0..{d.max}){hint}")
    lines += [
        "",
        f"An item ADVANCES if the total is >= {rubric.threshold} (out of {rubric.max_total}).",
    ]
    return "\n".join(lines)


def score_from_breakdown(breakdown: dict[str, Any], rubric: Rubric) -> ScoreResult:
    """Validate an LLM-produced (or any) per-dimension breakdown and apply the bar."""
    notes: list[str] = []
    clean: dict[str, int] = {}
    valid_keys = {d.key: d.max for d in rubric.dimensions}

    for key, max_v in valid_keys.items():
        raw = breakdown.get(key, 0)
        try:
            val = int(round(float(raw)))
        except (TypeError, ValueError):
            val = 0
            notes.append(f"dimension {key!r} was non-numeric ({raw!r}); treated as 0.")
        if val < 0:
            val, _ = 0, notes.append(f"{key} < 0, clamped to 0.")
        if val > max_v:
            notes.append(f"{key} = {val} exceeds max {max_v}, clamped.")
            val = max_v
        clean[key] = val

    for extra in set(breakdown) - set(valid_keys):
        notes.append(f"ignored unknown dimension {extra!r} (not in rubric).")

    total = sum(clean.values())
    return ScoreResult(total=total, breakdown=clean, advance=total >= rubric.threshold, notes=notes)


# --------------------------------------------------------------------------- #
# Heuristic mode (reference-domain; deterministic; test fixture)
# --------------------------------------------------------------------------- #

# Keyword lists for heuristic mode. Production scoring is LLM mode against
# whatever dimensions live in triage.yaml; these rules are a deterministic
# fallback for tests and offline passes. Update them when the rubric keys change.
_HIGH_INTENSITY_TERMS = [
    "broken", "wasted hours", "gave up", "can't", "cannot", "failed", "blocked", "pain",
]
_KNOWN_HEURISTIC_DIMS = {
    "frequency", "intensity", "agent_solvable_or_explainable", "solution_gap", "strategic_fit",
    "setup_clarity", "risk_reward", "gate_completeness", "market_context", "uniqueness",
}


def score_candidate_heuristic(candidate: dict[str, Any], rubric: Rubric) -> ScoreResult:
    """Deterministic scorer keyed to known rubric dimensions.

    Reads each dimension's `max` from the rubric so the proportions stay correct
    even if you rescale. Unknown dimensions score 0 and are noted — use LLM mode
    or add a rule here.
    """
    notes: list[str] = []
    maxes = {d.key: d.max for d in rubric.dimensions}
    breakdown: dict[str, int] = {k: 0 for k in maxes}

    def scaled(key: str, fraction: float) -> int:
        if key not in maxes:
            return 0
        return int(round(maxes[key] * max(0.0, min(1.0, fraction))))

    text = " ".join(str(candidate.get(k, "")) for k in ("claim", "why_it_may_matter", "title", "reason")).lower()
    fields = candidate.get("fields") if isinstance(candidate.get("fields"), dict) else {}
    merged = {**fields, **{k: v for k, v in candidate.items() if k != "fields"}}

    def g(*keys: str, default: str = "") -> str:
        for k in keys:
            v = merged.get(k)
            if v not in (None, ""):
                return str(v)
        return default

    # frequency — by distinct source count (4+ saturates)
    if "frequency" in maxes:
        n = len(candidate.get("sources") or [])
        breakdown["frequency"] = scaled("frequency", min(n, 4) / 4)

    # intensity — by strong-language hits in the candidate text
    if "intensity" in maxes:
        hits = sum(1 for t in _HIGH_INTENSITY_TERMS if t in text)
        breakdown["intensity"] = scaled("intensity", 0.25 + 0.25 * hits)

    # agent_solvable_or_explainable — categorical field
    if "agent_solvable_or_explainable" in maxes:
        v = str(candidate.get("agent_solvable_or_explainable", "partial")).lower()
        frac = 1.0 if v in {"yes", "true", "agent", "explainable", "solvable"} else 0.0 if v in {"no", "false", "none"} else 0.4
        breakdown["agent_solvable_or_explainable"] = scaled("agent_solvable_or_explainable", frac)

    # solution_gap — categorical field
    if "solution_gap" in maxes:
        v = str(candidate.get("solution_gap", "partial")).lower()
        frac = 1.0 if v in {"no", "none", "missing", "broken"} else 0.0 if v in {"good", "solved"} else 0.53
        breakdown["solution_gap"] = scaled("solution_gap", frac)

    # strategic_fit — categorical field
    if "strategic_fit" in maxes:
        v = str(candidate.get("strategic_fit", "tangential")).lower()
        frac = 1.0 if v in {"yes", "true"} or "agent" in v else 0.0 if v in {"no", "false", "off"} else 0.47
        breakdown["strategic_fit"] = scaled("strategic_fit", frac)

    gates_raw = g("gates_passed", "gates")
    gates = [p.strip() for p in gates_raw.replace(";", ",").split(",") if p.strip()]
    status = g("setup_status", "status").upper()
    style = g("style").lower()

    if "setup_clarity" in maxes:
        frac = 0.35
        if status == "TAKE":
            frac = 0.7
        if status == "WAIT" and ("wait:" in text or "missing" in text):
            frac = 0.55
        if "dumb obvious" in text or len(gates) >= 4:
            frac = min(1.0, frac + 0.3)
        if "vibe" in text or "confluence" in text:
            frac = min(frac, 0.4)
        breakdown["setup_clarity"] = scaled("setup_clarity", frac)

    if "risk_reward" in maxes:
        frac = 0.3
        risk_r = g("risk_r", "r")
        try:
            r_val = float(risk_r)
            frac = 1.0 if r_val >= 2 else 0.75 if r_val >= 1 else 0.25
        except (TypeError, ValueError):
            if any(tok in text for tok in ("1r", "2r", "defined-risk", "defined risk", "max loss")):
                frac = 0.7
        if style == "options" and ("naked" in text or "undefined" in text):
            frac = 0.0
        breakdown["risk_reward"] = scaled("risk_reward", frac)

    if "gate_completeness" in maxes:
        needed = ("entry", "stop", "target")
        have = sum(1 for k in needed if g(k))
        frac = have / 3
        if len(gates) >= 3:
            frac = min(1.0, frac + 0.35)
        if style == "options" and g("structure") and g("max_loss"):
            frac = min(1.0, frac + 0.35)
        breakdown["gate_completeness"] = scaled("gate_completeness", frac)

    if "market_context" in maxes:
        frac = 0.4
        ctx = g("catalyst", "timeframe", "market_context").lower()
        if any(tok in (text + " " + ctx) for tok in ("htf", "aligned", "smt")):
            frac = 0.75
        if any(tok in text for tok in ("chop", "news", "fomc surprise")):
            frac = 0.25
        breakdown["market_context"] = scaled("market_context", frac)

    if "uniqueness" in maxes:
        frac = 0.8
        if any(tok in text for tok in ("duplicate", "invalidated", "blown level")):
            frac = 0.15
        breakdown["uniqueness"] = scaled("uniqueness", frac)

    unknown = set(maxes) - _KNOWN_HEURISTIC_DIMS
    for k in unknown:
        notes.append(f"heuristic scorer has no rule for dimension {k!r}; scored 0 — use LLM mode or add a rule.")

    total = sum(breakdown.values())
    return ScoreResult(total=total, breakdown=breakdown, advance=total >= rubric.threshold, notes=notes)
