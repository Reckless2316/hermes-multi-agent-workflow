# 10 — Tradier data + state
Production Tradier is V1's primary real-time market/account read provider. Normalize it behind internal
dataclasses so OPRA/NBBO, Cboe direct/PITCH, and historical-IV providers can be added later.
Use one market stream and SQLite WAL `work/market_state.db` for latest shared state; REST supplies chain,
account, and batched open-leg snapshots. Redis is deferred until multi-host/high-throughput pub/sub is justified.
Runtime secrets, account IDs, databases, and snapshots stay out of Git and Telegram.


## Market-hours freshness
Scans, post-approval paper fills, and automatic paper closes require Tradier market clock state `open`. Closed/unknown states do not consume stale chains as executable evidence.
