# Churn Feature Pipeline

## Overview

This skill builds a versioned, lineage-documented feature engineering pipeline and local
feature store for the e-commerce customer churn dataset in `data/`. It ingests from three
heterogeneous sources (a CSV, a SQLite database, and a parquet extract), produces a single
parity-tested feature module shared by training and scoring, implements a spec-defined
feature-versioning exercise (which feature(s), parameter, and values are the learner's own
choice), and generates lineage, quality-check, and test-suite output. It
implements an already-confirmed `feature_spec.md` — it does not write the spec itself.

## Files in This Skill

- `skill.md` — the full build spec Claude follows: purpose, required inputs, the repo
  scaffold, the step-by-step workflow (data load, feature module, feature store, versioning
  exercise, lineage docs, tests, self-review), guardrails, and the validation checklist.
- `README.md` — this file.
- No `assets/` folder — this skill needs no templates, sample prompts, or reference
  diagrams beyond what `skill.md` already specifies.

## How Learners Should Use This

1. Invoke this skill's Stage 0 first, before `data_dictionary.md` exists at all: ask Claude
   to generate `data_dictionary.md` and a candidate-feature proposal directly from the raw
   sources. Treat the output as best-effort, not authoritative.
2. Read that generated output in full, on your own, and spot-check at least one claim in it
   against the actual data — with no help from Claude.
3. Correct `feature_spec.md` from Stage 0's proposal against `skill.md`'s Domain Context
   section (the standard for what a real candidate feature, parity design, versioning/
   lineage, multi-source judgment, and data-quality check need to look like) — a real
   review, not a rubber stamp, recording at least one thing you found wrong or
   under-justified in Stage 0's output — see `Helper Guide.docx`.
4. Reconcile your corrected spec with Claude in a separate conversation, without invoking this
   skill's build stage.
5. Only once `feature_spec.md` (and your corrected `data_dictionary.md`) are confirmed, invoke
   this skill's build stage (copy/symlink `skill.md` into
   `.claude/skills/churn-feature-pipeline/` in your own repo per the discovery note at the end
   of `skill.md`, or paste its contents directly) to build the pipeline, feature store,
   versioning exercise, quality checks, lineage docs, and tests in one run.
6. Spot-check the outputs yourself per `Helper Guide.docx` before treating the build as done.

## Evidence to Submit

Place all of the following in `outputs/artifacts/` in your submission zip:
- `FEATURE_LINEAGE.md`
- `VERSION_COMPARISON.md`
- `PARITY_CHECK.md`
- `ARTIFACT_NOTES.md`
- `review_log.md`
- Test run output/results (e.g. `pytest -v` output saved to a file, or a screenshot)
- Any spot-check evidence (e.g. the feature-store registry query output) referenced in
  `Evaluation Rubric.xlsx`

## Notes for Evaluators

- Confirm `feature_spec.md` reflects the learner's own judgment before the build, not a
  Claude-authored draft rubber-stamped after the fact.
- Confirm every version of every feature the learner's `feature_spec.md` designates as
  versioned is present, independently retrievable, and that `VERSION_COMPARISON.md` states a
  real, interpreted difference for each — not just "the values changed."
- Confirm `PARITY_CHECK.md` describes (or the learner reproduced) the parity-mutation check
  actually catching a deliberately introduced training/scoring divergence.
- Confirm `FEATURE_LINEAGE.md` justifies the multi-source (transactions.db vs.
  transactions_monthly_agg.parquet) choice per feature, not just stating it.
