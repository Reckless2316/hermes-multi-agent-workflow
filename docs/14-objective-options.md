# 14 — Objective options (income → growth → speculation)

`strategy/objective_options_v1.yaml` extends the deterministic options desk from one purpose
(tasty-style income) to a continuous curve of purposes. The same mechanism builds trades for
collecting premium, for directional growth, and for small convex bets, and picks the purpose
from the measured market situation when you do not pick it yourself.

Everything stays defined-risk and paper-only, and LLMs still only analyze: the purpose, structure,
strikes, prices, probabilities and size are all computed by code from Tradier data.

## The dial

`aggression ∈ [0, 1]`. Three anchor profiles sit on it:

| | income (0.0) | growth (0.5) | speculation (1.0) |
|---|---|---|---|
| Structures (bullish) | short put vertical | long call vertical, long call | long call, long call vertical |
| Structures (bearish) | short call vertical | long put vertical, long put | long put, long put vertical |
| Structures (neutral) | iron condor | none | none |
| DTE window (target) | 25–50 (45) | 45–120 (75) | 21–75 (45) |
| Delta band | short 0.20–0.35 | long 0.50–0.75 (stock replacement) | long 0.15–0.40 (OTM) |
| POP floor (at market IV) | 0.40 | 0.35 | 0.15 |
| Debit-vertical payoff floor | n/a | max profit ≥ 1.0 × max loss | ≥ 2.0 × max loss |
| Breakeven reach | n/a | ≤ 0.75 expected moves | ≤ 1.5 expected moves |
| Profit target | 50% of max profit | +50% on debit | +100% on debit |
| Stop | defined max loss | −50% of debit | premium is the stop |
| Manage / exit at DTE | 21 | 21 | 7 |
| Risk per trade (max loss / equity) | 1.00% | 0.75% | 0.25% |
| Ranking weight leader | capital efficiency 0.60 | POP 0.30 | payoff 0.50 |

A dial between anchors (say 0.25) **linearly interpolates every number** and searches **both
anchors' structure menus**, ranking them under the blended utility. So 0.25 compares income
credit spreads with conservative, high-POP debit spreads, and still leans toward income.
`--aggression 0.8` is a legitimate request: mostly speculative, a little more conservative on
delta, POP and risk than pure speculation.

Risk per trade falls monotonically along the curve. Convexity is paid for with size.

## The situation (auto mode)

`trading/regime.py` measures, per symbol, from provider data only:

- **20-day realized vol** (close-to-close, annualized ×√252) from Tradier daily history.
- **ATM IV**: mean call/put `mid_iv` at the strike nearest spot, read from the expiration nearest
  `iv_reference_dte` (30).
- **IV/RV ratio** → `rich` (≥ 1.15), `cheap` (≤ 0.90), else `fair`.
- **Trend**: last close vs SMA20 vs SMA50, plus a momentum z-score (20-day log return divided by
  the realized-vol stdev over 20 days). `|z| ≥ 0.5` with aligned averages is a trend;
  `|z| ≥ 1.25` is a strong trend.

`auto.map` in the YAML turns `(vol regime, trend)` into a dial setting:

| | neutral | trend | strong trend |
|---|---|---|---|
| **rich** premium | 0.0 income (condor) | 0.0 income (directional credit) | 0.25 blend |
| **fair** | 0.0 income | 0.5 growth | 0.5 growth |
| **cheap** premium | **no trade** | 0.5 growth | 1.0 speculation |

Cheap premium with no direction is a `null` cell: no objective has a structural reason to exist,
so the scanner returns `NO_SETUP: no structural edge` instead of forcing a trade. Missing history
or IV gives `situation unknown`, never a guess. `--max-aggression` (or `auto.max_aggression`)
caps the auto dial at your risk tolerance.

The trade's **bias** follows the measured trend unless you pass `--bias`. Your thesis always
wins, and the sidecar records which source decided. With an unknown trend only non-directional
structures (iron condors) are eligible.

This is not IV Rank. IVR needs a year of IV history Tradier does not supply; it stays
`unavailable_from_tradier`.

## Gates, model, and ranking

Each candidate must pass the V1 mechanical gates (DTE, delta band, two-sided liquidity, width,
defined risk; credit/width for credits) and the objective gates:

- `POP_OK`: P(expiry P&L > 0) under a zero-drift lognormal at the legs' **market IV** ≥ floor.
- `PAYOFF_MULTIPLE` (debit verticals): max profit / max loss ≥ floor.
- `BREAKEVEN_REACH` (debits): breakeven within `max_breakeven_em` one-sigma expected moves.

Survivors are scored (weights from the profile, normalized):

- **capital efficiency**: target-profit dollars / max loss.
- **POP** at market IV.
- **payoff**: P&L at a favorable 2-expected-move settle / max loss.
- **model edge**: E[expiry P&L] under a lognormal at **realized** vol / max loss. This is the
  situation term. When realized vol exceeds implied, bought premium is positive-expectation under
  this model and sold premium negative, and the reverse when implied is rich. It is labelled a
  model estimate, not a forecast, and is zero (and noted) when realized vol is unavailable.

All analytics are closed-form (`trading/pricing.py`), so results are exact and reproducible.
Rates and dividends are ignored; this is a ranking/gating model, not a pricer.

Income ranking remains capital-efficiency-first (weight 0.60), consistent with the V1 rule.

## Premium convention and the rest of the pipeline

Premium is signed per share everywhere downstream: **positive = credit, negative = debit**.
Because of that, existing mechanisms work unchanged in meaning:

- Revalidation's no-chase rule is "fresh natural premium must not be lower than approved" — less
  credit *or* more debit is rejected. Objective candidates re-run their own builder and objective
  gates on the exact OCC legs with the fresh spot (`revalidation_context`).
- `OptionsPaperLedger` P&L is `(entry − exit) × 100 × qty` for both. A debit position closes with a
  negative `exit_debit` (you receive the sale). `max_profit` is `NULL` for long options; V1 ledgers
  are migrated in place (atomically) on first open.
- `manage_paper_options.py` routes each row by sign: credits use the V1 rules; debits use
  `manage_debit_position` (target on debit, optional stop, exit at management DTE before theta
  accelerates, force close near expiry). The rules travel with the candidate in
  `analytics.management`, so a position is managed under the rules it was approved with.

## Running it

```bash
# Let the market choose, but never past growth:
python scripts/scan_objective_options.py --objective auto --max-aggression 0.5

# A specific purpose:
python scripts/scan_objective_options.py --objective income
python scripts/scan_objective_options.py --objective speculation --bias bearish --symbols QQQ

# Any point on the curve, with smaller risk than the profile allows:
python scripts/scan_objective_options.py --aggression 0.3 --risk-per-trade-pct 0.005
```

Output: an intake markdown (contract with `engine/intake_parser.py`) and a JSON sidecar holding
every candidate with its profile, situation, decision, model analytics and gates, plus per-symbol
`objective_gate_rejections` counts explaining empty sweeps. Post-approval is unchanged:
`materialize_options_setup.py` → `paper_execute_options.py` → `manage_paper_options.py`.

The scheduled Hermes options scout reads `OPTIONS_OBJECTIVE` and `OPTIONS_MAX_AGGRESSION` from the
profile environment (defaults `auto` and `1.0`). `scan_tradier_options.py` (V1, credit-only) is
still available as the baseline.

## Tuning discipline

Every number in the YAML is a stated hypothesis. Collect at least 50 clean paper occurrences per
objective before changing one, change one thing at a time, and prefer changing a gate over a
weight. The ledger records `strategy_version` and the full candidate (objective, dial, situation)
per position, so cohorts by objective/regime come straight from `trades.json`.
