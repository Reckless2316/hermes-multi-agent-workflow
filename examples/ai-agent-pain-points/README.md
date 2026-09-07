# Example: ai-agent-pain-points (historical reference)

This is the origin system the template was extracted from. Root `triage.yaml` is
now the **automated-trading** desk (`examples/automated-trading/`,
`docs/08-trading-domain.md`). This folder keeps the pain-point snapshot:

- `triage.yaml` — the original config
- `paths/` — original rails / specs / proposals
- `reference-skills/` — the real X scout

For a full architectural write-up of the origin system, see **`REFERENCE.md`**.

## What it does

- **Scouts** (`xresearch` on Grok, `webresearch` on GPT) watch X, Reddit,
  YouTube, and the web for concrete pain points AI-agent users hit.
- **Rubric** scores frequency / intensity / solvable-or-explainable / solution
  gap / strategic fit; threshold 65/100.
- **Research** verifies sources, gathers prior context, and audits existing
  solutions — the audit emits `solution_quality`.
- **Route:** `missing`/`broken` → **build** a fix; `confusing`/`poorly_documented`/
  `outdated` → make an explainer **video**; `good` → **shelve**.
- **Gate:** one Telegram approval per item.
- **Fulfill:** build path → prototype → test → report; video path → slides →
  script → deliver.

## Reference skill (a real, filled-in scout)

`reference-skills/pain-point-scout-x/SKILL.md` is the **actual** X/Grok scout from
the live system, included verbatim (lightly sanitized). Read it alongside the
generic `skills/templates/triage-scout/SKILL.md` to see exactly how a template
gets filled in for a real source — the search query, the report format, and the
`kanban_create` call that maps back to `triage.yaml`.

## Use it as a starting point

Copy `examples/ai-agent-pain-points/triage.yaml`, then follow `docs/04-adapting-to-your-domain.md` to
repoint it. The structure (sources → rubric → research → route → paths → gate)
stays the same; you swap the content.

## The pattern generalizes

The same skeleton fits, for example:

- **GitHub issue triage** — sources: repo issues + discussions; rubric:
  severity/frequency/reproducibility; route: `bug`→fix path, `docs-gap`→docs path,
  `wontfix`→shelve.
- **Sales-lead triage** — sources: inbound forms + mentions; rubric: fit/intent/
  budget; route: `qualified`→outreach path, `nurture`→sequence path, `junk`→shelve.
- **Support-ticket triage** — sources: ticket queue; rubric: severity/SLA/scope;
  route: `known`→auto-reply path, `bug`→escalate path, `unclear`→clarify path.

In every case you edit `triage.yaml` and the `paths/` templates — never the engine.
