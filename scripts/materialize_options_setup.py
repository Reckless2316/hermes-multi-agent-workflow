#!/usr/bin/env python3
"""Copy one exact deterministic sidecar candidate into persistent setup.json."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from trading.sidecar import SidecarSelectionError, write_candidate  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--sidecar", required=True)
    parser.add_argument("--candidate-id", required=True)
    parser.add_argument("--output", default="setup.json")
    args = parser.parse_args()
    try:
        output = write_candidate(args.sidecar, args.candidate_id, args.output)
    except (OSError, ValueError, SidecarSelectionError) as exc:
        raise SystemExit(f"SETUP_MATERIALIZE_FAILED: {exc}") from exc
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
