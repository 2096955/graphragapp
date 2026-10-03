# Version 1.2.0

## Production hardening

- Added an explicit production profile. Startup now refuses to continue without
  API_TOKEN. A random COMPLIANCE_HASH_KEY of at least 32 characters is required
  only when ENABLE_COMPLIANCE=true (defaults off in production).
- Replaced plain SHA-256 compliance identifiers with server-keyed HMAC-SHA256
  pseudonymous identifiers.
- Made configured compliance Kuzu storage persistent across process restarts;
  opening an existing store no longer deletes it.
- Disabled benchmark execution, the destructive compliance demo, and interactive
  API docs by default in production.
- Made hosted compliance default-deny unless ALLOW_HOSTED_COMPLIANCE=true is set
  after an explicit data-residency review.
- Protected internal graph, eval, result, test-set, and eval-status reads with the
  configured bearer token.
- Split request schemas and HTTP security out of app.main so the serving boundary
  is easier to review and modify.
- Added /api/ready, a hardened production Docker profile, CI, Dependabot,
  SECURITY.md, PRODUCTION.md, and production regression tests.
- CI validates Python compilation, the full pytest suite, and a production
  container build with local model dependencies disabled.
- GitHub Actions dependencies are pinned by immutable commit SHA.

## Verification

- 96 automated tests passed on Python 3.11 in GitHub Actions.
- The production Docker image built successfully with LOCAL_MODELS=false.
- Production-secret validation, HMAC key separation, compliance-store reopen,
  internal-read authentication, and demo-disable behaviour are covered by
  regression tests.

---

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
