# 08 — Trading domain (this desk)

Root `triage.yaml` is wired as an **automated trading desk** coordinated on a
Hermes Kanban board named `trading`. The generic triage `engine/` is unchanged.
**Options numbers come from `desk/` (`TASTY_DEFINED_RISK_V1`)**, not from an LLM.

> Watch **Tradier chains** (deterministic tasty scanner) and **swing structure**
> for **setups**. Keep the ones that score ≥ **70** on **clarity / R /
> gate-completeness / context / uniqueness**. After researching **verify_setup**,
> **market_context**, and **risk_audit**, if **disposition** says **options_take /
> swing_take / wait / skip**, do **options / swing / watch / shelve**, which
> produces a **paper journal fill or a WAIT monitor** — but only after **one
> human approve**.

## LLMs analyze; deterministic code authorizes

```
TRADIER LIVE DATA → MARKET STATE → OPTIONS SCANNER → TASTY RULE ENGINE
 → PORTFOLIO / BP → TAKE/WAIT/SKIP → HERMES DESK (veto/context)
 → YOUR APPROVAL → PAPER FILL → 25/50% + 21-DTE MANAGER → JOURNAL
```

Hermes must not invent strikes, Greeks, buying-power, max loss, or size.
The options scout runs `python -m desk.scan --emit-intake` and files that
markdown verbatim.

Strategy parameters (DTE 25–55 target 45, 50% profit / 25% calendars, manage
at 21 DTE, widths $1–$20, rank by expected_realized_profit / BP — not POP)
live in `desk/strategy.yaml`.

```bash
python -m desk.scan --replay tests/fixtures/spy_tasty.json --emit-intake
python -m desk.scan                 # live: TRADIER_ACCESS_TOKEN
python -m desk.manage --journal work/options/desk-trades.json --as-of 2026-10-01
```

Adapters: `desk.data.TradierAdapter` (V1) behind `MarketDataAdapter`. Later
OPRA/NBBO/flow plug in without rewriting the rule engine. Redis is not required
(SQLite / JSON journal).

## What was pulled from model-trader

| model-trader idea | Where it landed here |
|---|---|
| `SetupStatus` TAKE / WAIT / SKIP / NO_SETUP | Scout report `Setup status`; classifier `options_take` / `swing_take` / `wait` / `skip` |
| Pass/fail **gates**, not confluence scores | Swing scout query; `paths/rails/swing.md`; rubric `setup_clarity` |
| Detector order DATA → HTF → LTF FVG → CISD → levels | `sources[id=swing].query` and `triage-scout-swing` |
| Detectors: FVG, swings, failure swings, CISD, SMT, displacement | Swing scout + swing rails; fulfill re-verifies via `model_trader.detectors` |
| `is_duplicate_setup` / `is_invalidated_level` | `risk_audit` lane; swing/options rails |
| PaperTrader journal + 1% risk + leverage cap | Fulfill `paper_execute`; specs write `trades.json` |
| Agent philosophy is veto-only, fail-open | `paths/philosophy.md` — judgment before the gate, **not** a substitute for it |
| "If it's not dumb obvious, I don't take it." | Philosophy + scout queries |
| No live order routing in the framework | Rails: **never** live money |
| `extract_strategy` / `philosophy.md` | Optional later; `paths/philosophy.md` is the stub checklist |
| Hyperliquid adapter needs no API key | Swing scout may fetch public candles; options need a chain/flow source in `.env` |

Do **not** copy `traders/<name>/` projects, journals, or transcripts into this
repo (`traders/` is gitignored in model-trader for a reason). Point fulfillment
at a sibling checkout:

```text
MODEL_TRADER_ROOT=../model-trader   # or an absolute path
```

## Kanban shape

Board slug: **`trading`**. Cards still follow docs/02:

```
intake (scout) → triage (orchestrator)
                 ├ verify_setup     (researcher, parallel)
                 ├ market_context   (researcher, parallel)
                 └ risk_audit       (researcher, CLASSIFIER)
                        └ route
                            ├ prep → PROPOSE → human gate
                            └ fulfill (dir workspace) → deliver report.md
```

Profiles the scaffolder will print:

- Scouts: `options_scout`, `swing_scout` (need `toolsets: [hermes-cli, kanban]`)
- Desk: `orchestrator`, `researcher`, `analyst`, `options_trader`, `swing_trader`

Create the board with:

```bash
hermes kanban boards create trading
python -m cli.triage scaffold    # rest of the plan
```

Then `docs/07-runbook.md`.

## Research lane outputs

`risk_audit` must emit **exactly one** of:

| `risk_audit.disposition` | path | meaning |
|---|---|---|
| `options_take` | `options` | Defined-risk options TAKE; paper fill after approve |
| `swing_take` | `swing` | Swing/perp TAKE; `PaperTrader.open_trade` after approve |
| `wait` | `watch` | Named event missing; arm monitor, do not fill |
| `skip` | `shelve` (auto) | Gate failed; do not bother the human |
| `no_edge` | `shelve` (auto) | Duplicate, blown level, or undefined risk |

## Fully automated — with the gate kept

Scouts run on cron. Research and routing are automatic. **Fulfillment paper-trades
only after `approve <slug>`.** That is deliberate (`docs/06-security.md`): scouts
ingest untrusted web/flow content; the rails are the other half of the safety
boundary. Do not add auto-approve.

Paper ≠ live. model-trader does not ship a `LiveTrader`. Neither does this desk.

## Environment (trading)

See `.env.example`. Minimum to go live on Hermes:

- Telegram on the orchestrator (gate + delivery)
- Web/search or a market-data key on each scout
- `MODEL_TRADER_ROOT` on fulfill profiles so they can `import model_trader`
- `PAPER_TRADING=true` (and no live broker keys on these profiles)

Cursor / Cloud Agent workspaces that check out **both** repos should pip-install
this repo's `requirements.txt` and `pip install -e <model-trader>`.

## What success looks like (from model-trader, adapted)

- Two scouts filing TAKE/WAIT only, empty sweeps allowed
- Rubric auto-shelving junk so Telegram stays quiet
- Approved TAKEs producing `setup.json` + `trades.json` + `report.md` in
  `work/options/<slug>/` or `work/swings/<slug>/`
- A journal with enough samples to compute win rate, avg R, profit factor
  (`model_trader.paper_trader.metrics`) before anyone talks about live money
