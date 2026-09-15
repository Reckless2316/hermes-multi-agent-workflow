# OPTIONS path — hard rails
- Defined-risk short put vertical, short call vertical, or iron condor only in V1.
- Python/provider data owns prices, OCC legs, Greeks, max loss, BPR, size, gates.
- Entry risk uses natural credit (`short bid - hedge ask`); midpoint is reference only.
- Tradier current IV is not IV Rank; never fabricate IVR.
- After approval re-fetch exact OCC legs and re-run gates. If credit worsened, WAIT/repropose; never chase.
- Use `OptionsPaperLedger`, not model-trader's single-price PaperTrader, for spreads.
- No live orders, naked premium, averaging down, widening max risk, secret leakage, or auto-approval.

- Context review must check earnings, ex-dividend/assignment risk for short calls, major corporate actions, and scheduled macro events before proposing.
