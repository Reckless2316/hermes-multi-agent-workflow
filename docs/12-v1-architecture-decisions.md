# 12 — V1 architecture decisions
1. LLMs analyze/contextualize; deterministic code authorizes market/risk facts.
2. Tradier is V1 primary provider, not the permanent internal schema.
3. Current IV is not IV Rank; missing IVR stays missing.
4. Use natural executable pricing; midpoint is reference only.
5. Multileg options use an options-specific ledger, not model-trader's single-price PaperTrader.
6. Human approval is a credit limit, not permission to chase a changed market.
7. Exact-leg revalidation ignores discovery rank/top-N position.
8. SQLite WAL before Redis for single-host V1.
9. Read-only Tradier client is a security boundary; future live executor is separate.
10. Strategy YAML parameters are hypotheses to validate, not prompt-level mutable opinions.

11. Options do not use lifetime semantic dedup as final authority. Stable `candidate_id` blocks in-flight duplicate workflow items; exact broker/paper leg sets block simultaneous duplicate positions. Old history may become a new occurrence after the prior position is no longer open.

12. Trade purpose is one continuous dial (income 0 → growth 0.5 → speculation 1), not three
    separate strategies. Anchors are full profiles; points between interpolate numbers and union
    structure menus. See `docs/14-objective-options.md`.
13. Auto mode maps measured IV/RV and trend to the dial through an auditable table with explicit
    no-trade cells. Unknown inputs refuse; they are never inferred.
14. Premium is signed (credit positive, debit negative) end to end, so no-chase, ledger P&L and
    revalidation have one meaning for every structure.
15. Debit structures are allowed only where max loss is the premium paid (long verticals, long
    calls/puts). Speculation pays for convexity with smaller risk per trade, not with undefined risk.
16. Model edge is computed under realized vol and labelled as a model estimate; it ranks, it never
    authorizes on its own.

