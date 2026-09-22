"""Parse a saved text alert to JSON on stdout; no network or execution imports."""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from core.oddsnotifier_parser import AlertFormatError, parse_oddsnotifier


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("file", type=Path)
    parser.add_argument("--channel-id")
    parser.add_argument("--message-id")
    parser.add_argument("--source-timestamp")
    args = parser.parse_args()
    try:
        result = parse_oddsnotifier(args.file.read_text(encoding="utf-8-sig"),
                                   channel_id=args.channel_id, message_id=args.message_id,
                                   source_timestamp=args.source_timestamp)
    except (OSError, UnicodeError, AlertFormatError) as error:
        print(json.dumps({"status": "INVALID_ALERT", "detail": str(error)}))
        return 2
    print(json.dumps({"status": "PARSED" if result else "IGNORED", "observation": result}, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
