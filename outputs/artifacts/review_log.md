# review_log.md — self-review before merge

Step 3 of skill.md (self-review of the full change) and the Helper Guide's pre-merge checklist.
Each finding is marked **resolved** (fixed in code, with the test that covers it), **accepted** (left
on purpose, with the reason), or **open** (needs the learner).

## 1. Self-review findings (correctness, parity, feature-store overwrite risk)

| # | Area | Finding | Status | Resolution / evidence |
|---|---|---|---|---|
| 1 | Label leakage | A recency feature (`days_since_last_txn`) reveals the label. | resolved | Excluded from the spec. `test_label_window_transactions_do_not_change_any_feature`. |
| 2 | Label window | The assignment says 90 days; the data's label is 91 days (customer 697). | resolved | `LABEL_WINDOW_DAYS = 91`. Label reconstruction is in `data_dictionary.md`. |
| 3 | Source staleness | The monthly parquet is stale for 2026-07 (110 customer-months low, 102 customers missing). | resolved | Parquet read only for months ending before the cutoff. `test_active_months_ignores_months_that_overlap_or_follow_the_label_window`. |
| 4 | Parity | Training and scoring could diverge if the scoring path had its own logic. | resolved | One code path: `build.build_features` -> `compute_feature` -> `transforms`. Only `customer_ids` differs. `test_parity.py`, plus the mutation check (`PARITY_CHECK.md`: CAUGHT). |
| 5 | Feature store overwrite | A rebuild could add duplicate versions, or keep stale snapshots for a different as-of. | resolved | `register_version` refuses duplicate parameters and existing files. Build refuses a different as-of. Tests in `test_feature_store.py`. |
| 6 | `is_latest` atomicity | `is_latest` could flip without the insert, or leave two rows set. | resolved | Insert and flip run in one SQLite transaction (`with closing(_connect()) as conn, conn:`). `test_each_feature_has_its_own_latest_flag`, plus the real registry check. |
| 7 | Zero-activity default | A zero-row customer could come out as NaN. | resolved | Explicit `reindex(..., fill_value=...)`. Not masked with `fillna`. Check `zero_activity_defaults_applied`. |
| 8 | Zero-activity invariant | My first invariant was wrong (customer 350 with a 2026-05-01 transaction). | resolved | Build failed safely on the first run. Check rewritten to the valid subset rule, spec updated. See ARTIFACT_NOTES item 4. |
| 9 | Quality checks | The reconciliation check had no failure test. | resolved | `test_txn_count_off_by_one_window_fires_reconciliation_check`. |
| 10 | Mutation harness | The harness dropped `transactions.db` and produced a false "CAUGHT". | resolved | Copy fixed. Verdict now needs an `AssertionError`. See ARTIFACT_NOTES item 6. |
| 11 | Dependency | Spearman in pandas imports scipy, which is not pinned. | resolved | Spearman computed as Pearson on ranks. |
| 12 | Scoring errors | An unknown id or a not-yet-signed-up id could return an empty result silently. | resolved | `population` raises `KeyError` / `ValueError`. `score_customer.py` exits 2 with a message. Checked manually with id 99999. |
| 13 | Drift | No reference snapshot, so the drift check cannot pass in the build. | accepted | Reported as "skipped", never "passed". Covered by unit tests with a synthetic reference. Reason: no prior build exists. |
| 14 | Concurrency | Two simultaneous builds could race on `MAX(version)`. | accepted | Single-user local use, per the assignment's local-only constraint. Documented in `ARTIFACT_NOTES.md`. |
| 15 | Population filter | Customers who signed up after `as_of` are excluded silently in training. | accepted | Intentional, because they are not part of the population at that date. The population rule is in `features/build.py` and the spec. |
| 16 | Interpretation text | `VERSION_COMPARISON.md` interpretation is rule-based, not a human judgment. | accepted | The numbers are from the registry. The learner should read them and say whether the interpretation holds. |

## 2. Coverage-of-intent check (skill.md Step 2, item 2)

Spec items and where each is exercised:

| Spec item | Test or check |
|---|---|
| `txn_count_prior` (3 versions, windows 90/180/365) | `test_txn_count_*`, `test_longer_window_counts_at_least_as_many_transactions`, `test_real_registry_has_every_spec_versioned_feature_fully_registered` |
| `spend_prior_winsorized` (2 versions, caps 250/500) | `test_spend_*`, parity sample includes cap-sensitive customers |
| `return_rate_prior_180d` (zero default 0.0) | `test_return_rate_*` |
| `active_months_prior_12m` (parquet, zero default 0) | `test_active_months_*` |
| `tenure_days` | `test_tenure_days_is_days_from_signup_to_as_of` |
| No leakage | `test_label_window_transactions_do_not_change_any_feature` |
| Parity (one code path) | `test_parity.py` (3 tests), `PARITY_CHECK.md` |
| No unexpected nulls | `test_injected_null_fires_null_check` |
| Zero-activity defaults | `test_zero_activity_row_with_nan_default_*`, `test_zero_activity_row_with_nonzero_spend_*` |
| Ranges | `test_out_of_range_amount_*`, `test_return_rate_above_one_*` |
| Row counts | `test_dropped_customer_*`, `test_duplicated_customer_*` |
| Source reconciliation | `test_txn_count_off_by_one_window_*` (added in this review) |
| Drift | `test_shifted_distribution_*`, `test_identical_*`, `test_drift_without_reference_*` |
| Versioning mechanism | `test_feature_store.py` (7 tests) |
| As-of guard for registration | `test_training_build_refuses_a_different_as_of_*` (added in this review) |
| Idempotent re-run | Manual evidence: `build_training_features_rerun.log` (all versions skipped, exit 0). Not automated. |

## 3. Final review of FEATURE_LINEAGE.md and VERSION_COMPARISON.md

- **FEATURE_LINEAGE.md:** 8 registered versions across 5 features. Each version has its own entry with its parquet path,
  parameters, source justification and rationale. Regenerated from the schema and the registry after the last build.
- **VERSION_COMPARISON.md:** Two versioned features, with distribution tables, consecutive-version changes, and rule-based
  interpretation. `txn_count_prior` changes for 56% (v1 to v2) and 46% (v2 to v3) of customers. `spend_prior_winsorized` changes for 3%
  (45 customers), which matches the expected effect of raising the cap from 250 to 500.

## 4. Open items that need the learner (not Claude)

- [ ] **Stage 0 review.** Read `data_dictionary.md` yourself and spot-check at least one claim against the data. The spot-check queries are in its verification log.
- [ ] **Correct `feature_spec.md` yourself.** It is currently Claude's draft. Accept or change each decision, especially the label window (91 days), the recency exclusion, and the choice of versioned features and values.
- [ ] **Reconciliation conversation.** Run a separate Claude session that reviews your corrected spec against skill.md's Domain Context. Record the findings you agreed with, redirected or pushed back on.
- [ ] **Read `ARTIFACT_NOTES.md` and push back once** on anything that looks too clean. Ask Claude to re-check the zero-activity default, the as-of threading and `get_latest`.
- [ ] **Hand-check one feature value yourself**, not only through the logs above (the customer-2 spot-check was done by Claude).
- [ ] **Run `pytest` and `scripts.parity_mutation_check` yourself** on your machine.
- [ ] **Write or edit `README.md`.** Claude drafted it; check that every command works on your machine.
- [ ] **Rename the zip** to the required pattern (empid, name, level).
- [ ] **Decide on the open review items above** and note the decision in this file.
