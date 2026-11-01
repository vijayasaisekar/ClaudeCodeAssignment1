"""
Local feature store API: a SQLite metadata/version registry (`feature_store/registry.db`,
table `feature_registry`) plus one parquet value snapshot per registered version
(`feature_store/values/<feature_name>__v<version>.parquet`).

No feature-store library is used. This store is SQLite + parquet only. Versions are append-only:
a new version gets a new registry row and a new parquet file, and nothing is ever overwritten.
`is_latest` is flipped in the same transaction as the insert.

Never hardcode a parquet filename outside this module. All reads resolve the path via the registry.
"""

import json
import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

REGISTRY_DB = "feature_store/registry.db"
VALUES_DIR = "feature_store/values"

_REGISTRY_TABLE = """
CREATE TABLE IF NOT EXISTS feature_registry (
    feature_name       TEXT    NOT NULL,
    version            INTEGER NOT NULL,
    created_at         TEXT    NOT NULL,
    description        TEXT    NOT NULL,
    source_columns     TEXT    NOT NULL,
    transform_summary  TEXT    NOT NULL,
    business_rationale TEXT    NOT NULL,
    parameters         TEXT    NOT NULL,
    parquet_path       TEXT    NOT NULL,
    is_latest          INTEGER NOT NULL CHECK (is_latest IN (0, 1)),
    PRIMARY KEY (feature_name, version)
)
"""


def _connect() -> sqlite3.Connection:
    """Open the registry, creating it (and its folders) on first use. Never drops existing rows."""
    Path(REGISTRY_DB).parent.mkdir(parents=True, exist_ok=True)
    Path(VALUES_DIR).mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(REGISTRY_DB)
    conn.execute(_REGISTRY_TABLE)
    return conn


def _parameters_json(parameters: dict) -> str:
    return json.dumps(parameters, sort_keys=True)


def find_version(feature_name: str, parameters: dict) -> int | None:
    """Return the registered version whose parameters match exactly, or None."""
    with closing(_connect()) as conn:
        row = conn.execute(
            "SELECT version FROM feature_registry WHERE feature_name = ? AND parameters = ?",
            (feature_name, _parameters_json(parameters)),
        ).fetchone()
    return row[0] if row else None


def register_version(
    feature_name: str,
    values_df: pd.DataFrame,
    description: str,
    source_columns: str,
    transform_summary: str,
    business_rationale: str,
    parameters: dict,
) -> int:
    """Write a new parquet snapshot, insert the registry row, flip is_latest, return the new version.

    `values_df` must have columns `customer_id`, `as_of_date` and `feature_name`.
    Raises if a version with identical parameters is already registered, so a rebuild cannot
    silently add a duplicate version.
    """
    missing = {"customer_id", "as_of_date", feature_name} - set(values_df.columns)
    if missing:
        raise ValueError(f"values_df is missing columns: {sorted(missing)}")
    if find_version(feature_name, parameters) is not None:
        raise ValueError(f"{feature_name} already has a version with parameters {parameters}")

    with closing(_connect()) as conn, conn:
        (max_version,) = conn.execute(
            "SELECT COALESCE(MAX(version), 0) FROM feature_registry WHERE feature_name = ?",
            (feature_name,),
        ).fetchone()
        version = max_version + 1
        parquet_path = f"{VALUES_DIR}/{feature_name}__v{version}.parquet"
        if Path(parquet_path).exists():
            raise FileExistsError(f"Refusing to overwrite existing snapshot {parquet_path}")

        values_df.to_parquet(parquet_path, index=False)
        conn.execute(
            "UPDATE feature_registry SET is_latest = 0 WHERE feature_name = ? AND is_latest = 1",
            (feature_name,),
        )
        conn.execute(
            "INSERT INTO feature_registry VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 1)",
            (
                feature_name,
                version,
                datetime.now(timezone.utc).isoformat(timespec="seconds"),
                description,
                source_columns,
                transform_summary,
                business_rationale,
                _parameters_json(parameters),
                parquet_path,
            ),
        )
    return version


def _parquet_path(conn: sqlite3.Connection, where: str, args: tuple) -> str:
    row = conn.execute(f"SELECT parquet_path FROM feature_registry WHERE {where}", args).fetchone()
    if row is None:
        raise KeyError(f"No registered version matches ({where}) with {args}")
    return row[0]


def get_latest(feature_name: str) -> pd.DataFrame:
    """Return the values of the version currently flagged is_latest = 1."""
    with closing(_connect()) as conn:
        path = _parquet_path(conn, "feature_name = ? AND is_latest = 1", (feature_name,))
    return pd.read_parquet(path)


def get_version(feature_name: str, version: int) -> pd.DataFrame:
    """Return the values of one specific (feature_name, version)."""
    with closing(_connect()) as conn:
        path = _parquet_path(conn, "feature_name = ? AND version = ?", (feature_name, version))
    return pd.read_parquet(path)


def list_versions(feature_name: str) -> pd.DataFrame:
    """Every registered version's metadata row for feature_name, most recent first."""
    with closing(_connect()) as conn:
        return pd.read_sql(
            "SELECT * FROM feature_registry WHERE feature_name = ? ORDER BY version DESC",
            conn,
            params=(feature_name,),
        )


def list_all_versions() -> pd.DataFrame:
    """Every registered version of every feature (used by the lineage generator)."""
    with closing(_connect()) as conn:
        return pd.read_sql(
            "SELECT * FROM feature_registry ORDER BY feature_name, version", conn
        )
