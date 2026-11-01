"""
For each feature the spec designates as versioned, register its versions, confirm each is
independently retrievable by version number, confirm is_latest identifies the highest version, and
confirm list_versions returns every version with distinct parquet paths that exist on disk.

Store tests use a temporary registry so they never touch feature_store/registry.db. The last test
checks the real registry after the build, when it exists.
"""

import sys
from pathlib import Path

import pandas as pd
import pytest

from feature_store import store
from features.schema import FEATURE_SCHEMA


@pytest.fixture
def tmp_store(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "REGISTRY_DB", str(tmp_path / "registry.db"))
    monkeypatch.setattr(store, "VALUES_DIR", str(tmp_path / "values"))
    return tmp_path


def _values(feature_name: str, value: float) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "customer_id": [1, 2, 3],
            "as_of_date": pd.Timestamp("2026-08-01"),
            feature_name: [value, value + 1, value + 2],
        }
    )


def _register(feature_name: str, value: float, parameters: dict) -> int:
    return store.register_version(
        feature_name=feature_name,
        values_df=_values(feature_name, value),
        description="test feature",
        source_columns="test:source",
        transform_summary="test transform",
        business_rationale="test rationale",
        parameters=parameters,
    )


def test_register_and_retrieve_all_versions_of_a_versioned_feature(tmp_store):
    """Three versions of one feature: each retrievable by number, with different values."""
    assert _register("window_feature", 10.0, {"window_days": 90}) == 1
    assert _register("window_feature", 20.0, {"window_days": 180}) == 2
    assert _register("window_feature", 30.0, {"window_days": 365}) == 3

    values = {v: store.get_version("window_feature", v)["window_feature"].iloc[0] for v in (1, 2, 3)}
    assert values == {1: 10.0, 2: 20.0, 3: 30.0}


def test_is_latest_points_to_highest_version_not_an_earlier_one(tmp_store):
    _register("window_feature", 10.0, {"window_days": 90})
    _register("window_feature", 20.0, {"window_days": 180})
    _register("window_feature", 30.0, {"window_days": 365})

    registry = store.list_versions("window_feature")
    latest_rows = registry[registry["is_latest"] == 1]
    assert latest_rows["version"].tolist() == [3]
    assert store.get_latest("window_feature")["window_feature"].iloc[0] == 30.0


def test_list_versions_returns_distinct_parquet_paths_that_exist(tmp_store):
    _register("window_feature", 10.0, {"window_days": 90})
    _register("window_feature", 20.0, {"window_days": 180})

    listing = store.list_versions("window_feature")
    assert listing["version"].tolist() == [2, 1]  # most recent first
    assert listing["parquet_path"].nunique() == 2
    assert all(Path(p).exists() for p in listing["parquet_path"])


def test_duplicate_parameters_are_refused_not_overwritten(tmp_store):
    _register("window_feature", 10.0, {"window_days": 90})
    with pytest.raises(ValueError):
        _register("window_feature", 99.0, {"window_days": 90})
    listing = store.list_versions("window_feature")
    assert len(listing) == 1
    assert store.get_version("window_feature", 1)["window_feature"].iloc[0] == 10.0


def test_earlier_snapshot_is_not_modified_by_a_new_version(tmp_store):
    _register("window_feature", 10.0, {"window_days": 90})
    first_path = store.list_versions("window_feature").set_index("version").loc[1, "parquet_path"]
    before = Path(first_path).read_bytes()

    _register("window_feature", 20.0, {"window_days": 180})
    assert Path(first_path).read_bytes() == before


def test_each_feature_has_its_own_latest_flag(tmp_store):
    _register("feature_a", 1.0, {"p": 1})
    _register("feature_a", 2.0, {"p": 2})
    _register("feature_b", 5.0, {})

    assert store.get_latest("feature_a")["feature_a"].iloc[0] == 2.0
    assert store.get_latest("feature_b")["feature_b"].iloc[0] == 5.0


def test_missing_version_raises_key_error(tmp_store):
    _register("window_feature", 10.0, {"window_days": 90})
    with pytest.raises(KeyError):
        store.get_version("window_feature", 7)


def test_training_build_refuses_a_different_as_of_for_already_registered_versions(tmp_store):
    """Re-running the build for the same as-of skips existing versions; a different as-of must fail
    instead of silently keeping snapshots from another date."""
    from scripts import build_training_features

    original_argv = sys.argv
    try:
        sys.argv = ["build_training_features", "--as-of", "2026-08-01"]
        build_training_features.main()
        assert store.list_versions("tenure_days").shape[0] == 1

        sys.argv = ["build_training_features", "--as-of", "2026-07-31"]
        with pytest.raises(ValueError, match="not 2026-07-31"):
            build_training_features.main()
    finally:
        sys.argv = original_argv


def test_real_registry_has_every_spec_versioned_feature_fully_registered():
    """After the build: every spec-designated versioned feature has all its versions registered,
    each retrievable, with exactly one is_latest row pointing to the highest version."""
    if not Path(store.REGISTRY_DB).exists():
        pytest.skip("feature_store/registry.db not built yet; run scripts.build_training_features")

    for spec in FEATURE_SCHEMA:
        listing = store.list_versions(spec.name)
        expected_versions = [v.version for v in spec.versions]
        assert sorted(listing["version"].tolist()) == expected_versions, spec.name
        assert int((listing["is_latest"] == 1).sum()) == 1, spec.name
        assert int(listing.loc[listing["is_latest"] == 1, "version"].iloc[0]) == max(expected_versions)
        for version in expected_versions:
            values = store.get_version(spec.name, version)
            assert spec.name in values.columns
            assert len(values) > 0
