# feature_spec.md — Churn Feature Pipeline

**Status: DRAFT for learner review.** Written by Claude as a corrected draft of the Stage 0
proposal, to be reviewed and confirmed by the learner before the build is invoked. The
assignment requires the learner to write or correct this file personally; every decision below
is one the learner should be able to defend and change if they disagree. Each decision lists
the evidence it rests on (see `data_dictionary.md`). - Review is completed.

As-of date: **2026-08-01**. Label window: `[2026-05-02, 2026-08-01)` (91 days, inclusive of
2026-05-02). **Usable history for every feature: strictly before `history_cutoff = as_of − 91 days = 2026-05-02 00:00:00`.**

## Corrections to the Stage 0 proposal

1. **Label window.** The assignment says "no purchase in the 90 days before the as-of date". The
   data's label is a 91-day window. A 90-day rule disagrees on customer 697. The features use the
   data's definition (91 days). `history_cutoff = as_of − 91 days`.
2. **Recency is ruled out.** The Stage 0 family list (skill.md's "Recency") includes
   `days_since_last_txn`. Because the label *is* "no txn in the label window", a recency value
   reveals the label. Recency is not a feature in this spec. The history-only features below are
   the replacement.
3. **The monthly parquet is not safe for recent months.** Stage 0 treated the parquet as a
   drop-in for the row table. The 2026-07 month is stale (110 customer-months lower than the row table;
   102 customers missing). The 2026-05 to 2026-07 months also overlap the label window. The parquet is
   used only for months that end before 2026-05-02.
4. **Zero-activity default for a return rate.** Stage 0 proposed a return rate with default 0.0 and
   no caveat. A customer with no transactions is not the same as a customer with zero returns. The spec
   keeps the 0.0 default but documents it as "no observed returns", and the activity signal
   is carried by `txn_count_prior`, so the two are not confused.
5. **Feature family coverage.** Stage 0 covered recency, frequency, monetary, engagement and profile.
   The spec omits recency (point 2) on purpose. Return signals and profile are kept.

## Candidate features

Every feature is computed from history strictly before `history_cutoff`. Zero-activity default
is stated per feature; no feature is ever null.

- **Feature**: `txn_count_prior` (versioned, see below)
  - **Source**: `data/transactions.db`, table `transactions` (`customer_id`, `txn_timestamp`)
  - **Computation**: count of transactions with `history_cutoff − window_days ≤ txn_timestamp < history_cutoff`.
    `window_days` is the versioned parameter.
  - **Zero-activity default**: `0` (integer). Customers with no rows in the window get `0`, via an explicit reindex with `fill_value=0`.
  - **If multiple sources could supply this, which and why?**: Row table. The parquet's calendar-month grain cannot express a window that starts on 2026-05-02 − N days (the cut lands mid-month), and it would include partial-month data from the stale/overlapping months. Row level is needed for the exact boundary.
  - **Rationale**: "This predicts churn because customers whose purchase count in the pre-label-window history fell
    well below their own longer-run pace are fading, distinct from customers who have always bought rarely. The 90/180/365-day
    windows separate a recent decline from a long-run low-activity customer." Using multiple window lengths is the versioning exercise (see below).

- **Feature**: `spend_prior_winsorized` (versioned, see below)
  - **Source**: `data/transactions.db`, table `transactions` (`amount`, `txn_timestamp`)
  - **Computation**: `sum(min(amount, cap_amount))` over transactions with
    `history_cutoff − 180 days ≤ txn_timestamp < history_cutoff`. Window fixed at 180 days. `cap_amount` is the versioned parameter.
  - **Zero-activity default**: `0.0`.
  - **If multiple sources could supply this, which and why?**: Row table. Winsorizing needs individual amounts. The monthly
    `total_amount` cannot be capped per transaction, and it has the same boundary problem.
  - **Rationale**: "This predicts churn because a customer whose capped spend has fallen relative to history is
    disengaging, distinct from a customer who buys often but cheaply (which `txn_count_prior` captures). Winsorizing stops one
    large purchase from masking a fading customer, and the cap is an explicit choice rather than a silent outlier drop."

- **Feature**: `return_rate_prior_180d` (not versioned)
  - **Source**: `data/transactions.db`, table `transactions` (`is_returned`, `txn_timestamp`)
  - **Computation**: `sum(is_returned) / count(*)` over the same 180-day prior window as above.
  - **Zero-activity default**: `0.0`, meaning "no observed returns". It is not a measured rate. Zero-activity customers are
    identified by `txn_count_prior` and `active_months_prior_12m`, not by this value.
  - **If multiple sources could supply this, which and why?**: Row table. `return_count` in the parquet is at monthly grain; a 180-day window
    cannot be expressed exactly from it.
  - **Rationale**: "This predicts churn because a rising share of returned orders before the label window signals unmet
    expectations that precede a lapse. It is distinct from low spend, since a customer can spend normally and still return a large
    share."

- **Feature**: `active_months_prior_12m` (not versioned)
  - **Source**: `data/transactions_monthly_agg.parquet` (`customer_id`, `txn_month`, `txn_count`)
  - **Computation**: number of calendar months in `[2025-05-01, 2026-04-30]` (12 full months, all ending before 2026-05-02)
    where the customer has a row with `txn_count > 0`.
  - **Zero-activity default**: `0` (integer). A customer with no row in those months gets `0`.
  - **If multiple sources could supply this, which and why?**: Parquet, chosen on purpose. It is a breadth count over whole calendar
    months, which is exactly the parquet's grain. It is the one feature where the pre-aggregated source is the justified choice.
    The 12 months were checked to match the row table exactly (verified in `data_dictionary.md`). The stale 2026-07 month and the
    straddling 2026-05 month are excluded.
  - **Rationale**: "This predicts churn because a customer active in many months of the year has a habit, and a customer
    active in few months is a sporadic buyer who lapses easily. This is distinct from `txn_count_prior`: ten purchases in one month
    and one purchase in each of ten months give the same count but different engagement."

- **Feature**: `tenure_days` (not versioned)
  - **Source**: `data/customers.csv` (`signup_date`)
  - **Computation**: `(as_of − signup_date).days`. The population is limited to customers with `signup_date ≤ as_of`.
  - **Zero-activity default**: not applicable. Every customer has a signup date, so no default is needed.
  - **If multiple sources could supply this, which and why?**: Only one source.
  - **Rationale**: "This predicts churn because a customer with zero prior purchases who signed up last month is a new
    customer, not a lapsed one. Tenure is the baseline that tells the model whether low activity is normal for this customer's age."

**Excluded on purpose (leakage):** any recency feature (`days_since_last_txn` and variants); any count, sum or
return flag from `[history_cutoff, as_of)`; any parquet month from 2026-05 onward; the `churned` column itself.

## Train/score parity design

- **Shared function/code path**: `features.build.build_features(as_of, source_paths=None, customer_ids=None)`.
  Every feature is computed by one function, `features.build.compute_feature(name, as_of, sources, customer_ids, params)`,
  which calls the pure transform in `features/transforms.py`. Training and scoring both reach it through `build_features`.
- **Only allowed training/scoring difference**: `customer_ids`. Training passes `None` (all customers signed up by `as_of`).
  Scoring passes one or more ids. Both then run the identical transforms over the identical loaded sources.
- **How as_of is threaded (not hardcoded)**: `as_of` is a parameter of `build_features`, of `compute_feature`, and of every transform.
  The cutoff is derived in a single helper, `history_cutoff(as_of) = as_of − 91 days`. Nothing reads the current date and no default
  `as_of` is baked into a transform. The scripts take `--as-of` (default `2026-08-01`).
- **Parity test**: `tests/test_parity.py` builds one customer through the training path and through the scoring path at the same
  as-of date and asserts every feature value is exactly equal.

## Feature store, versioning & lineage

- **Features versioned**: `txn_count_prior` (≥2 versions) and `spend_prior_winsorized` (≥2 versions). Both are designated
  here; no other feature is versioned.

- **Feature**: `txn_count_prior` — **Parameter**: `window_days` (look-back length before `history_cutoff`)
  - Version 1: `window_days = 90` — the 90 days immediately before the label window (same length as the label, so a direct comparison).
  - Version 2: `window_days = 180` — widened because many customers buy about once a month, so 90 days often holds zero or one transaction. Widening
    reduces the noise in the zero/one bucket and is a real change in values, not a rename.
  - Version 3: `window_days = 365` — covers a full annual purchase cycle, so seasonal buyers are not counted as fading when they simply
    have not reached their usual season.
  - Reason each version differs from the last: v2 widens the window to reduce sparsity noise; v3 widens to a full year to remove the
    seasonal confound. Each change changes the counts for many customers.

- **Feature**: `spend_prior_winsorized` — **Parameter**: `cap_amount` (per-transaction cap, dollars)
  - Version 1: `cap_amount = 250` — about the 99th percentile of transaction amounts (255.66). Removes the rare very large purchases.
  - Version 2: `cap_amount = 500` — about the 99.9th percentile (518.34). Keeps genuine large purchases that version 1 truncated.
  - Reason v2 differs from v1: version 1 treats legitimate large purchases as noise. Version 2 keeps them and caps only the
    extreme tail. Electronics is over-represented among purchases above 250 (27% of them, against 16% of all transactions),
    so the cap is not just a catch-all for one category. Version 1 truncates these purchases for every category. This changes
    spend for customers with purchases between 250 and 500 (128 transactions above 250 in total).

- **What forces a version bump vs. not**: A new version is needed when a parameter value, the window, or the computation
  changes and the new values differ materially for some customers. A renamed column, a docstring change or a reordered
  column does not create a version. Existing versions are never overwritten. A new value gets a new row and a new
  parquet file, and `is_latest` moves in the same transaction.

- **What a lineage entry must let someone reconstruct**: for each feature and each stored version, the source file and table
  and columns, the filter (the exact timestamp window from `history_cutoff` and `window_days`/180-day), the aggregation
  (count, capped sum, return share, distinct active months), the zero-activity default, the parameters, the rationale, and the
  registry row with the exact `parquet_path`. `FEATURE_LINEAGE.md` is generated from `features/schema.py` and the registry so it
  cannot drift.

## Multi-source judgment calls

- **Feature**: `txn_count_prior` — **Source chosen**: `transactions.db` — **Why**: window boundaries (2026-05-02 − N days) fall mid-month, which the
  monthly grain cannot express. Every window ends at 2026-05-02, so the stale 2026-07 month is never read by this feature. The row table is used
  to keep the boundary exact.
- **Feature**: `spend_prior_winsorized` — **Source chosen**: `transactions.db` — **Why**: capping needs individual transaction amounts. The aggregate has only totals.
- **Feature**: `return_rate_prior_180d` — **Source chosen**: `transactions.db` — **Why**: the 180-day window is not month-aligned, so the monthly `return_count` cannot give the exact share.
- **Feature**: `active_months_prior_12m` — **Source chosen**: `transactions_monthly_agg.parquet` — **Why**: it counts whole calendar months, which the aggregate
  already provides, and every month used ends before the label window. Verified equal to the row table for those months.
  Choosing the row table here would be defensible too, and the two agree on these months.
- **No feature blends both sources.** Each feature reads from exactly one source.

## Data-quality checks

- **Check**: no nulls in any feature column after defaulting — **Catches**: a reindex or merge that leaves a zero-activity customer as
  NaN (the most likely bug in this build) — **On failure**: raise, exit non-zero.
- **Check**: zero-activity defaults applied — for every customer with `txn_count_prior == 0` (count window, 365 days), `spend_prior_winsorized == 0.0`
  and `return_rate_prior_180d == 0.0`. The 180-day windows are contained in the count window, so this holds for any correct build. Catches a feature that silently drops zero-activity
  customers or writes NaN for them — **On failure**: raise, exit non-zero.
  (`active_months_prior_12m` is not used for this check. Its months end in April, so it does not see 2026-05-01 transactions, which the 365-day count does.)
- **Check**: ranges — `txn_count_prior` in `[0, 1000]`; `spend_prior_winsorized` in `[0, 10000]`; `return_rate_prior_180d` in `[0, 1]`;
  `active_months_prior_12m` in `[0, 12]`; `tenure_days` in `[0, 5000]` — **Catches**: a unit error (cents vs dollars), a duplicated
  join that inflates counts, or a bad signup date — **On failure**: raise, exit non-zero.
- **Check**: row count reconciles — output rows equal the population (customers with `signup_date ≤ as_of`, or the requested
  `customer_ids`), and `customer_id` is unique. Catches a join that drops or duplicates customers — **On failure**: raise, exit non-zero.
- **Check**: source reconciliation — the sum of `txn_count` for the 90-day window equals the number of row-table rows in that
  window. Catches a window-boundary off-by-one — **On failure**: raise, exit non-zero.
- **Check**: drift against a reference snapshot, when one is supplied — fails if a feature's mean moves more than 25% from the
  reference. Catches a silent computation change between builds — **On failure**: raise, exit non-zero. When no reference is supplied the
  check reports "skipped" and is recorded as such, not as a pass.
