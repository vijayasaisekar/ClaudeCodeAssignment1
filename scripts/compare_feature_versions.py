#!/usr/bin/env python3
"""
Version comparison for every feature feature_spec.md designates as versioned. Every version is
loaded through the feature store (get_version), not recomputed. The output is
outputs/artifacts/VERSION_COMPARISON.md: per feature, how many customers changed between
consecutive versions, the distribution shift, rank-order agreement, and how many customers
move in or out of the lowest-value quintile (the group a churn ranking would target first).

Run from the repo root, after build_training_features:

    python -m scripts.compare_feature_versions
"""

from pathlib import Path

import pandas as pd

from feature_store import store
from features.schema import FEATURE_SCHEMA

OUTPUT_PATH = Path("outputs/artifacts/VERSION_COMPARISON.md")
CHANGE_TOLERANCE = 1e-9
QUINTILE_SHARE = 0.20


def _load_versions(feature_name: str) -> pd.DataFrame:
    """Wide frame: one column per registered version (ascending), indexed by customer_id."""
    registry = store.list_versions(feature_name)
    versions = sorted(registry["version"].tolist())
    columns = {
        version: store.get_version(feature_name, version).set_index("customer_id")[feature_name]
        for version in versions
    }
    return pd.DataFrame(columns)


def _interpret_change(changed_share: float, rank_corr: float) -> str:
    """Rule-based reading of the numbers, so the interpretation is generated, not hand-written."""
    if changed_share < 0.05:
        magnitude = "Only a small share of customers change, so a model consuming this feature would see little difference."
    elif changed_share < 0.25:
        magnitude = "A moderate share of customers change, which a model consuming this feature would likely notice in the tails."
    else:
        magnitude = "Most customers change, so a model consuming this feature would see a clearly different input distribution."
    if rank_corr >= 0.95:
        ordering = "Rank order is almost unchanged (Spearman >= 0.95): the relative ordering of customers is preserved, so the change is mostly in scale."
    elif rank_corr >= 0.80:
        ordering = "Rank order moves somewhat (Spearman 0.80 to 0.95): some customers change position relative to others."
    else:
        ordering = "Rank order changes materially (Spearman < 0.80): the version reorders customers, so it would change who is ranked as at-risk."
    return f"{magnitude} {ordering}"


def _compare_pair(wide: pd.DataFrame, older: int, newer: int) -> dict:
    a, b = wide[older], wide[newer]
    diff = (b - a).abs()
    changed = diff > CHANGE_TOLERANCE
    n = len(wide)
    quintile_size = max(1, int(round(n * QUINTILE_SHARE)))
    bottom_a = set(a.rank(method="first").nsmallest(quintile_size).index)
    bottom_b = set(b.rank(method="first").nsmallest(quintile_size).index)
    rank_corr = float(a.rank().corr(b.rank()))  # Spearman = Pearson on ranks (no scipy needed)
    return {
        "older": older,
        "newer": newer,
        "changed": int(changed.sum()),
        "changed_share": float(changed.mean()),
        "median_abs_change_when_changed": float(diff[changed].median()) if changed.any() else 0.0,
        "max_abs_change": float(diff.max()),
        "rank_corr": rank_corr,
        "bottom_quintile_entering": len(bottom_b - bottom_a),
        "bottom_quintile_leaving": len(bottom_a - bottom_b),
    }


def _describe_distribution(wide: pd.DataFrame) -> list[str]:
    """Markdown table of per-version distribution statistics (no extra dependency needed)."""
    header = "| version | mean | p10 | median | p90 | max | share zero |"
    rows = [header, "|---|---|---|---|---|---|---|"]
    for version in wide.columns:
        col = wide[version]
        rows.append(
            f"| v{version} | {col.mean():.4f} | {col.quantile(0.1):.4f} | {col.median():.4f} | "
            f"{col.quantile(0.9):.4f} | {col.max():.4f} | {(col == 0).mean():.1%} |"
        )
    return rows


def _section(feature_name: str, description: str, wide: pd.DataFrame, pairs: list[dict]) -> list[str]:
    lines = [f"## {feature_name}", "", description, ""]
    lines += ["### Distribution by version", ""] + _describe_distribution(wide) + [""]
    lines += ["### Version-to-version change", ""]
    lines.append(
        "| older -> newer | customers changed | share changed | median abs change (changed only) | max abs change | Spearman rank corr | bottom-quintile entering | bottom-quintile leaving |"
    )
    lines.append("|---|---|---|---|---|---|---|---|")
    for p in pairs:
        lines.append(
            f"| v{p['older']} -> v{p['newer']} | {p['changed']} of {len(wide)} | {p['changed_share']:.1%} | "
            f"{p['median_abs_change_when_changed']:.4f} | {p['max_abs_change']:.4f} | "
            f"{p['rank_corr']:.3f} | {p['bottom_quintile_entering']} | {p['bottom_quintile_leaving']} |"
        )
    lines.append("")
    lines += ["### Interpretation", ""]
    for p in pairs:
        lines.append(f"- **v{p['older']} -> v{p['newer']}:** {_interpret_change(p['changed_share'], p['rank_corr'])}")
    lines.append("")
    return lines


def main() -> None:
    versioned = [spec for spec in FEATURE_SCHEMA if spec.is_versioned]
    out = [
        "# VERSION_COMPARISON.md",
        "",
        "Generated by `scripts/compare_feature_versions.py` from the feature store registry and value snapshots.",
        f"Customers compared: every customer in each feature's registered snapshots. A change is a value difference greater than {CHANGE_TOLERANCE}.",
        "",
    ]
    for spec in versioned:
        wide = _load_versions(spec.name)
        versions = list(wide.columns)
        pairs = [_compare_pair(wide, older, newer) for older, newer in zip(versions[:-1], versions[1:])]
        params_by_version = store.list_versions(spec.name).sort_values("version")
        description_lines = [
            "Parameter by version: "
            + "; ".join(
                f"v{row.version} {row.parameters}" for row in params_by_version.itertuples()
            )
            + ".",
        ]
        out += _section(spec.name, " ".join(description_lines), wide, pairs)

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text("\n".join(out), encoding="utf-8")
    print(f"Wrote {OUTPUT_PATH} for {len(versioned)} versioned feature(s).")


if __name__ == "__main__":
    main()
