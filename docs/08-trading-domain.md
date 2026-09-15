# 08 — Trading domain
The generic triage engine stays unchanged. Options are built by deterministic Tradier-backed
code before Hermes sees them; swings keep model-trader-style pass/fail detector ideas.

```text
Tradier chain/account -> options gates/sizing -+
swing scanner --------------------------------+-> intake -> research -> route -> human gate
                                                   -> exact-leg recheck -> paper ledger
```
Hermes researches events/context/portfolio fit and may veto; it may not invent mechanical facts.
Research lanes are `mechanical_verify`, `market_context`, and classifier `portfolio_risk`.
Routes remain `options_take`, `swing_take`, `wait`, `skip`, `no_edge`.
Options use `OptionsPaperLedger` because model-trader's entry/stop risk model is not multileg spread risk.
V1 is paper-only; the Tradier client contains no trade-order submission method.

For options, `market_context` explicitly reviews earnings, ex-dividend/early-assignment risk, major corporate actions, FOMC/CPI and other scheduled macro catalysts.


Options item frontmatter permanently stores `candidate_id` and `sidecar_json`. The post-gate chain begins with `materialize_setup`, which selects that exact JSON candidate into the persistent workspace before revalidation/execution.
