# Hermes Multi-Agent Workflow

A reusable skeleton for an **autonomous, multi-agent triage pipeline** built on
[Hermes](https://github.com/NousResearch/hermes-agent): a fleet of agents that
**detects** items from sources, **dedups** them, **scores** them against a rubric,
**researches** them in parallel, **routes** each to a fulfillment path, pauses at
**one human approval gate**, then **fulfills and delivers** — all coordinated on a
single Hermes Kanban board.

Root `triage.yaml` is wired as an **automated trading desk**: an options-signal
scout and a swing-trade scout feed board `trading`; setups that clear the rubric
are researched, routed to paper options / paper swing / watch / shelve, and
paper-executed only after one Telegram approve. Ideas, detectors, paper-trader
filters, and the TAKE/WAIT/SKIP vocabulary come from the sibling
[model-trader](https://github.com/Reckless2316/model-trader) repo
(`docs/08-trading-domain.md`).

The previous AI-agent pain-point example is snapshotted under
`examples/ai-agent-pain-points/`.

> **This is a template, not a turnkey broker.** It runs its unit tests and
> validates its config out of the box, but going live requires your Hermes
> install, profiles, auth, and scouts (`docs/07-runbook.md`). Scope rails forbid
> live money; fulfillment writes a paper journal.

## The idea

```
options scout ─┐
               ├→ intake → dedup → score → research (parallel) → route
swing scout  ─┘                                              │
                              ┌──────────────┬───────────────┼──────────┐
                           options        swing           watch      shelve
                           (prep)        (prep)          (prep)      (auto)
                              └──────────────┴───────────────┘
                                       ── HUMAN GATE ──
                              ┌──────────────┴───────────────┐
                         paper fill                     arm monitor
                              └──────────────┬───────────────┘
                                          deliver
```

The shape is fixed; **what flows through it is yours.** Everything domain-specific
lives in one file, `triage.yaml`.

## Quickstart

```bash
pip install -r requirements.txt          # just PyYAML
python -m cli.triage validate            # check the trading-desk config
python -m unittest discover -s tests
python -m cli.triage scaffold            # print the Hermes setup plan
# then:  hermes kanban boards create trading
```

If the sibling **model-trader** repo is checked out next to this one:

```bash
pip install -e ../model-trader
export MODEL_TRADER_ROOT=../model-trader
```

## Adapt it to your domain

The whole adaptation is editing `triage.yaml` + the markdown templates it points
at. Hand your coding agent **`AGENTS.md`** and ask it to walk you through
`docs/04-adapting-to-your-domain.md`. In brief:

1. Edit `triage.yaml`: sources, rubric, research lanes, route map, paths, roles.
2. Edit `paths/` templates (scope rails, deliverable specs, proposal formats).
3. Edit `skills/templates/` (scout queries + orchestrator notes).
4. `python -m cli.triage validate`, keep `tests/` green.
5. Follow `docs/07-runbook.md` to set up profiles and go live.

## Repository layout

```
triage.yaml              THE config — your whole pipeline (start here)
AGENTS.md                Guide for the AI agent adapting this template
engine/                  Generic engine (rarely edited)
proposal_actions.py      Human-gate handler (approve/shelve/modify)
paths/                   Per-path templates (rails, specs, proposals, philosophy)
skills/templates/        Scout + orchestrator SKILL.md
  triage-scout-options/  Filled-in options scout
  triage-scout-swing/    Filled-in swing scout
cli/triage.py            validate / scaffold / init / install
tests/                   Generic engine tests + trading-domain cases
docs/                    Deep-dive docs (08 = this desk + model-trader map)
examples/                Historical pain-point snapshot + trading README
```

## Documentation

- `docs/01-architecture.md` — fat engine / thin skill; how the pieces fit.
- `docs/02-the-board.md` — Kanban as the bus; dispatcher; fan-in.
- `docs/03-config-reference.md` — every `triage.yaml` key.
- `docs/04-adapting-to-your-domain.md` — the step-by-step adaptation guide.
- `docs/05-pipeline-stages.md` — each stage, and the gotchas to preserve.
- `docs/06-security.md` — trust surface, scope rails, safe publishing.
- `docs/07-runbook.md` — profiles, board, crons, go-live.
- `docs/08-trading-domain.md` — this desk, mapped onto model-trader.
- `examples/ai-agent-pain-points/REFERENCE.md` — write-up of the origin system.

## Security

This template can shell out and, on a build-style path, run LLM-authored code,
behind one human gate. The trading desk's rails additionally **forbid live
orders**. Read **`SECURITY.md`** and `docs/06-security.md` before deploying —
and run the pre-publish secret-scan checklist before open-sourcing an adapted
copy.

## Contributing

See **`CONTRIBUTING.md`**. The golden rule: keep `engine/` domain-agnostic; new
domains go in `triage.yaml`, not the code.

## License

MIT — see `LICENSE`.
