# Hermes Multi-Agent Trading Workflow

A reusable Hermes multi-agent triage framework, currently adapted into a
**rule-driven trading desk**.

The generic workflow still follows Tonbi Studio's original shape:

> detect → dedup → score → parallel research → route → one human approval gate → fulfill → deliver

This fork adds a deterministic options mechanism around an active Tradier
brokerage data connection while preserving the swing-trading concepts borrowed
from [tonbistudio/model-trader](https://github.com/tonbistudio/model-trader).

## Trading architecture

```text
                     MARKET / ACCOUNT DATA
                             Tradier
                                │
              ┌─────────────────┴────────────────┐
              ▼                                  ▼
      deterministic options              swing detectors
        scanner + sizing                 / model-trader ideas
              │                                  │
              └──────────────┬───────────────────┘
                             ▼
                        Hermes intake
                             ▼
                    dedup + triage score
                             ▼
       mechanical_verify | market_context | portfolio_risk
                             ▼
                      TAKE / WAIT / SKIP
                             ▼
                       HUMAN APPROVAL
                             ▼
                 exact-leg fresh revalidation
                             ▼
                  paper ledger / monitoring
```

**Core invariant:** LLMs analyze; deterministic code authorizes. Hermes can
research earnings/macro context, explain, or veto a mechanically valid setup. It
cannot invent or hand-edit option prices, strikes, Greeks, max loss, BPR, size,
or hard-gate results.

## Options V1

`strategy/tasty_defined_risk_v1.yaml` is a paper-only defined-risk
premium-selling baseline built around the user's stated tasty-style priorities:
capital efficiency, small risk, many occurrences, wider defined-risk structures
when they earn their buying power, and early winner management.

V1 scans only:

- short put verticals;
- short call verticals;
- iron condors.

Candidate economics use **natural executable pricing**, not optimistic midpoint
fills. Tradier supplies current option quotes plus ORATS Greeks/IV; historical IV
Rank is not supplied by Tradier, so the system reports it as unavailable instead
of manufacturing it.

## Quickstart

```bash
pip install -r requirements.txt
python -m cli.triage validate
python -m unittest discover -s tests
python -m compileall -q engine trading scripts tests
python -m cli.triage scaffold
```

For the options scanner, configure local/profile environment variables from
`.env.example`, especially `TRADIER_API_TOKEN` and `TRADIER_ACCOUNT_ID`. Never
commit their values.

One manual scan:

```bash
python scripts/scan_tradier_options.py \
  --config strategy/tasty_defined_risk_v1.yaml \
  --output work/manual/options-intake.md \
  --json-output work/manual/options-scan.json
```

See `docs/13-tradier-paper-runbook.md` for the full paper workflow.

## Repository layout

```text
triage.yaml                     Hermes routing/domain workflow
AGENTS.md                       durable instructions/invariants for coding agents
engine/                         generic multi-agent triage engine
strategy/                       auditable deterministic trading parameters
trading/                        Tradier/data/options/risk/paper mechanisms
scripts/                        scanner, durable candidate handoff, stream, paper execute/manage entrypoints
paths/                          rails, proposal formats, deliverable contracts
skills/templates/               Hermes scout/orchestrator operating instructions
tests/                          generic + trading mechanism tests
docs/                           architecture, runbooks, strategy provenance
examples/                       historical template examples
```

## Documentation

- `docs/01-architecture.md` — generic fat-engine/thin-skill architecture.
- `docs/04-adapting-to-your-domain.md` — upstream adaptation method.
- `docs/06-security.md` — trust surface and secrets.
- `docs/07-runbook.md` — generic Hermes setup.
- `docs/08-trading-domain.md` — current desk mapping.
- `docs/09-tasty-defined-risk-v1.md` — strategy contract and mechanical math.
- `docs/10-tradier-data-and-state.md` — provider/state architecture.
- `docs/11-v1-roadmap.md` — current project state and graduation path.
- `docs/12-v1-architecture-decisions.md` — durable ADR-style decisions.
- `docs/13-tradier-paper-runbook.md` — local integration and paper operation.

## model-trader relationship

Do not merge the two projects into one blob. `model-trader` remains a useful
sibling/reference for swing detectors, pass/fail gate design, and its original
single-price paper-trading concepts. Multileg options deliberately use this
repo's options-specific risk and ledger mechanisms because spread risk is not
entry-to-stop distance.

If needed locally:

```bash
pip install -e ../model-trader
export MODEL_TRADER_ROOT=../model-trader
```

## Safety / execution boundary

V1 contains **no live order-submission adapter**. The Tradier client is read-only
apart from creating a market-data streaming session. Production credentials are
used for real-time market/account reads; fills are simulated in the paper ledger
after the existing human gate.

A future live executor is a separate phase with broker preview, limit-order
state, reconciliation, idempotency, stale-data controls, and portfolio/daily
kill switches. It is not enabled by toggling `PAPER_TRADING`.

## License

MIT — see `LICENSE`.
