# OPTIONS deliverable
Persistent `work/options/<slug>/` contains:
- `setup.json`: exact selected sidecar candidate, including OCC legs and deterministic gates.
- `snapshot.json`: sanitized post-approval live revalidation facts.
- `trades.json`: options paper-ledger export.
- `report.md`: proposal/fill/management recap.
Every number must be provider/deterministic; natural credit and midpoint must remain distinct.

Post-gate stage 1 must materialize the exact candidate using `scripts/materialize_options_setup.py`; stage 2 invokes `scripts/paper_execute_options.py` with fresh market/account revalidation.
