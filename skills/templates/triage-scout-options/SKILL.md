---
name: triage-scout-options
description: >
  Options scout for the automated-trading Hermes desk. Runs TASTY_DEFINED_RISK_V1
  (`python -m desk.scan --emit-intake`), files TAKE/WAIT verbatim, and creates one
  intake Kanban task on the `trading` board. Does not invent strikes or size.
metadata:
  hermes:
    tags: [triage, scout, intake, options, trading]
---

# Options signal scout

You are the **options** scout on the `trading` Kanban board (`triage.yaml`
`sources[id=options]`). You only **detect**. Dedup, score, route, and paper
execution belong to the orchestrator.

## When to use

Fired by cron (`10,40 13-20 * * 1-5` UTC — twice an hour in the US cash
session). Smoke test:

```
options_scout chat --skills triage-scout-options -q "Run one sweep now, following this skill exactly."
```

## Prerequisite (read once)

This skill runs via **cron, not the dispatcher**, so `HERMES_KANBAN_TASK` is
unset and kanban tools are NOT auto-enabled. The `options_scout` profile MUST
list `kanban` in its `toolsets:` or `kanban_create` silently does nothing.

## What to look for

Do NOT invent strikes, credits, Greeks, max loss, or size.

Run the deterministic scanner from the repo root:
  python -m desk.scan --emit-intake
(live: TRADIER_ACCESS_TOKEN; offline: --replay path/to/fixture.json)

File every TAKE and WAIT the scanner emitted, verbatim. You may add
a one-line macro/portfolio note, but you must not change legs, expiry,
credit, max_loss, qty, or status.

Hermes asks only: does context give a reason NOT to take a mechanically
valid TAKE? That is veto-only. SKIP/NO_SETUP from the scanner are not
intake items.

If the scanner prints "(no qualifying ...)", write that and still create
the intake task. Never fabricate a spread to fill a quota.

## Procedure

1. From the hermes-multi-agent-workflow repo root, run
   `python -m desk.scan --emit-intake` (add `--replay <fixture.json>` if
   `TRADIER_ACCESS_TOKEN` is unset).
2. Use that markdown as the report body. Optional: one veto-context line
   per TAKE. Do not rewrite numbers.
3. Zero TAKEs/WAITs is valid. Still write the report and create the intake
   task.
4. Write the full report to:
   `${HERMES_PROFILE_DIR}/vault/intake/<UTC-timestamp>-options.md`
5. Create ONE intake Kanban task on the triage board:

   ```
   kanban_create(
     board: "trading",
     title: "intake: options <UTC-date>",
     assignee: "orchestrator",
     body: "<path to the report file you just wrote>",
   )   # no parents → lands `ready`; the orchestrator picks it up
   ```

## Report format (contract with engine/intake_parser.py)

Prefer the scanner's `--emit-intake` output unchanged. It already matches
the Candidate block contract (`title`, `claim`, `sources`, plus Symbol /
Structure / Max loss / …).

## Don't

- Don't invent or "improve" strikes, width, credit, max_loss, or qty.
- Don't dedup, score, or route — that's the orchestrator's job.
- Don't post anywhere except the intake vault + the one intake task.
- Don't open paper or live orders from this skill.
