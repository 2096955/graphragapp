# Version 1.1.0

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
