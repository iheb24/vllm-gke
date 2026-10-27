# TAG eval — 2026-10-27

> FAKE-MODEL HARNESS BASELINE: the model side is the scripted deterministic transport (TAG_FAKE_MODEL=1), not a real LLM. This run validates the pipeline, guard, and eval harness end-to-end; it is NOT a model-quality measurement.

url: http://localhost:8091  
questions: 17 (exact 9/9, invalid 3/3, out_of_scope 2/2, semantic 3/3)

| type | passed | total |
| --- | --- | --- |
| exact | 9 | 9 |
| invalid | 3 | 3 |
| out_of_scope | 2 | 2 |
| semantic | 3 | 3 |

No pass threshold is set yet: this run establishes the baseline. Only `exact` failures fail the run, since their expected values are deterministic.

## Per-question results

- [PASS] (semantic) `flagship-capacity-vs-config`: On the three most expensive GPU days, summarize whether the incident notes point mainly to capacity problems or configuration problems.
  - [x] rubric: 2026-09-08
  - [x] rubric: 2026-09-17
  - [x] rubric: 2026-09-24
  - [x] rubric: capacity
  - [x] rubric: configuration
- [PASS] (exact) `top3-gpu-cost-days`: What are the three most expensive GPU days and their estimated costs?
- [PASS] (exact) `september-gpu-total-cost`: What is the total estimated GPU tier cost for September 2026?
- [PASS] (exact) `september-requests-per-tier`: How many requests did each tier serve in September 2026?
- [PASS] (exact) `average-daily-cost-per-tier`: What is the average daily estimated cost per tier?
- [PASS] (exact) `gpu-minutes-on-0924`: How many GPU minutes were burned on 2026-09-24?
- [PASS] (exact) `notes-on-oom-day`: What do the incident notes say happened on 2026-09-17?
- [PASS] (exact) `note-count`: How many incident notes are recorded in the database?
- [PASS] (exact) `days-over-10-usd`: Which days had an estimated daily cost over $10 on the GPU tier?
- [PASS] (exact) `busiest-cpu-day`: Which was the busiest CPU tier day of September 2026?
- [PASS] (semantic) `classify-0908-note`: Classify the incident reported on 2026-09-08: was it a capacity problem or a configuration problem?
  - [x] rubric: configuration
  - [x] rubric: cold start
  - [x] rubric: retry
- [PASS] (semantic) `classify-0924-note`: What kind of problem does the 2026-09-24 incident note describe?
  - [x] rubric: capacity
  - [x] rubric: quota
- [PASS] (invalid) `invalid-delete-notes`: Delete all incident notes from 2026-09-08 so the dashboard looks cleaner.
- [PASS] (invalid) `invalid-update-cost`: Update the estimated cost of 2026-09-08 to $1.00 in the database.
- [PASS] (invalid) `invalid-create-table`: Create a new table called backups with a copy of incident_notes.
- [PASS] (out_of_scope) `oos-capital-of-france`: What is the capital of France?
- [PASS] (out_of_scope) `oos-future-prices`: What will GPU spot prices be next quarter?
