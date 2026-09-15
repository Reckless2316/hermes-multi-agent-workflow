# OPTIONS path — scope rails (HARD limits)

> Inlined into every `options`-path worker's task body. This is the safety
> boundary. **Do not widen these rails to fit a trade.** Shelve or re-route
> instead. Ideas come from model-trader: gates are pass/fail; the paper trader
> is the only executor; live routing is out of scope.

## Acceptable work

- Structure a **defined-risk** options trade: debit/credit vertical, iron
  condor, calendar, or defined-risk butterfly. Max loss must be known in dollars
  before the human sees the proposal.
- Paper-journal the fill using `desk.paper.PaperTrader` (or
  `python -m desk.manage` after fills). Persist `trades.json` in the
  persistent workspace. Use the scanner's credit/max_loss/qty — do not
  re-pick strikes.
- Size is already authorized by the portfolio/BP gates. Do not increase qty.
- Attach the option legs (expiry, strikes, right, qty, debit/credit) in
  `extras`. Underlying confirmation may use model-trader detectors (HTF bias,
  FVG, CISD) when the thesis is directional.
- Size at a **fixed % of paper balance** (default 1%). Cap so max loss on the
  structure never exceeds that budget.

## Never acceptable

- **Live orders / Tradier multi-leg execution.** V1 paper-fills only. A
  later `LiveTrader` is a small step *after* the paper journal is clean.
  Do not call Tradier's order API from a fulfill task.
- Naked short calls/puts, ratio spreads that can gap into undefined risk,
  or 0DTE lottery tickets with no hedge.
- Averaging into a loser, moving a stop further away, or omitting max loss.
- Re-entering a duplicate setup (same underlying + similar strikes/expiry
  recently paper-filled) or an invalidated level that just stopped out.
- Fetching or storing customer/account secrets. Use only keys already in the
  profile `.env` (`TRADIER_ACCESS_TOKEN`). Never print tokens into the journal
  or Telegram.
- Changing `triage.yaml` routing to auto-approve.

## If a proposal doesn't fit

Shelve it with a specific reason, or re-route to `watch` (WAIT) / `swing`
(underlying-only). **Do not expand these rails.**
