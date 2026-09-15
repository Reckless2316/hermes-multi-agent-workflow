"""python -m desk <scan|manage> ..."""
from __future__ import annotations

import sys


def main() -> int:
    if len(sys.argv) < 2 or sys.argv[1] in {"-h", "--help"}:
        print("usage: python -m desk scan|manage [args]")
        return 0
    cmd, rest = sys.argv[1], sys.argv[2:]
    if cmd == "scan":
        from .scan import main as scan_main
        return scan_main(rest)
    if cmd == "manage":
        from .manage import main as manage_main
        return manage_main(rest)
    print(f"unknown command {cmd!r}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
