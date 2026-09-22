"""Allow `python -m tools.confirmation ...` from repo root."""

from .cli import main

if __name__ == "__main__":
    raise SystemExit(main())
