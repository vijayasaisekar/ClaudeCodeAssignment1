#!/usr/bin/env python3
"""
Builds features for the full training population as of a given date, runs the data-quality
checks, and registers every candidate feature (and every spec-defined version) into the feature
store. Nothing is written to the feature store if a check fails.

Run from the repo root:

    python -m scripts.build_training_features --as-of 2026-08-01
"""

import argparse

import pandas as pd

from feature_store import store
from features import build
from features.quality_checks import enforce, run_all_checks
from features.schema import FEATURE_SCHEMA


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        "--as-of",
        default="2026-08-01",
        help="As-of date for feature computation (default: 2026-08-01).",
    )
    args = parser.parse_args()
    as_of = args.as_of

    sources = build.load_sources()
    ids = build.population(sources, as_of, None)
    features = build.build_features(as_of)
    print(f"Built training features: {len(features)} customers as of {as_of}, "
          f"{len(FEATURE_SCHEMA)} features")

    summary = run_all_checks(
        features,
        transactions=sources["transactions"],
        as_of=as_of,
        expected_ids=ids,
    )
    print("Quality-check summary:")
    for result in summary["results"]:
        status = "SKIPPED" if result["skipped"] else ("PASS" if result["passed"] else "FAIL")
        print(f"  [{status}] {result['check']}: {result['detail']}")
    enforce(summary)
    print("All quality checks passed. Registering features.")

    for spec in FEATURE_SCHEMA:
        for version in spec.versions:
            label = f"{spec.name} params={version.params}"
            existing = store.find_version(spec.name, version.params)
            if existing is not None:
                # Registered snapshots are stamped with the as-of date of their first build. Refuse a
                # different as-of rather than silently keeping values from another date.
                registered_as_of = store.get_version(spec.name, existing)["as_of_date"].iloc[0]
                if pd.Timestamp(registered_as_of) != pd.Timestamp(as_of):
                    raise ValueError(
                        f"{label} is registered as v{existing} for as-of {pd.Timestamp(registered_as_of).date()}, "
                        f"not {as_of}. Use a new registry for a different as-of date."
                    )
                print(f"  already registered for this as-of, skipped: {label}")
                continue
            values = build.compute_feature(spec.name, as_of, sources, ids, params=version.params)
            values_df = pd.DataFrame(
                {
                    "customer_id": ids,
                    "as_of_date": pd.Timestamp(as_of),
                    spec.name: values.to_numpy(),
                }
            )
            registered = store.register_version(
                feature_name=spec.name,
                values_df=values_df,
                description=spec.description,
                source_columns=spec.source,
                transform_summary=f"{spec.transform_summary}; parameters={version.params}",
                business_rationale=version.business_rationale,
                parameters=version.params,
            )
            print(f"  registered v{registered}: {label}")


if __name__ == "__main__":
    main()
