# AGENTS.md — read this first

You are a coding agent working on the Reckless fork of **Hermes Multi-Agent
Workflow**. Preserve the generic triage framework while extending the trading
desk as explicit, testable mechanisms.

## What this repository is

The Hermes workflow is a reusable pipeline:

> detect → dedup → score → research in parallel → route → one human gate → fulfill → deliver

Root `triage.yaml` is currently an automated trading desk. The **swing** path
continues to borrow detectors/gate ideas from `tonbistudio/model-trader`. The
**options** path now has its own deterministic Tradier-backed mechanism under
`trading/` because multileg options require different data, pricing, risk, and
paper-ledger semantics than a single-price stop/target trader.

## Core template rule

The generic triage engine stays generic.

- `engine/` = generic workflow mechanisms. Edit rarely.
- `triage.yaml` = routing/domain workflow.
- `paths/` = path rails, proposal format, deliverable contracts.
- `skills/templates/` = agent operating instructions.
- `strategy/` = deterministic trading parameters.
- `trading/` = reusable trading mechanisms/data/risk/ledger code.

A new trading mechanism may belong in `trading/`; trading subject matter does
not belong in `engine/`.

## Trading desk invariants

These are architecture constraints, not suggestions:

1. **LLMs analyze; deterministic code authorizes.** Agents may research events,
   explain, rank context, or veto. They may not invent/hand-edit strikes, market
   prices, Greeks, IV Rank, max loss, buying-power math, contract count, or a
   hard-gate result.
2. Options market/account reads use the read-only `TradierClient`. Do not add
   order POST methods to that class. A future live executor must be a separate
   adapter with separate review and tests.
3. Tradier current IV/Greeks are not historical IV Rank. Missing IVR stays
   missing. Never infer it with an LLM.
4. Entry economics use conservative **natural** prices: credit = `short bid - hedge ask`,
   debit = `long ask - short bid`. Midpoint is reference/mark data only. Premium is signed
   in JSON and the ledger: positive credit, negative debit.
5. `model-trader.PaperTrader` must not size multileg options. It uses one
   entry/stop distance; options risk is defined by leg structure. Use
   `OptionsPaperLedger` for options.
6. Post-approval execution must re-fetch the exact OCC legs and re-run hard
   gates. Ranking changes alone do not invalidate an approved structure.
7. Human-approved natural premium is the paper limit. If fresh natural premium is
   worse (less credit or more debit), do not chase; return to WAIT/reproposal. If better, the paper ledger
   still fills at the approved limit for conservative accounting while recording
   the fresh quote snapshot.
8. Run one Tradier market stream service. Share latest state through SQLite WAL
   (`work/market_state.db`). Redis is not required for V1.
9. Strategy parameters live in `strategy/*.yaml`; routing stays in
   `triage.yaml`; secrets and runtime state never enter Git.
10. Paper execution remains behind the existing human gate. Never auto-approve.

## Current options strategy boundary

There are two strategy files. Neither may be widened silently.

`strategy/objective_options_v1.yaml` (the scheduled scout's default) adds the
objective curve income → growth → speculation. It may also build long call/put
verticals and long calls/puts, where the debit paid is the max loss. The
objective, dial, and bias are decided by `trading/objectives.py` from measured
IV/RV and trend or from explicit operator input; agents must report that
decision, never change it. Risk per trade falls along the curve; never raise it.
Auto-mode `null` cells and unknown situations mean no trade, not a guess.
See `docs/14-objective-options.md`.

`strategy/tasty_defined_risk_v1.yaml` currently supports only:

- short put verticals;
- short call verticals;
- iron condors.

It is a paper-only, defined-risk premium-selling baseline. Do not silently add
naked premium, ratio spreads with undefined risk, 0DTE lottery structures, or
live execution.

The V1 ranking objective is capital efficiency first, then actual premium dollars,
then width as a tie-breaker. Do not replace this with headline POP ranking; the
objective planner's income anchor keeps capital efficiency as its dominant weight.

## Human/LLM boundary

Mechanical scanner output is immutable market/risk evidence downstream.
Hermes research lanes may add:

- earnings/material company events;
- FOMC/CPI/macro context;
- broader market/sector regime;
- portfolio concentration/correlation observations;
- contextual veto / WAIT / SKIP reasoning.

They may not recalculate the spread from prose.

## Existing Hermes gotchas — preserve them

- Cron scouts need the `kanban` toolset because dispatcher auto-enablement does
  not apply to them.
- Post-gate stages need persistent `dir` workspaces, not scratch directories.
- Setting task status is not delivery; headless workers must actually send the
  outbound message.
- Telegram gate replies have no leading slash (`approve <slug>`).
- The first task in a post-gate chain must be ready and not blocked by the still
  open triage parent.
- Never commit `.env`, auth files, Kanban databases, `work/`, vaults, ledgers, or
  account/market snapshots containing private runtime data.

## Required validation before changing trading mechanisms

Run:

```bash
python -m cli.triage validate
python -m unittest discover -s tests
python -m compileall -q engine trading scripts tests
```

For changes under `trading/`, add a deterministic unit test before loosening a
rule. Never tune a gate solely to make a small backtest look better.

## Reading order for this fork

1. `docs/08-trading-domain.md`
2. `docs/09-tasty-defined-risk-v1.md`
3. `docs/10-tradier-data-and-state.md`
4. `docs/11-v1-roadmap.md`
5. `docs/12-v1-architecture-decisions.md`
6. `docs/13-tradier-paper-runbook.md`
7. upstream/general `docs/01-07`

When a future decision changes one of these invariants, update the relevant doc,
test, and config in the same change. The repository—not conversational memory—is
the durable source of truth.

### Options occurrence dedup
Do not use the generic lifetime semantic dedup as the final authority for options. Run `scripts/check_options_occurrence.py` for in-flight candidate IDs. The scanner and execution path separately reject exact structures already open in the paper ledger or Tradier account. This allows a closed historical structure to become a legitimate new occurrence later.
