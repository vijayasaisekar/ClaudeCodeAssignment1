# ARTIFACT_NOTES.md — self-critique log

Written by Claude during the build. Each item says what was wrong or uncertain, how it was found,
and what changed. Nothing here is "everything worked" without evidence. The learner should push back
on any item that looks thin.

## Things that were wrong, and what changed

1. **The label window is 91 days, not 90.** The assignment says "no purchase in the 90 days before the as-of date".
   A 90-day rule disagrees with `churned` for customer 697 (last transaction 2026-05-02 17:12, labeled 0).
   The 91-day rule (`[2026-05-02, 2026-08-01)`) matches all 1,500 labels. Found in Stage 0 by reconstructing the label.
   Fixed: `LABEL_WINDOW_DAYS = 91` in `features/transforms.py`. The spec and data dictionary record it.

2. **A recency feature would leak the label.** skill.md's first feature family is recency (`days_since_last_txn`).
   The label is "no transaction in the label window", so a recency value reveals it. Not built.
   The leakage test `test_label_window_transactions_do_not_change_any_feature` injects transactions inside the
   label window and asserts every feature is unchanged. It passes.

3. **The monthly parquet is stale for 2026-07.** The parquet matches the row table exactly for every month through
   2026-06. For 2026-07, 110 customer-months are lower in the parquet, and 102 customers' July transactions are missing from it.
   The 2026-05 to 2026-07 months also overlap the label window. Only `active_months_prior_12m` reads the parquet, and only
   for the 12 months 2025-05 to 2026-04, which end before the cutoff. `test_active_months_ignores_months_that_overlap_or_follow_the_label_window`
   covers this.

4. **My first zero-activity invariant was wrong, and the guardrail caught it on the first build.** I first wrote the check as
   "`active_months_prior_12m == 0` implies `txn_count_prior == 0`". The first build failed on 338 customers. Customer 350 has
   one transaction on 2026-05-01. It is before the cutoff, so the 365-day count sees it. The 12-month monthly window ends in April,
   so it does not. The check was rewritten to the valid subset rule: `txn_count_prior == 0` implies `spend == 0.0` and
   `return_rate == 0.0`, because the 180-day windows sit inside the 365-day count window. The spec's check text was updated to match.
   The first failing build wrote nothing to the registry, which is what the enforce step is for.

5. **The spec overclaimed twice, and I corrected both.**
   - "Large purchases are mainly electronics" was wrong. Electronics is 27% of purchases above 250, against 16% of all transactions.
     The spec now states those numbers.
   - "The stale 2026-07 month is inside the 365-day window" was wrong. Every window ends at 2026-05-02, so the July month is never read by
     the count feature. The spec now says so.

6. **The parity mutation harness had a bug that made a failure look like a catch.** The first run reported "CAUGHT", but the
   mutated tree failed with `no such table: transactions`. The harness copy excluded `*.db`, which also dropped the raw
   `data/transactions.db`. The verdict accepted any failure in the parity test. Fixed twice: the copy now skips only
   `registry.db` and `values/`, and "CAUGHT" requires an `AssertionError` from the parity comparison with no `DatabaseError` in the output.
   The re-run shows real `AssertionError`s on `spend_prior_winsorized` in two parity tests.

7. **Spearman needed scipy, which is not pinned.** pandas' `corr(method="spearman")` imports scipy. Replaced it with
   Pearson correlation on ranks, which is the same statistic and needs no new dependency.

8. **A rebuild with a different as-of would silently keep old snapshots.** A second run for another date skipped versions
   already registered by parameters, so a 2026-07-31 build would have kept values from 2026-08-01. Added a guard that raises
   when the stored snapshot's `as_of_date` differs. Covered by `test_training_build_refuses_a_different_as_of_for_already_registered_versions`.

9. **Two checks had no failure test.** The source-reconciliation check and the as-of guard were only exercised on clean data.
   Both now have tests that fire on bad input.

## Things checked directly (not taken on trust)

- **Zero-activity default.** 81 customers have no transaction rows. In the build, 333 customers have `txn_count_prior == 0`
  (365-day window). The check confirms their spend and return rate are exactly `0.0`, with no NaN. The test
  `test_zero_activity_row_with_nan_default_fires_zero_activity_check` confirms the check fires when it is not.
- **As-of threading.** The cutoff is computed once, in `history_cutoff(as_of)`. Every transform receives `as_of` as a parameter.
  The as-of guard test runs the build at 2026-08-01 and at 2026-07-31 and sees different cutoffs. Nothing reads the current date.
- **`get_latest` returns the highest version.** `test_is_latest_points_to_highest_version_not_an_earlier_one` registers three versions
  and checks `get_latest` returns version 3. The real registry is checked too: `is_latest = 1` on exactly one row per feature,
  at the highest version (`outputs/artifacts/registry_contents.txt`).
- **Hand-verified feature values.** For customer 2, every feature was recomputed with raw SQL and Python date arithmetic, not the
  pipeline's transforms. All eight values match (`outputs/artifacts/spot_check_customer_2.txt`).
- **The parity check catches a real split.** The mutation check was run and its output is in `PARITY_CHECK.md`.

## Known limitations (accepted, with reasons)

- **Drift check is skipped in the build.** No reference snapshot exists for this build. The check reports "skipped",
  not "passed", and the test covers the check itself with a shifted reference. A future build would compare against the previous
  registered snapshot.
- **One registry, one as-of.** A registered version stores the as-of of its first build. Scoring at another date is supported
  by `scripts/score_customer.py` (read-only), but training registration for a second as-of is refused by design.
- **Interpretation text in `VERSION_COMPARISON.md` is rule-based.** The thresholds in `scripts/compare_feature_versions.py` produce it.
  It is not a human judgment. The numbers in each table come directly from the registry snapshots.
- **Not concurrency-safe.** Two builds run at the same time could race on `MAX(version)`. Single-user local use only.
- **Python version (resolved).** The first build ran on Python 3.14.3, the only interpreter installed at that point. Python 3.11.9 was then installed per-user and the whole pipeline was rebuilt from scratch on it: build, re-run, comparison, lineage, quality checks, parity-mutation check and all 42 tests pass there (outputs/artifacts/*.log, pytest_output.txt).

## Process deviations (read these before grading)

- **This was not a learner-driven run.** The assignment asks the learner to write `feature_spec.md` by hand, to review Stage 0 in a separate
  session, to reconcile the spec with Claude before the build, and to spot-check results personally. Claude (this session) produced
  `data_dictionary.md`, the draft `feature_spec.md`, and all of `features/`, `feature_store/`, `scripts/`, `tests/` and the artifacts.
  The Stage 0 pass and the spec reconciliation were not done in separate sessions. The learner must do those steps personally before the
  rubric items for them can be marked as met. `review_log.md` lists which items are open.
- **The skill was not invoked as a skill.** Claude followed `skills/churn-feature-pipeline/skill.md` as its build spec, and the repo layout
  and registry schema match it. A copy was added at `.claude/skills/churn-feature-pipeline/skill.md` so Claude Code can discover it, as the Helper Guide asks. The assignment's folder tree does not list `.claude/`, so it is an extra folder.
- **Claude used the `claude-haiku-5-5` model per the environment.** This pipeline needs no API key. No key is written to any file in the submission.
