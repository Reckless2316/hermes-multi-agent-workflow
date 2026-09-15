---
name: triage-scout-options
description: Deterministic Tradier-backed options scout.
metadata: {hermes: {tags: [triage, scout, options, tradier, trading]}}
---
# Deterministic options scout
Run `scripts/scan_tradier_options.py`; do not originate trades with an LLM.
The markdown report contains `sidecar_json:` and each candidate has a stable
`Candidate id:`. Downstream prep selects that candidate from the JSON sidecar and
copies the complete object to `work/options/<slug>/setup.json`; never reconstruct
OCC symbols or economics from prose. Missing IV Rank stays missing. Zero candidates
is valid. Create exactly one intake task on board `trading`. Never call broker order endpoints.
