#!/usr/bin/env python3
"""
Builds features for one or more specific customer_ids as of a given date, using the
scoring path of the same shared build_features(as_of, ...) entry point used by
build_training_features.py. Read-only: it does not touch the feature store.

Run from the repo root:

    python -m scripts.score_customer --customer-id 2 --as-of 2026-08-01
"""

import argparse
import sys

from features import build


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        "--customer-id",
        type=int,
        action="append",
        required=True,
        help="Customer ID to score. May be passed multiple times.",
    )
    parser.add_argument(
        "--as-of",
        default="2026-08-01",
        help="As-of date for feature computation (default: 2026-08-01).",
    )
    args = parser.parse_args()

    try:
        features = build.build_features(args.as_of, customer_ids=args.customer_id)
    except (KeyError, ValueError) as exc:
        print(f"error: {exc.args[0]}", file=sys.stderr)
        sys.exit(2)

    print(features.to_string(index=False))


if __name__ == "__main__":
    main()
