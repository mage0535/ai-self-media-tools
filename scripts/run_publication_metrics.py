#!/usr/bin/env python3
"""Consume due publication windows; no credentials or fake metrics are generated here."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from content_platform.publication_ledger import PublicationLedger
from content_platform.publication_metrics import run_due_collections


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--ledger", default="data/publication_ledger.db")
    args = parser.parse_args()
    ledger = PublicationLedger(Path(args.ledger))
    result = run_due_collections(ledger, lambda _identity, _window: {})
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
