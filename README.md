# Churn Feature Pipeline — reproduction steps

Local feature pipeline for the e-commerce churn dataset: three heterogeneous sources, one shared
feature code path, a SQLite + parquet feature store with versioned features, data-quality checks,
generated lineage, and a train/score parity test.

Drafted by Claude and checked by running every command below on this machine. The learner must re-run them
before submitting (see `outputs/artifacts/review_log.md`, open items).

## 1. Environment setup

Use Python 3.10 or 3.11, as the assignment specifies. Verified on Python 3.11.9.

```powershell
cd churn-feature-pipeline
python -m venv .venv
.\.venv\Scripts\Activate.ps1          # Windows PowerShell
# source .venv/bin/activate           # macOS / Linux
python -m pip install --upgrade pip
pip install -r requirements.txt
```

No API key, credential or environment variable is needed. Everything runs locally against `data/`.

## 2. Repo layout

```
data/                         provided raw sources (do not edit)
features/                     ingest, transforms, schema, build (shared entry point), quality_checks
feature_store/                store.py (API), registry.db (SQLite registry), values/ (parquet snapshots)
scripts/                      build_training_features, score_customer, compare_feature_versions,
                              generate_lineage, parity_mutation_check
tests/                        test_transforms, test_parity, test_quality_checks, test_feature_store
skills/churn-feature-pipeline/  skill.md and README.md (the build spec)
outputs/artifacts/            all reports, logs and test output
feature_spec.md               feature specification (draft; see review_log.md)
data_dictionary.md            Stage 0 data dictionary (draft; see review_log.md)
```

## 3. Build the feature store (training path)

Run from the repo root. Use `python -m`, not `python scripts/<name>.py`, so the packages resolve.

```powershell
python -m scripts.build_training_features --as-of 2026-08-01
```

This runs the data-quality checks first. If any check fails, nothing is written and the command exits non-zero.
On success it registers every candidate feature, and every spec-defined version, into `feature_store/registry.db`
with one parquet snapshot per version under `feature_store/values/`. Running it again for the same as-of date
skips versions that are already registered. Running it for a different as-of date fails on purpose.

## 4. Score one customer (scoring path)

```powershell
python -m scripts.score_customer --customer-id 2 --as-of 2026-08-01
python -m scripts.score_customer --customer-id 2 --customer-id 697 --as-of 2026-08-01
```

Read-only. An unknown customer id exits with code 2 and a clear message.

## 5. Version comparison and lineage (after step 3)

```powershell
python -m scripts.compare_feature_versions     # writes outputs/artifacts/VERSION_COMPARISON.md
python -m scripts.generate_lineage             # writes outputs/artifacts/FEATURE_LINEAGE.md
```

## 6. Run the test suite

```powershell
python -m pytest -v
```

Covers transforms (including the label-window leakage test), train/score parity, quality checks on
bad input, and the feature store (versions, `is_latest`, no overwrite, the as-of guard). The last store
test checks the real registry, so run step 3 first; it is skipped if the registry does not exist yet.

## 7. Parity-mutation check

```powershell
python -m scripts.parity_mutation_check       # writes outputs/artifacts/PARITY_CHECK.md
```

Copies the code to a scratch folder, injects a scoring-only divergence there, and confirms the parity
test fails. The real repo is not modified. Exits 0 when the divergence is caught.

## 8. Standalone quality check

```powershell
python -m features.quality_checks --as-of 2026-08-01
```

## Notes

- Feature definitions and version values are in `features/schema.py`. The reasoning is in `feature_spec.md`.
- The label window is `[as_of − 91 days, as_of)`. Features use only history before that window.
- The raw files in `data/` are read-only inputs.
