# OPTIONS proposal template

> Orchestrator fills this in and sends it at the human gate. Skimmable on a
> phone. Reply verbs from `gate:` in triage.yaml — **no leading slash**.

```
📈 OPTIONS proposal: <title>   (slug: <slug>)

Setup
- Underlying: <symbol>   Direction: <long|short|neutral>
- Structure: <vertical / iron condor / calendar / …>
- Expiry / strikes: <…>
- Debit/credit: <amt>    Max loss: <amt>    Planned R: <n>
- IV rank / flow: <…>
- Catalyst: <earnings date | none | …>

Why take it
- Score: <total>/100 (<short breakdown>)
- Gates / checks passed: <list>
- Underlying confirmation: <HTF bias / FVG / none for non-directional>
- Duplicate? <no | yes — shelve>   Invalidated level? <no | yes>

"Am I actually taking this?" (from paths/philosophy.md)
- Dumb obvious? <yes/no>
- Undefined risk? <no required>
- News chop? <no>
- If any answer is off → this should not be a proposal.

Paper plan
- Size: <1% of paper equity, capped by max loss>
- Journal: work/options/<slug>/trades.json
- LIVE MONEY: no

Reply:  approve <slug>   |   shelve <slug>: <reason>   |   modify <slug>: <change>
```
