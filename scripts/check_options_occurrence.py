#!/usr/bin/env python3
"""Check item-vault frontmatter for an in-flight duplicate options occurrence."""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from engine.item_vault import ItemVault  # noqa: E402
from trading.occurrence import find_active_occurrence  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--candidate-id", required=True)
    parser.add_argument("--vault-dir", default=os.environ.get("TRIAGE_VAULT_DIR", "./work/vault/items"))
    args = parser.parse_args()
    vault = ItemVault(Path(args.vault_dir))
    items = []
    for path in sorted(vault.root.glob("*.md")):
        try:
            item = vault.load(path.stem)
        except (ValueError, FileNotFoundError):
            continue
        items.append((path.stem, item.frontmatter))
    duplicate = find_active_occurrence(args.candidate_id, items)
    result = {"candidate_id": args.candidate_id, "active_duplicate": duplicate, "ok_to_create": duplicate is None}
    print(json.dumps(result, sort_keys=True))
    return 2 if duplicate else 0


if __name__ == "__main__":
    raise SystemExit(main())
