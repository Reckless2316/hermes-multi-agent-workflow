#!/usr/bin/env python3
"""Attach deterministic options intake context to an existing item-vault entry."""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from engine.intake_parser import parse_intake_report  # noqa: E402
from engine.item_vault import ItemVault  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--slug", required=True)
    parser.add_argument("--intake-report", required=True)
    parser.add_argument("--candidate-id", required=True)
    parser.add_argument("--vault-dir", default=os.environ.get("TRIAGE_VAULT_DIR", "./work/vault/items"))
    args = parser.parse_args()

    report_path = Path(args.intake_report).resolve()
    report = parse_intake_report(report_path.read_text(encoding="utf-8"))
    matches = [candidate for candidate in report.candidates if candidate.fields.get("candidate_id") == args.candidate_id]
    if len(matches) != 1:
        raise SystemExit(f"OPTIONS_CONTEXT_FAILED: expected exactly one candidate {args.candidate_id!r}; found {len(matches)}")
    sidecar = report.metadata.get("sidecar_json")
    if not sidecar:
        raise SystemExit("OPTIONS_CONTEXT_FAILED: intake report has no sidecar_json")

    candidate = matches[0]
    vault = ItemVault(Path(args.vault_dir))
    item = vault.load(args.slug)
    item.frontmatter.update(candidate.fields)
    item.frontmatter.update({"candidate_id": args.candidate_id, "sidecar_json": sidecar, "intake_report": str(report_path), "intake_source": report.metadata.get("source", "options")})
    vault.save(item)
    print(item.path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
