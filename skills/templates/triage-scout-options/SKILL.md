---
name: triage-scout-options
description: Deterministic Tradier-backed options scout (objective curve income -> growth -> speculation).
metadata: {hermes: {tags: [triage, scout, options, tradier, trading]}}
---
# Deterministic options scout
Run `scripts/scan_objective_options.py --objective "${OPTIONS_OBJECTIVE:-auto}" --max-aggression "${OPTIONS_MAX_AGGRESSION:-1.0}"`;
do not originate trades with an LLM. The scanner measures the situation (ATM IV vs
20-day realized vol, trend), sets the objective dial (income 0, growth 0.5,
speculation 1, or a blend), builds only defined-risk structures, and gates/scores them.
`scripts/scan_tradier_options.py` (tasty_defined_risk_v1, credit-only) remains available
when the operator asks for the V1 baseline.

The markdown report contains `sidecar_json:` and each candidate has a stable
`Candidate id:`, `Objective:` and the dial's reason. Downstream prep selects that
candidate from the JSON sidecar and copies the complete object to
`work/options/<slug>/setup.json`; never reconstruct OCC symbols, premium, POP, or
economics from prose. Missing IV Rank stays missing. Zero candidates and
`no structural edge` are valid. Create exactly one intake task on board `trading`.
Never call broker order endpoints. Never change the objective, dial, or bias on the
operator's behalf; report what the scanner decided.
