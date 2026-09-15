# 13 — Tradier paper runbook
Set local `TRADIER_API_TOKEN`, `TRADIER_ACCOUNT_ID`, and `PAPER_TRADING=true`; never commit values.
Validate with `python -m unittest discover -s tests` and `python -m compileall -q trading scripts tests`.
Run scan with `python scripts/scan_tradier_options.py --output work/manual/options.md --json-output work/manual/options.json`.
Run one shared stream with `python scripts/stream_tradier_market.py`.
Write sanitized portfolio state with `python scripts/snapshot_tradier_portfolio.py`.
After `approve <slug>`, select exactly one candidate JSON and run `paper_execute_options.py`; exit 2/
`WAIT_REPROPOSE` means do not override the deteriorated/invalid structure. Manage open positions with
`manage_paper_options.py` (`--dry-run` available). Preserve gate-failure, natural-vs-mid, holding-time,
management-reason, strategy/width/delta/DTE cohort, reconnect, and stale-data evidence before live discussion.


## Market-hours freshness
Scans, post-approval paper fills, and automatic paper closes require Tradier market clock state `open`. Closed/unknown states do not consume stale chains as executable evidence.


## Durable Hermes candidate handoff
After a new options item is created, run `scripts/attach_options_context.py` to copy `candidate_id` and `sidecar_json` into item frontmatter. Post-approval, the first persistent fulfillment stage runs `scripts/materialize_options_setup.py` to create `setup.json`; never depend on pre-gate scratch files.
