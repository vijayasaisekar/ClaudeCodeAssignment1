---
name: churn-feature-pipeline
description: >
  Builds a versioned, lineage-documented feature pipeline with a local feature store for the
  e-commerce customer churn dataset. Also used earlier, in a separate invocation, to generate
  a best-effort `data_dictionary.md` and a candidate-feature proposal directly from the raw
  sources, for the learner to review before `feature_spec.md` is drafted. Ingests from three
  heterogeneous sources (a flat file, a SQL-style database, and a pre-aggregated parquet
  extract), builds a single parity-tested feature module shared by training and scoring paths,
  stands up a local feature store (SQLite metadata/version registry + parquet value
  snapshots), implements a spec-defined versioning exercise (at least two candidate features
  each with two or more versions; which features, which parameter(s), how many versions, and
  which values are the learner's own choice, per `feature_spec.md`), adds automated
  drift/null/outlier checks, generates per-feature lineage documentation covering every stored
  version, and a full test suite including a train/score parity check. The build step requires
  `feature_spec.md` to already exist alongside a learner-confirmed `data_dictionary.md`, the
  raw data sources, and `requirements.txt` — this skill implements a confirmed spec, it does
  not originate one.
---

# Churn Feature Pipeline

## Purpose

You are Claude, building a production-quality feature engineering pipeline for the
e-commerce customer churn dataset described in the learner-confirmed `data_dictionary.md`.
Build the whole thing —
feature module, feature store, versioning exercise, drift/quality checks, lineage docs,
tests — to a fixed production-readiness bar, implementing `feature_spec.md` faithfully.

## When to Use

This skill covers two separate invocations, run at two different points in the assignment —
do not conflate them.

**Stage 0 — metadata and candidate-feature proposal.** Invoke this first, before
`feature_spec.md` exists at all. Its job is to give the learner something concrete to react
to, not to make any decision on their behalf — see "Stage 0" below.

**Build — the pipeline itself.** Use this only after the learner's `feature_spec.md` has been
independently reviewed, corrected against Stage 0's proposal, and reconciled in a review
conversation (see `Helper Guide.docx`, sections on proposal review and spec reconciliation).
This stage implements a confirmed spec — it does not originate one. If `feature_spec.md` does
not exist yet, stop and say so rather than drafting it yourself. Once invoked, it builds a
versioned local feature store pipeline for this churn dataset in one straight run: ingestion,
transforms, the feature store, the spec-defined versioning exercise, quality checks, lineage
documentation, and the test suite.

## Stage 0 — Generate `data_dictionary.md` and a candidate-feature proposal

Run this before anything else, directly against the raw sources — with no prior
`data_dictionary.md` to lean on, since generating it is the point of this stage.

1. Load all three raw sources (`data/customers.csv`, `data/transactions.db`,
   `data/transactions_monthly_agg.parquet`) and, if the learner has provided one, any business
   requirements document. Do not edit any of them.
2. From the sources alone, generate `data_dictionary.md`: business context (inferred from
   column names/values, stated as inference, not fact where you're guessing), a schema for
   every source (columns, dtypes, nullability observed in practice), time dimensions (which
   columns are timestamps, what grain each source is at, whether sources can disagree at the
   edges), and any data-quality realities you can actually detect by inspecting the data
   (e.g. customers with zero matching transaction rows, out-of-range values, null patterns) —
   not ones you assume must be there because they're common in this kind of dataset.
3. From that generated dictionary (+ the business requirements doc if supplied), generate a
   candidate-feature proposal: plausible features with a name, rationale, and named source(s)
   each — see "Domain Context" below for the kind of feature families a churn problem
   typically draws from, but do not treat that list as a template to fill in mechanically.
4. Treat both outputs as best-effort, not authoritative. This is inference from raw data
   under time pressure, not a verified spec — say so explicitly in `data_dictionary.md`'s
   own text, and flag your own low-confidence fields (a guessed column meaning, a
   data-quality claim you didn't fully verify across the whole dataset, a feature rationale
   that's more generic than dataset-specific) rather than presenting everything with uniform
   confidence. There is no fixed accuracy target to hit here — the point is that the learner's
   review in the next step is expected to find real things to correct, not to rubber-stamp
   this output.
5. Stop here. Do not draft `feature_spec.md` yourself — that is the learner's own step, done
   by reviewing and correcting this proposal (see `Helper Guide.docx`).

If a `data_dictionary.md` or `FEATURE_LINEAGE.md` already exists from an earlier phase of this
same project (not just a first-run artifact), read it and carry its context forward instead of
regenerating blind — see Guardrails.

## Inputs Required

**For Stage 0:**
- `data/customers.csv`, `data/transactions.db` (SQLite, table `transactions`), and
  `data/transactions_monthly_agg.parquet` — provided, the raw sources. Do not edit them.
- `requirements.txt` — provided, pins dependencies.
- A business requirements document, if the learner has one — optional, strengthens the
  candidate-feature proposal but is not required to produce one.

**For the build stage:**
- `data_dictionary.md` — generated in Stage 0, then reviewed and corrected by the learner.
  Read this in full before doing anything else — it states real constraints (e.g. no leakage
  past the as-of date, zero-activity customers exist, the same signal is available from more
  than one source at a different grain) that a generic feature-engineering pass would miss.
  Treat it as ground truth at this stage: the learner's correction pass is what makes it
  trustworthy, and the build stage should not re-litigate it.
- `feature_spec.md` — must already exist, stating the candidate features (with source(s) and
  rationale), the train/score parity design, the feature-store/versioning/lineage plan, the
  multi-source judgment calls, and the data-quality checks. If it doesn't exist, stop and say
  so rather than originating one yourself.
- `requirements.txt` — provided, pins dependencies (pandas, numpy, pyarrow, pytest). SQLite
  access uses Python's stdlib `sqlite3`, so it is not a separate dependency. The feature store
  is built entirely on SQLite + parquet — do not add mlflow, feast, or any other
  feature-store library.

## Domain Context: The Checklist for a Real `feature_spec.md`

This section is the standard both you and the learner apply — there is no separate
learner-authored checklist. Use it for three things: (1) generating Stage 0's
candidate-feature proposal without inventing generic filler, (2) the learner's own review of
Stage 0's proposal before correcting it into `feature_spec.md` (see `Helper Guide.docx`), and
(3) your own read of the confirmed `feature_spec.md` in Step 1 below, to judge whether it's
genuinely been corrected or just rubber-stamped. All three uses apply the same bar defined
here — this is deliberately the one place this bar is written down.

### Plausible feature families for this dataset

For an e-commerce churn problem built from `data_dictionary.md`'s sources, the feature
families a reasonably informed spec would typically draw from include:
- **Recency** — time since last activity (e.g. `days_since_last_txn`). Needs row-level
  precision from `transactions.db`; the monthly parquet aggregate can't express an exact
  recency window.
- **Frequency** — how often the customer transacts in a window (e.g. transaction count in
  the last N days/months). Could reasonably come from either source depending on the window's
  alignment to calendar months.
- **Monetary** — spend magnitude and/or trend (e.g. recent spend, average monthly spend,
  spend trajectory). The right-skew data-quality note in `data_dictionary.md` is directly
  relevant to how these should be computed.
- **Engagement consistency** — breadth of activity over a longer window (e.g. count of
  active months in the last year), naturally suited to the monthly aggregate.
- **Return/quality signals** — return rate or return count, a plausible dissatisfaction
  proxy that can precede churn.
- **Customer profile** — tenure, acquisition channel, region: static or near-static
  attributes from `customers.csv`, no source ambiguity.

A spec that covers none of these families isn't automatically wrong, but it's worth noticing
during your review — ask whether the omission is a deliberate, stated choice or just an
oversight. Conversely, a spec that mechanically lists all six with no distinct rationale per
feature likely hasn't done real thinking either; this checklist is meant to catch both failure
modes, not just the first one.

### What makes a feature rationale real vs. filler

A rationale only counts as real if it survives the question "why, specifically, would that
behavior indicate churn risk, as opposed to just being correlated with something else?" —
"might be predictive" or "seems relevant" is filler regardless of how it's worded. A real
rationale names a specific customer behavior and distinguishes it from a plausible confound
(e.g. a drop in frequency relative to the customer's own baseline, distinct from a customer
who has always been low-activity). At minimum, a real candidate-features section should cover,
per feature: name, source(s), computation, an explicit zero-activity default (never a bare
null/NaN), and this kind of rationale.

### What makes train/score parity design trustworthy

Suspicious: two functions (or two branches inside one function) computing the same feature
differently depending on whether it's the training or scoring call. Trustworthy: exactly one
code path, with the only conditional being which `customer_ids` get selected at the end, and
`as_of` threaded through as a parameter everywhere, never hardcoded or defaulted inside a
transform. At minimum, a real parity-design section should cover: the name of the one shared
function/code path, the single allowed difference between the training and scoring call
sites, and how `as_of` is threaded through as a parameter.

### What makes a version bump real vs. cosmetic

Real: the parameter, source, or computation actually changed and the new value differs
materially from the old one for at least some customers, with a stated business reason for
the change (not "just testing a different number"). Cosmetic: a renamed column or a
reformatted description with no underlying computational change. A lineage entry is detailed
enough if it would let someone recompute the feature by hand from raw data without reading any
code. At minimum, a real versioning/lineage section should cover: which ≥2 distinct features
are versioned (each with ≥2 versions), per feature the parameter varied and its value at each
version, the business reason each version differs from the last, and what a lineage entry
must let someone reconstruct without reading code.

### What makes a multi-source choice defensible

A feature belongs on the row-level table (`transactions.db`) instead of the monthly aggregate
(`transactions_monthly_agg.parquet`) when its window is short enough that a real,
verifiable gap between the two sources (see `data_dictionary.md`'s stated data-quality
realities) could actually change the answer. A silently wrong choice looks like picking the
aggregate because it's easier to read, with no comment on whether a source-timing gap matters
for that specific window. At minimum, a real multi-source-judgment section should cover, per
feature that could plausibly come from either source: which source was chosen, and why.

### What makes a data-quality check load-bearing vs. for-show

Load-bearing: a check that would catch a mistake actually plausible for this pipeline (e.g. a
zero-activity customer ending up with a null instead of the stated default — an easy
off-by-one in a reindex/fillna step). For-show: a generic "no nulls anywhere" assertion with
no connection to a real failure mode in this dataset. A failing check must raise / exit
non-zero — never just log a warning. At minimum, a real data-quality section should cover: no
unexpected nulls after defaulting, the zero-activity default is actually applied (not a silent
NaN), monetary/aggregate features stay within a sane bound, and row counts before/after the
build reconcile against the customer count.

## Workflow

### Repo scaffold to create
```
.
├── data/customers.csv                       <- provided, do not edit
├── data/transactions.db                     <- provided, do not edit (SQLite, table `transactions`)
├── data/transactions_monthly_agg.parquet    <- provided, do not edit
├── data_dictionary.md                       <- Stage 0 generates this; learner reviews/corrects it, then do not edit further
├── requirements.txt                          <- provided
├── pytest.ini                                <- provided, sets pythonpath so `pytest` resolves
│                                                 `features`/`feature_store` imports with no
│                                                 extra flags or PYTHONPATH changes needed
├── feature_spec.md                          <- provided, implement faithfully
├── features/
│   ├── __init__.py
│   ├── build.py                  <- the ONE shared entry point: build_features(as_of, source_paths=...)
│   ├── ingest.py                 <- one loader function per source (CSV / SQLite / parquet), pure I/O, no feature logic
│   ├── transforms.py             <- individual feature functions, pure and unit-testable
│   ├── schema.py                  <- output feature schema (names, dtypes, nullability, version) as versioned metadata
│   └── quality_checks.py         <- drift + null/outlier checks, runnable standalone
├── feature_store/
│   ├── store.py                   <- feature store API: register_version(), get_latest(), get_version(), list_versions()
│   ├── registry.db                <- SQLite metadata/version registry (see schema below), generated
│   └── values/                    <- one parquet snapshot per (feature_name, version), generated
│       └── <feature_name>__v<version>.parquet
├── scripts/
│   ├── build_training_features.py <- calls features/build.py in "training" mode, writes to the feature store
│   ├── score_customer.py          <- calls features/build.py in "scoring" mode for one or more customer_ids
│   └── compare_feature_versions.py <- per-feature version comparison for whichever feature(s) feature_spec.md designates as versioned (see Step 3)
├── tests/
│   ├── test_transforms.py        <- pure feature-function logic, edge cases (zero activity, missing dates)
│   ├── test_parity.py            <- proves training-path and scoring-path produce identical features for the same customer/as-of-date
│   ├── test_quality_checks.py    <- drift/null/outlier checks fire on deliberately bad input
│   └── test_feature_store.py     <- proves every version of every feature_spec.md-designated versioned feature is stored and independently retrievable
├── FEATURE_LINEAGE.md            <- auto-generated: each feature (every stored version)'s business rationale, source(s), transform, and feature-store location
├── ARTIFACT_NOTES.md             <- self-critique log
├── PARITY_CHECK.md               <- train/score parity verification result
└── VERSION_COMPARISON.md         <- per-feature version comparison + interpretation for the spec-defined versioning exercise
```

### Step 0 — Confirm the raw data loads cleanly from every source
Before implementing any feature:
1. Set up a Python environment if one isn't already active (e.g. `python3 -m venv .venv &&
   source .venv/bin/activate`), then `pip install -r requirements.txt`.
2. Load all three sources: `data/customers.csv` with `pandas.read_csv`, `data/transactions.db`
   with `sqlite3.connect(...)` or `pandas.read_sql(...)`, `data/transactions_monthly_agg.parquet`
   with `pandas.read_parquet`. Confirm row counts and dtypes look sane for each.
3. Confirm the specific data-quality realities `data_dictionary.md` calls out are actually
   present rather than assumed — e.g. that some customers have zero matching rows in
   `transactions.db`, and that the row-level table and the monthly-aggregate parquet file
   actually can disagree at the edges (spot-check a couple of customers across both).
4. Do not modify any source file. If you find what looks like a genuine data defect, note it
   in `ARTIFACT_NOTES.md` rather than silently fixing the source file.

### Step 1 — Implement the feature module, feature store, and lineage docs from the spec

Read `feature_spec.md` in full, then implement it faithfully:

#### 1a. Ingestion and transforms
1. `features/ingest.py` — one loader function per source: a CSV loader for `customers.csv`, a
   SQLite loader against `data/transactions.db`'s `transactions` table, and a parquet loader
   for `data/transactions_monthly_agg.parquet`. Pure I/O — no feature logic here, so ingestion
   can be unit-tested and swapped independently of transforms.
2. `features/transforms.py` — one pure function per feature named in `feature_spec.md`, each
   independent of any I/O. Handle the zero-activity case explicitly per the spec's stated
   default, not with a bare `try/except` that swallows the real problem. For any feature the
   spec says should come from a specific source among several candidates, the function should
   only touch the data it needs from that source — don't quietly blend both without the spec
   calling for reconciliation.
3. `features/schema.py` — the output feature list as versioned metadata: name, dtype,
   nullable (should be `False` for all if defaults are correctly applied), source(s), and the
   feature-set version from the spec.
4. `features/build.py` — the single `build_features(as_of, ...)` entry point that both
   `scripts/build_training_features.py` and `scripts/score_customer.py` call, using
   `features/ingest.py` for all I/O. There must be exactly one code path here — if you find
   yourself writing separate logic for "training mode" vs. "scoring mode" beyond which rows
   they select, that's a parity bug; go back and unify it.
5. `features/quality_checks.py` — runnable standalone against a features DataFrame,
   implementing every check listed in `feature_spec.md`'s data-quality section, each
   returning a clear pass/fail plus which rows/features triggered a failure.

#### 1b. The local feature store (SQLite registry + parquet values)
Build `feature_store/` as a small, real feature store — not a bespoke JSON manifest, not
mlflow. Use exactly this registry schema so retrieval logic is predictable:

**`feature_store/registry.db`**, table `feature_registry`:

| Column | Type | Notes |
|---|---|---|
| `feature_name` | TEXT | e.g. `recent_spend_adjusted_90d` |
| `version` | INTEGER | starts at 1, increments per feature_name |
| `created_at` | TEXT (ISO-8601) | when this version was registered |
| `description` | TEXT | one or two sentences, human-readable |
| `source_columns` | TEXT | source file/table + column(s), e.g. `data/transactions.db:transactions.amount,txn_timestamp` |
| `transform_summary` | TEXT | short prose description of the computation |
| `business_rationale` | TEXT | why this feature exists / why this version differs from the prior one |
| `parameters` | TEXT | JSON-encoded dict of any tunable parameter values for this version (e.g. `{"multiplier": 2.0}`); empty JSON object `{}` if none |
| `parquet_path` | TEXT | relative path to this version's value snapshot, e.g. `feature_store/values/recent_spend_adjusted_90d__v1.parquet` |
| `is_latest` | INTEGER (0/1) | exactly one row per `feature_name` has `is_latest = 1`; registering a new version flips the prior latest row to 0 in the same transaction |

Primary key: `(feature_name, version)`.

**`feature_store/values/<feature_name>__v<version>.parquet`** — one snapshot per registered
version: columns `customer_id`, the feature's own value column (named after the feature), and
`as_of_date`. Never overwrite an existing version's parquet file — a new version gets a new
file and a new registry row.

`feature_store/store.py` exposes at minimum:
- `register_version(feature_name, values_df, description, source_columns, transform_summary, business_rationale, parameters) -> version` — writes the parquet snapshot, inserts the registry row, flips `is_latest`, returns the new version number.
- `get_latest(feature_name) -> DataFrame` and `get_version(feature_name, version) -> DataFrame` — both read from the registry to resolve the parquet path, then load it. Never hardcode a parquet filename outside `store.py`.
- `list_versions(feature_name) -> DataFrame` — every registered version's metadata row, most recent first.

Every feature produced by `features/build.py` that `feature_spec.md` names as a candidate
feature gets registered into this store when `scripts/build_training_features.py` runs, not
just the versioning exercise below.

#### 1c. Versioning exercise (mechanism and minimum count are fixed, everything else is not)
Two things are fixed, everything past them is the learner's own design choice, stated in
`feature_spec.md`:
- The feature store must demonstrably support N versions of a feature (N ≥ 2), not just
  single-shot registration.
- **At least two distinct candidate features** must each be versioned this way (each with
  N ≥ 2 of its own versions) — a single versioned feature is not enough to demonstrate the
  mechanism across more than one case.

Beyond that floor, *how many* features get versioned (two is the minimum, more is fine),
*how many versions* each one gets (two is the minimum per feature, more is fine), *which*
features, and *which* parameter each takes are entirely the learner's choice. This is not a
single designated exercise on one fixed feature with exactly two versions: any versioned
feature may have two versions or more than two, and nothing in this pipeline should assume a
hardcoded "v1 vs v2" pair is the only shape a versioned feature can take. For each of the (at
least two) features the spec chooses to version: it must take a tunable parameter (a
multiplier, a window length, a threshold — whatever that feature's own design naturally
supports), get at least two versions (more is fine) with a different parameter value per
version, with every version registered in the feature store and none of them ever
overwritten. For each versioned feature, `feature_spec.md` must state which parameter, the
value for every version it defines, and the business reason each new version's value changed
(e.g. "the assumed reorder rate was recalibrated," "the recency window was shortened based on
updated churn-window analysis") — do not invent a feature, a version count, or parameter
values that aren't in the confirmed spec. If `feature_spec.md` designates fewer than two
features for versioning (or fewer than two versions for any of them), do not silently build
to that reduced scope and do not silently pad it out with a feature or version the spec never
named — **stop and tell the learner** the confirmed spec doesn't meet this pipeline's
versioning floor (at least two distinct features, each with at least two versions) and ask
them to revise `feature_spec.md` before you continue. This is a fallback, not the expected
path — the learner's own reconciliation with Claude before invoking this skill (see the
Helper Guide) should already have caught this; treat it as a sign that step was skipped or
incomplete, not as something to quietly fix on their behalf.

For every feature the spec designates as versioned, every one of its versions (not just the
first and last) must be independently retrievable via `feature_store.store.get_version(...)`,
and `get_latest(...)` must return whichever version is actually highest once all are
registered — do not hardcode retrieval logic that only handles exactly two versions. Then:
1. `scripts/compare_feature_versions.py` — for each versioned feature named in
   `feature_spec.md`, loads all of its versions for the full customer base via the feature
   store (not by recomputing from scratch), and produces a comparison per feature: how many
   customers' values changed, the distribution shift (e.g. summary stats or a quantile
   comparison) between versions, and — since this is a churn feature set — how many customers
   would move across a reasonable churn-risk-ranking threshold if this feature were used, if
   the spec's candidate model/ranking makes that checkable; if no ranking exists yet, compare
   the feature's own distribution and rank-order changes instead.
2. `VERSION_COMPARISON.md` — the results above, one section per versioned feature, each with a
   short interpretation: is a change of this size something a model consuming this feature
   would even notice, and why.

#### 1d. Lineage documentation
`FEATURE_LINEAGE.md` — generated from `features/schema.py`, `feature_store/registry.db`, and
the spec: for **every feature, across every stored version**, document its source(s)
(specific file/table + column), the transform that produces it, the one-line business
rationale, any version-specific parameters, and the feature-store location (registry table +
exact `parquet_path`) that holds it. This file should be regeneratable from code + the
registry, not hand-maintained prose that can drift from the implementation. For the
spec-defined versioning exercise specifically, every registered version of every versioned
feature must appear as its own distinct entry with its own rationale and parquet path — not
collapsed into one entry that only shows the latest.

After generating everything above, write `ARTIFACT_NOTES.md`: list at least one thing you got
wrong or reconsidered across transforms/build/store/checks (a default value that didn't match
the spec, a leakage risk you caught late, a quality-check threshold that was initially too
loose/strict, a feature-store retrieval bug). If you genuinely produced everything cleanly,
say so explicitly — but re-check the zero-activity default, the as-of-date threading, and that
`get_latest` actually returns each versioned feature's highest version (not an earlier one)
specifically before concluding that; those are the most common gaps in generated
feature/feature-store code like this.

### Step 2 — Build the full test suite, then verify parity yourself
Generate, across the four test files:
- **`test_transforms.py`** — each feature function in isolation: normal case, zero-activity
  case, single-record case, and (where relevant) a case right at a time-window boundary.
- **`test_parity.py`** — the test that matters most for this pipeline: build features for the
  same customer via the "training" path (historical as-of date, batch of many customers) and
  via the "scoring" path (single customer, same as-of date), and assert the resulting feature
  values are identical. If these two paths can't be driven through the same test with the
  same expected output, the parity guarantee in the spec isn't real — fix `build.py`, not the
  test.
- **`test_quality_checks.py`** — feed each check a deliberately bad input (an injected null,
  an out-of-range amount, a shifted distribution) and confirm it fires; feed it clean input
  and confirm it doesn't false-positive.
- **`test_feature_store.py`** — for each feature `feature_spec.md` designates as versioned,
  register its versions (using that feature's own spec'd values is fine), confirm each is
  independently retrievable by version number, confirm `is_latest` correctly identifies the
  highest version and not an earlier one, and confirm `list_versions` returns every version in
  the registry with distinct `parquet_path` values that all actually exist on disk.

Then run two checks yourself and record results in `PARITY_CHECK.md`:
1. **Parity mutation check** — in a scratch copy, deliberately reintroduce a training/scoring
   split (duplicate one transform with a subtly different implementation for the scoring
   path), rerun the suite, and confirm `test_parity.py` catches it. If it doesn't, the parity
   test isn't testing the right thing — strengthen it and repeat until it does, then restore
   the real file.
2. **Coverage-of-intent check** — diff the candidate features and data-quality checks listed
   in `feature_spec.md` against what the test suite actually exercises. List anything spec'd
   but untested, add a test for it, and note the addition.

### Step 3 — Self-review and resolve
Review the full diff generated so far (ingestion, transforms, build module, feature store,
quality checks, lineage doc, tests) as if you were a reviewer seeing it for the first time,
for correctness and maintainability issues — with particular attention to: any place training
and scoring could silently diverge, any feature whose null/default handling doesn't match what
the spec promised, and any place the feature store could silently overwrite a version instead
of creating a new one. For each finding: fix it if it's real, or note in a review log why
you're leaving it. Don't leave a list of unresolved findings unaddressed — resolve what you
can, and be explicit about what you didn't and why. Write this to `review_log.md`.

## Output Expectations

By the end of a run, the repo should contain:
- `features/`, `scripts/` — generated, ingesting from all three heterogeneous sources, with
  `FEATURE_LINEAGE.md` and `ARTIFACT_NOTES.md`.
- `feature_store/` — `registry.db` (`feature_registry` table) and `values/*.parquet`
  populated for every candidate feature; at least two distinct features are versioned (each
  with two or more versions), every version of every feature the spec designates as versioned
  is present, independently retrievable, and `is_latest` correctly set.
- `scripts/compare_feature_versions.py` run, with `VERSION_COMPARISON.md` documenting and
  interpreting the version-to-version difference for each versioned feature.
- `tests/` (transforms + parity + quality checks + feature store) passing, with
  `PARITY_CHECK.md` stating the parity-mutation-check result.
- A versioned parquet feature snapshot produced by `scripts/build_training_features.py` and
  registered in the feature store.
- `review_log.md` documenting the Step 3 self-review and how each finding was resolved.

See the Validation Checklist below for the literal checklist to confirm all of this is in
place before handing the build back to the learner.

## Guardrails

- SQLite + parquet only. Do not add mlflow, feast, or any other feature-store library or
  service to implement the feature store.
- Do not edit any raw data file (`data/customers.csv`, `data/transactions.db`,
  `data/transactions_monthly_agg.parquet`). If you find a genuine data defect, note it in
  `ARTIFACT_NOTES.md` — never silently patch the source file.
- During the build stage, do not edit or regenerate `data_dictionary.md` — once the learner
  has reviewed and corrected Stage 0's version, treat it as fixed input, the same way you
  would a provided file. If it looks wrong once you're deep in the build, say so in
  `ARTIFACT_NOTES.md` rather than silently rewriting it.
- If a `data_dictionary.md` or `FEATURE_LINEAGE.md` from an earlier phase of this same project
  is already present when Stage 0 runs, read it and carry its facts and open questions
  forward — do not regenerate from the raw sources as if no prior phase existed. Losing that
  context is exactly the downstream-error risk this note exists to prevent.
- Carrying prior context forward is not the same as trusting it blindly: if what you observe
  directly in the raw data contradicts a specific claim in that prior `data_dictionary.md` or
  `FEATURE_LINEAGE.md` (a column's stated meaning, a data-quality claim, a source's grain),
  do not silently keep the old claim and do not silently overwrite it with your new one either
  — stop and flag the contradiction explicitly in the newly generated `data_dictionary.md`,
  and let the learner's review resolve it. An inherited error compounds every feature built on
  top of it, which is worse than a missing one.
- Similarly, if `feature_store/registry.db` already has registered versions from a prior run
  when the build stage starts, do not treat the store as empty — register new versions on top
  of what's there, never reset or recreate it from scratch.
- Never overwrite an existing feature-store version's registry row or parquet file. A new
  version always gets a new row and a new file; `is_latest` must be flipped atomically with
  the new insert.
- Do not fabricate results in `ARTIFACT_NOTES.md`, `VERSION_COMPARISON.md`,
  `PARITY_CHECK.md`, or `review_log.md`. If a check genuinely passed cleanly on the first
  try, say so explicitly rather than inventing a finding — but re-verify the zero-activity
  default, as-of-date threading, and `get_latest` behavior before concluding that.
- This assignment involves no secrets, credentials, or API keys — everything runs locally
  against provided files. Do not introduce any, and do not add a `.env` requirement that
  doesn't exist.
- This skill implements a confirmed `feature_spec.md`; it does not originate one. If asked to
  build without a confirmed spec present, stop and say so.

## Validation Checklist

- [ ] `features/`, `scripts/` — generated, ingesting from all three heterogeneous sources,
      with `FEATURE_LINEAGE.md` and `ARTIFACT_NOTES.md`
- [ ] `feature_store/` — `registry.db` (`feature_registry` table) and `values/*.parquet`
      populated for every candidate feature; at least two distinct features are versioned
      (each with two or more versions), every version of every versioned feature is present,
      independently retrievable, and `is_latest` correctly set
- [ ] `scripts/compare_feature_versions.py` run, `VERSION_COMPARISON.md` documents and
      interprets the version-to-version difference for each versioned feature
- [ ] `tests/` (transforms + parity + quality checks + feature store) passing,
      `PARITY_CHECK.md` states the parity-mutation-check result
- [ ] A versioned parquet feature snapshot produced by `scripts/build_training_features.py`
      and registered in the feature store
- [ ] `review_log.md` exists and documents the Step 3 self-review

## Discovery note for Claude Code

This file lives at `skills/churn-feature-pipeline/skill.md` inside the assignment package.
For Claude Code to auto-discover it as a skill in your own cloned working repo, copy or
symlink it into `.claude/skills/churn-feature-pipeline/skill.md` there
(`mkdir -p .claude/skills/churn-feature-pipeline && cp skills/churn-feature-pipeline/skill.md
.claude/skills/churn-feature-pipeline/`). If your setup doesn't auto-discover it, paste this
file's contents directly as your message when starting the build instead.
