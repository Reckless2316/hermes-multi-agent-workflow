# OPTIONS deliverable
Persistent `work/options/<slug>/` contains:
- `setup.json`: exact selected sidecar candidate, including OCC legs, deterministic gates, and
  (objective candidates) the profile, situation, model analytics, and management rules.
- `snapshot.json`: sanitized post-approval live revalidation facts.
- `trades.json`: options paper-ledger export.
- `report.md`: proposal/fill/management recap, naming the objective the trade was taken for.
Every number must be provider/deterministic; natural premium and midpoint must remain distinct.

Post-gate stage 1 must materialize the exact candidate using `scripts/materialize_options_setup.py`; stage 2 invokes `scripts/paper_execute_options.py` with fresh market/account revalidation (it detects objective candidates by `strategy_version` and re-runs their own gates).
