# OPTIONS path — hard rails
- Defined-risk structures only. tasty_defined_risk_v1: short put vertical, short call vertical,
  iron condor. objective_options_v1 adds long call/put verticals and long calls/puts
  (debit paid is the max loss). Nothing else: no naked short options, ratios, or undefined risk.
- Python/provider data owns prices, OCC legs, Greeks, POP, breakevens, max loss, BPR, size, gates,
  and the objective/dial/bias decision recorded on the candidate.
- Entry risk uses natural prices: credit = `short bid - hedge ask`; debit = `long ask - short bid`.
  Midpoint is reference only. Premium is signed in JSON: positive credit, negative debit.
- Tradier current IV is not IV Rank; never fabricate IVR. IV/RV ratio is not IVR either.
- After approval re-fetch exact OCC legs and re-run gates (including objective gates). If the
  credit shrank or the debit grew, WAIT/repropose; never chase.
- Use `OptionsPaperLedger`, not model-trader's single-price PaperTrader, for options.
- No live orders, averaging down, widening max risk, raising risk per trade above the profile,
  secret leakage, or auto-approval.

- Context review must check earnings, ex-dividend/assignment risk for short calls, major corporate actions, and scheduled macro events before proposing.
- Speculation-objective candidates must be proposed as small-risk convex bets; never present a
  low-POP debit as income or as likely to win.
