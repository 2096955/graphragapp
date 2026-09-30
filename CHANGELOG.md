# Version 1.2.0

Reviewed the 1.1.0 patch, kept most of it, fixed what it got wrong, ran the benchmark again, and
had the write-up checked against the data by a separate reviewer, which led to the statistics
changes below.

## Kept from 1.1.0

- Calibration and thresholds split by request, not by decision.
- A fresh AnyJev decider for each benchmark run. Its L0 prior carries over between calls, so
  live traffic would otherwise leak into a benchmark.
- Named places, sectors and dates carried through discovery; every named member must be covered,
  also after roll-up.
- The review outcome, per-model calibration files tied to exact questions, the stricter Laya
  install check, and failed decisions counted in coverage.

## Changed

- **The request parser no longer overrides the model.** In 1.1.0 it decided before any model
  was asked, and ordinary wording ("I need", "a breakdown of", "for me", "over time", "I'd like")
  was sent back for clarification. It now stops a request only on catalogue facts (years,
  granularity or pollutants the catalogue does not hold, places or sectors it does not know) and
  on two breakdowns for one dimension, which one query cannot express. Forecasts and other kinds
  of pollution are left to the model's gate. Where the request names something in catalogue
  terms, that is used and a disagreeing model sends the result to review. Words the parser cannot
  place are listed for review. Everything else is the model's decision.
- **Review no longer stops the run once the gate says answer.** The result is complete, marked
  provisional, and lists the reasons. An unconfident gate that leans towards clarify or reject
  still stops the run for a person. "No data" is reported only when every decision behind the
  query was confident; otherwise the result goes to review.
- **Test-set entries removed from the parser**: the typos of the test requests ("contry", "yeer",
  "aanlyse") and "poem" and "world cup" from the reject set. A test that required the parser to
  reproduce every gate label is replaced by one that checks its stops never contradict a label.
- **Paper case 15 is labelled answer again**, as the paper answered it. 1.1.0 had relabelled it
  to match the parser. NO2, ozone and SF6 requested alongside held pollutants are now named in
  the result.
- **The group question no longer contradicts its labels.** It said "a mention of emissions alone
  does not include every group" while "air emissions" is labelled as all pollutants.
- **Laya's default is back to its own default checkpoint, english.** Typed-decisions is a
  separate backend, `laya-typed`. Laya's code says that checkpoint is tuned on four other
  workflows and "should not be a silent default".
- **New statistics** (`app/stats.py`):
  - 95% intervals for accuracy that resample whole requests, sources and name pairs.
  - Coverage and error at 1, 2, 5 and 10% target error, with thresholds chosen per task on
    other requests, averaged over 50 random splits and reported with the range across splits.
    A single split can be lucky: on the first split tried, Laya typed-decisions looked close to
    its 5% target (5.7%); over 50 splits it averages 8.7%.
  - Calibration error measured within each task and weighted by task size. Pooling tasks first
    let over- and under-confidence cancel (Laya: 0.040 pooled, 0.100 per task).
  - The most-common-answer baseline per task.
- Saved runs are rescored against the current labels, and the page, recorded or connected to a
  server, shows only runs that asked every current question.
- The four run files had been labelled `pipeline_version: 1.1.0` by the 1.1.0 save code. That
  label is removed: each decision records the hash of the question it was asked, and that decides
  whether a run is current.
- `.env.example` comments moved to their own lines: `docker run --env-file` does not strip a
  comment after a value.

## Results

- Fresh CPU runs of Laya (english), Laya (typed-decisions), AnyJev (Qwen3-1.7B, L0) and the
  uniform reference on all 584 decisions, and recorded pipeline examples for each model and for
  the catalogue rules.
- The Laya and AnyJev runs reproduce the 1.0 runs exactly on the 448 decisions they share.
- The 1.0 results are kept in `results/legacy/`.

## Verification

- 89 automated tests pass. No model weights or network are needed for them.
- The page was checked in Chromium at 1280 and 390 pixels wide, light and dark: no script errors
  and no horizontal overflow.
- Not run: Jev (needs an API key), the Docker build, a GPU, and AnyJev models larger than
  Qwen3-1.7B (they need more than the 7 GB of memory available).

# Version 1.1.0

## Worked example: compliance filter

- Added a legal/compliance agent in front of a downstream research agent. Jev (or
  Catalogue rules with no keys) answers one typed question: release, redact, or block.
- The knowledge graph records each decision. A repeated email or circumvention
  increments the pattern node, so the repeat is graph state, not a one-off score.
- Two hops from the matched pattern reach prior attempts, the filter decision, and
  both agents. The lab shows the cited Watts–Strogatz visual (N=500, K=25, p=0.15,
  seed 1): path 2.06, clustering 0.464, 75% of nodes in two hops. Retrieval is
  bounded by tokens or rank, not hop count. Watts & Strogatz (1998) and the
  MathWorks small-world demo are cited.
- Arize is the eval and cost view. Space name AzureDev. Send traces with
  `register(space_id, api_key, project_name=...)` or OTLP. Live export runs only
  when `ARIZE_SPACE_ID`, `ARIZE_API_KEY` and `ARIZE_PROJECT_NAME` are set. A key
  named graph-demo must not be committed. Without credentials the example still
  runs and shows the sample fixture. Catalogue mode costs $0.
- TypeSafe Jev stays optional behind `TYPESAFE_API_KEY`. No secrets or `.env` files
  are in the repository.

## Application Corrections

- Added a working Catalogue rules backend that needs no model weights or API key.
- Restricted group expansion to explicitly requested groups; model outputs cannot silently
  add or omit explicitly named pollutants. Unknown terms need clarification.
- Preserved named place, sector and date constraints through source selection, profiles and
  ranking. Filters apply before roll-up; every named member must be covered.
- Added review outcomes for weak or conflicting decisions and unsupported preferences.
  Source-update recency uses the oldest constituent source of a join.
- Added frozen per-task serving calibration tied to the exact model and question signature.
  Missing signatures or absent acceptance thresholds require review. Without an artifact,
  MIN_CONFIDENCE is an explicitly heuristic fallback, not a validated risk guarantee.
- Defaulted Laya to typed-decisions. AnyJev accepts raw/L0 only; fresh benchmark deciders
  isolate their running priors from live traffic. Laya availability checks its inference
  runtime so a source-only or incomplete install is not advertised as ready.
- Expanded the benchmark to 584 decisions in seven tasks, including 128 group and eight
  preference decisions. P15 now clarifies its unheld NO2 component. Historical gold labels
  and results are retained, clearly marked as legacy.
- Used request/source-grouped calibration and held-out threshold reporting; corrected
  temperature metadata and raw coverage denominators. No production risk guarantee is claimed.
- Updated recorded examples and the page; added filters, review states and empty-scope handling.

## Verification

- 72 automated tests passed, independently rerun by GPT-6 Sol.
- Chromium checks passed at 1280x900 and 390x844: live constrained answers, clarification,
  review, new task scopes and the typed-question playground. No JavaScript errors or
  horizontal overflow were observed.
- Fresh Laya/AnyJev inference, the paid Jev API, GPU execution and Docker builds were not run.
  Docker is not installed in the validation environment.

## Start Without Model Weights

From this directory, with Python 3.11 or newer:

```bash
python -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Open http://localhost:8000/ and choose Catalogue rules. Try `Annual CO2 for Australia in 2024`.
See README.md for optional models, authentication and calibration setup.
