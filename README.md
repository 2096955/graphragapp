# Graphs for agent context

A field guide to graph databases for agent context, and a working lab that pairs a knowledge
graph with small typed decision models. Read the findings, run the lab with no keys, then point
it at your own data.

![One request through the lab: the model's probabilities for each call, and the part of the graph it used](docs/images/lab-pipeline.png)

## The argument

Agents make many small calls: can this request be answered, which entity does this name mean,
does this payload hold personal data, how well does this dataset fit. Three things follow.

1. **A graph holds the facts and proposes the candidates.** Retrieval starts at the entities in
   the question and follows relationships, instead of matching text. In a small-world graph two
   hops can reach most of the graph, so hop count does not bound context: retrieval has to stop
   on a token budget or a ranking.
2. **A small typed decision model makes each call.** It answers a fixed question (yes or no, a
   choice, or a score) with a probability for every permitted answer, and never writes free text,
   so code always gets an answer it expects. TypeSafe Jev works this way, and so do the open
   models measured here, Laya and AnyJev.
3. **A threshold decides what runs without a person.** That only works if the probabilities mean
   what they say, so thresholds are chosen per task on some requests and checked on others.
   Everything below the threshold goes to a person, and what people decide becomes the labels
   for the next threshold.

```mermaid
flowchart LR
  G[(Knowledge graph)] -- "candidates within<br/>a token budget" --> D{"Typed decision:<br/>probability per answer"}
  D -- "above the task's<br/>threshold" --> A[Act]
  D -- "below it" --> P[Person reviews]
  A --> L[(Decision log)]
  P --> L
  L -- "labels" --> C["Thresholds chosen on<br/>held-out requests"]
  C -.-> D
```

The lab tests this with open models on a synthetic catalogue. Some calls come close to running
unattended; most do not yet; and a threshold chosen on the same labels it is scored on looks
at least twice as safe as it is.

## Start here

| To | Go to | Time |
|---|---|---|
| Read | [The field guide in brief](#the-field-guide-in-brief) and [what the lab found](#what-the-lab-found) | 10 minutes |
| Run the lab, no keys | [![Open in GitHub Codespaces](https://github.com/codespaces/badge.svg)](https://codespaces.new/2096955/graphragapp) or [run it locally](#run-it) | 5 minutes |
| Use it on your own data | [Adapt it](#adapt-it-to-your-own-graph) | A day or two |

## The field guide in brief

[`web/field-guide.html`](web/field-guide.html) compares nine graph engines for agent context and
grades each against the job it is built for: a shared production service, or embedded
per-session memory. Weights: traversal depth 30%, operations 25%, total cost 20%, vendor
viability 15%, fit for decision-model state 10%. Grades are judgement against those weights, not
measurement. Prices are USD list prices as at 25 September 2026.

![Grades by job](docs/images/field-guide-grades.png)

| Engine | Kind | Grade | Entry cost a month (USD) | Priced as |
|---|---|---|---|---|
| Neo4j | Native graph | A- shared | 4,670 | Business Critical, 32 GB |
| FalkorDB | Native graph | B+ shared, B embedded | 350 | Pro, 8 GB with HA |
| Amazon Neptune | Native graph | B shared | 460 | Two db.r6g.large, before storage and I/O |
| Spanner Graph | Graph over existing data | B shared | 120 to 1,200 | Enterprise edition, 0.1 to 1 node |
| PuppyGraph | Graph over existing data | B shared (provisional) | Quote only | Server CPU and memory |
| Fabric graph | Graph over existing data | C+ shared | 1,300 | Always on, pay-as-you-go estimate |
| MongoDB Atlas | Document store | C shared | 394 | M30 cluster |
| Cosmos DB Gremlin | Document store | D shared | Varies | Throughput-based |
| Kuzu forks | Embedded | B- embedded | No licence fee | Your own compute |
| Kuzu 0.11.3 | Embedded | C embedded | No licence fee | Archived October 2025; pin only for existing use |

![Entry production cost](docs/images/field-guide-cost.png)

Duplication and sync costs for native stores are not included, and are often the larger number.

<details>
<summary>Scores by criterion</summary>

![Scores by criterion, 0 to 5](docs/images/field-guide-criteria.png)

</details>

### Built-in graph algorithms

Lab 2 in the field guide ranks context with personalised PageRank (PageRank seeded from the
entities in the question) and packs the top-ranked facts into a token budget. Few engines ship
that built in. Checked against vendor documentation on 30 September 2026:

| Engine | Personalised PageRank | Other built-in algorithms | Vector search |
|---|---|---|---|
| Neo4j ([Graph Data Science](https://neo4j.com/docs/graph-data-science/current/algorithms/page-rank/)) | Yes (`sourceNodes`) | PageRank, Louvain, Leiden, label propagation, connected components, Dijkstra, A*, Yen, betweenness, closeness, node similarity, KNN, FastRP, GraphSAGE, Node2Vec | Yes |
| Neptune Analytics ([`neptune.algo`](https://docs.aws.amazon.com/neptune-analytics/latest/userguide/algorithms.html)) | Yes (`sourceNodes`) | PageRank, Louvain, label propagation, connected components, BFS, shortest paths, degree, closeness, Jaccard | Yes |
| Neptune Database | No | None | No |
| Spanner Graph ([algorithms](https://docs.cloud.google.com/spanner/docs/graph/algorithms)) | Yes (`source_nodes`), Preview | PageRank, betweenness, closeness, connected components, modularity clustering, label propagation, similarity, shortest path. Preview, Enterprise editions, run as batch jobs whose results are exported | Yes |
| FalkorDB ([`algo.*`](https://docs.falkordb.com/algorithms/)) | No seed option documented | PageRank, label propagation, connected components, BFS, shortest paths, A*, betweenness, harmonic centrality, spanning forest, max flow | Yes |
| PuppyGraph ([algorithms](https://docs.puppygraph.com/graph-algorithms/)) | Not documented | PageRank, Louvain, Leiden, label propagation, connected components, shortest paths | Not documented |
| Fabric graph | Not documented | GQL shortest path; no algorithm reference found | No |
| MongoDB Atlas | No | `$graphLookup` recursion only | Yes |
| Cosmos DB Gremlin | No | Gremlin traversals only | No |
| Kuzu 0.11.3 and its forks ([`algo`](https://kuzudb.github.io/docs/extensions/algo/)) | No | PageRank, Louvain, k-core, connected components; Cypher shortest paths | Yes |

Where it is missing, compute personalised PageRank in application code on the subgraph you
retrieved, as the field guide's Lab 2 does. For per-request retrieval, Spanner Graph's batch-only
algorithms do not help today.

### What else is in the field guide

![Tap a node in the field guide's example graph to see what an agent reaches in one, two or three hops](docs/images/field-guide-hops.gif)

- **Three labs that run in the browser**, each with editable code: keyword retrieval against
  graph retrieval; personalised PageRank into a token budget; and per-action thresholds under
  growing overconfidence.
- **One question in five dialects**: Cypher, Gremlin, GQL, MongoDB and Kuzu from Python.
- **Local run commands** for every engine that has a local option.
- Vendor claims (PuppyGraph and FalkorDB performance, Jev) are marked as vendor-reported.

## Pairing a graph with typed decisions

### Small calls, not free text

The lab re-implements the dataset-discovery method of Diamantini et al. (2026) over a two-layer
knowledge graph in Kuzu. The graph proposes candidates, expands groups, rolls levels up and finds
the minimal sets of sources that answer a request. A typed decision model makes each call the
request leaves open, every call is shown with its probabilities, and anything uncertain or
overruled goes to review. An optional LLM only writes the explanation; it never decides.

### Hop count does not bound context

![Rewiring a ring: two-hop reach from one node rises from 20% to 75% of the graph as edges are rewired](docs/images/small-world-rewire.gif)

In the 500-node Watts-Strogatz example (K = 25, rewiring probability 0.15), rewiring 1,912 of
12,500 edges takes two-hop reach from one node from 20% of the graph to 75%, while clustering only
falls from 0.735 to 0.464. At about 60 tokens a node, two hops are about 22,380 tokens, 70% of a
32,000-token budget, and three hops reach every node: about 29,940 tokens, leaving almost nothing
for the question. So cap retrieval by tokens and rank what comes back. The figures are a synthetic example, not a measurement of the lab's
catalogue graph; [`web/small-world.html`](web/small-world.html) reproduces MathWorks' published
results and lets you try other settings.

### Thresholds and review

![Moving the confidence threshold: how much is decided without a person, and how much of that is wrong](docs/images/lab-threshold.gif)

A single threshold such as 0.8 suits none of the models. AnyJev clears it on 78% of its decisions
and 37% of those are wrong; Laya clears it on 43% with 16% wrong; Laya typed-decisions understates
its confidence and clears it on 8%. Thresholds have to be chosen per task, on requests other than
the ones they are scored on.

![Stated confidence against actual accuracy, per model](docs/images/lab-calibration.png)

### Jev, Laya and AnyJev

| Model | What it is | Measured here |
|---|---|---|
| [TypeSafe Jev](https://typesafe.ai/blog/introducing-system-one-models-and-jev) | Commercial API, launched 15 September 2026. Answers typed questions with a probability per answer. TypeSafe says it is trained with reinforcement learning for calibrated decisions (RLCD) and prices input at $0.042 per million tokens, output free. | No: it needs an API key. The backend is built and uses Jev's request format, but nothing here tests TypeSafe's claims |
| [Laya](https://huggingface.co/convaiinnovations/laya) | Convai Innovations' open 421M-parameter decision model (Apache 2.0) that accepts Jev's request format. Two of its three checkpoints are measured: english (its default) and typed-decisions, fine-tuned on invoices, security incidents, customer service and agent traces | Yes, both checkpoints |
| [AnyJev](https://github.com/nokia-applied-research/AnyJev) | Nokia's training-free layer that turns an open LLM into a typed decision model (Apache 2.0); here Qwen3-1.7B at level L0 | Yes |
| Catalogue rules | Exact catalogue terms and no weights, so the lab runs with no model at all | Pipeline examples and the compliance check |

### Where reinforcement learning fits

- **Jev's training.** TypeSafe describes RLCD as rewarding the model for probabilities that
  match how often it is right. That is the vendor's description; this repository does not test
  it.
- **This lab does no reinforcement learning.** It measures calibration after the fact and fixes
  the scale with temperature scaling, which needs a few dozen labels per task.
- **The decision log is the raw material if you go further.** Each reviewed decision is a state,
  a typed question, the model's probabilities and a person's answer: what a calibration fit, a
  supervised fine-tune or an RL reward needs.
- **[`labs/text2cypher-grpo`](labs/text2cypher-grpo)** trains a small open model with GRPO to
  write Cypher, using the graph itself as the reward: each generated query is run and scored on
  the rows it returns. The graph, the reward and the evaluation are tested on CPU; the GPU
  training cells have not been run yet.

## What the lab found

584 hand-labelled decisions in seven tasks, from 62 requests, 8 sources and 82 name pairs (152
independent units). Run on 30 September 2026, CPU only. Held-out figures use thresholds chosen on
other requests, averaged over 50 splits. Full tables and method: [BENCHMARK.md](BENCHMARK.md).

| | Laya | Laya typed-decisions | AnyJev |
|---|---|---|---|
| Right on the labelled set (95% interval) | 72.8% (68% to 76%) | 74.5% (70% to 78%) | 60.4% (56% to 65%) |
| Calibration error per task, weighted (ECE) | 0.100 | 0.176 | 0.312 |
| The same after temperature scaling on other requests | 0.071 | 0.077 | 0.080 |
| Decided without a person at a 5% target, held out | 32.7% | 38.1% | 11.0% |
| Error among those (10th to 90th percentile across splits) | 9.5% (7% to 12%) | 8.7% (7% to 11%) | 14.9% (10% to 20%) |
| Median time per decision, CPU | 0.43 s | 0.43 s | 1.08 s |

- **No model holds a 5% error target on new requests.** Thresholds chosen on some requests let
  through about twice the target on others for Laya, three times for AnyJev. Chosen and scored on
  the same labels, the same thresholds look safe (Laya: 32% decided at 4.2% wrong).
- **Some calls come close.** Breakdown level with Laya typed-decisions: 82% decided at 6.4%
  wrong, held out. Column mapping with either Laya checkpoint: 54% to 57% decided at 7.5% to 8.0%
  wrong. Worth validating on your own requests, not switching on.
- **The first call cannot be automated.** On answer, clarify or reject, no model is clearly
  better than the 51% of always answering: both Laya checkpoints are at it, and AnyJev's 61% has
  an interval (48% to 72%) that includes it.
- **Out of the box, the confidence is off.** Temperature scaling on other requests brings all
  three models to a calibration error of 0.07 to 0.08, but never changes an answer.
- **Accuracy needs a baseline.** Laya's 91% on whole-group selection is below the 93% of always
  saying no.

![Decided without a person, by target error, held out](docs/images/lab-selective.png)

### What this means for a delivery team

1. Let the graph hold the facts and propose candidates, and let a typed model choose between
   them. Where the request already names something in catalogue terms, use that and check the
   model against it.
2. Choose a threshold per task on requests it was not chosen on, and check it again as labels
   come in. Report the held-out error, not the in-sample one.
3. Budget context in tokens and rank what comes back. In a small-world graph, a hop limit bounds
   nothing.
4. Log every decision with its probabilities and the reviewer's answer. That log is your
   evaluation set, your calibration set and, later, your training set.
5. Compare accuracy with always giving the most common answer before claiming anything.

## Worked example: a compliance filter

![The compliance example: a redacted first attempt, a blocked repeat, the pattern node and the labelled check](docs/images/lab-compliance.png)

A legal and compliance agent sits in front of a research agent and releases, redacts or blocks
each payload with one typed decision.

- **It fails closed.** A backend error blocks the payload, and so does a "redact" decision when
  the redactor finds nothing it can remove.
- **The graph remembers patterns, not payloads.** Kuzu stores a keyed pattern identity
  (HMAC-SHA256 with a server-side key, `COMPLIANCE_HASH_KEY`), the decision and the attempt count.
  A second attempt with the same address updates the same pattern node. Keyed hashes are
  pseudonymised personal data, not anonymous data.
- **Right and wrong come from 30 hand-labelled payloads**, written from the policy in
  [LABELLING.md](LABELLING.md) (section 8), not from the rules that make the catalogue decision.
  Payloads outside the set have no label, and the eval view does not count them.
- **Arize** receives each decision as an OTLP span when `ARIZE_SPACE_ID` and `ARIZE_API_KEY` are
  set (`ARIZE_PROJECT_NAME` names the project). Without them, the page shows local traces and a
  sample fixture.

| Backend | Right of 30 | Released when it should not have been | Decided at a 0.8 threshold, wrong among those |
|---|---|---|---|
| Catalogue rules | 19 | 9 | 30, 11 |
| Laya | 11 | 17 | 1, 1 |
| Laya typed-decisions | 12 | 17 | 0, 0 |
| AnyJev | 20 | 4 | 25, 7 |

None of these is a PII filter out of the box. The rules miss anything exact patterns cannot see.
Laya releases almost everything, but unsure of itself, so a threshold would send those payloads to
a person. AnyJev is right most often but sure of itself when wrong, so a threshold would not
catch its mistakes.

Not production: the filter acts on the top answer whatever its confidence and has no review
queue; the redactor knows e-mail addresses, SSN-shaped numbers and phone numbers only; there is
no retention policy for the decision graph; and the Arize export follows the OTLP/HTTP JSON
format but has not been tested against a live Arize space.

## The pages

| Page | Source | Served at | Hosted copy | What you can do |
|---|---|---|---|---|
| Decisions Lab | `web/template.html`, built into `web/index.html` | `/` | [claude.ai](https://claude.ai/artifact/DCNwze2sj8ua574gB5hHBs) | Step through the pipeline per model, benchmark charts, threshold picker, compliance example, playground |
| Field guide | `web/field-guide.html` | `/field-guide` | [claude.ai](https://claude.ai/artifact/UbBG78KRYTsNHMbgAoccDc) | Grades, costs, three browser labs, query snippets, local run commands |
| Small-world graphs | `web/small-world.html` | `/small-world` | [claude.ai](https://claude.ai/artifact/9xTMnwrzm1WHUKbSFJ7Vq2) | Rewire a ring, watch path length and reach, run the sweep, export the graph |

The pages also open straight from the `web` folder with no server, using recorded results, and
work on any static host. The hosted copies are private to their owner until shared from
claude.ai.

## Run it

No keys and no model weights are needed for the catalogue rules, the compliance example, the
small-world example and the recorded results.

```bash
python -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --port 8000
```

Open http://localhost:8000 and choose **Catalogue rules**. Try `Annual CO2 for Australia in
2024`, or press **Run the example (no keys)** in the compliance section.

In a Codespace the packages are installed and the server starts by itself; open the forwarded
port 8000.

To add the local models (about 0.8 GB per Laya checkpoint and 4 GB for Qwen3-1.7B, downloaded on
first use):

```bash
pip install torch==2.14.0 --index-url https://download.pytorch.org/whl/cpu
pip install -r requirements-local.txt
```

On CPU the service needs about 3 GB of memory with one Laya checkpoint loaded, about 6 GB with
Laya and AnyJev, and about 1.7 GB more for the second Laya checkpoint.

### Docker

```bash
docker build -t graphs-for-agent-context .
docker run -p 8000:8000 -e API_TOKEN=choose-a-token -v hf-cache:/cache graphs-for-agent-context
```

For a GPU image, build with `--build-arg TORCH_INDEX=https://download.pytorch.org/whl/cu126` and
run with `--gpus all -e DEVICE=cuda`. For a small image with no local models, build with
`--build-arg LOCAL_MODELS=false` and set `BACKENDS=catalogue,jev,uniform`.

### Tests

```bash
pip install -r requirements-dev.txt
pytest
```

No model weights, keys or network are needed.

### Configuration

All optional. [`.env.example`](.env.example) lists every variable with notes; use it with
`docker run --env-file .env`. Never commit a `.env` file or a key.

| Variable | Default | Purpose |
|---|---|---|
| `BACKENDS` | `laya,laya-typed,anyjev,jev,catalogue,uniform` | Which backends to build |
| `API_TOKEN` | none | Bearer token required on every POST; also switches on benchmark runs from the page |
| `ALLOWED_ORIGINS` | none | Browser origins allowed to call the API when the page is hosted elsewhere |
| `TYPESAFE_API_KEY` | none | Enables TypeSafe Jev. Stays on the server |
| `JEV_PRICE_PER_MTOK` | `0.042` | USD per million input tokens, for cost reporting |
| `DEVICE` | `cpu` | `cuda` on a GPU |
| `LAYA_CHECKPOINT` | `english` | Checkpoint for the `laya` backend; `laya-typed` is always typed-decisions |
| `ANYJEV_MODEL`, `ANYJEV_LEVEL` | `Qwen/Qwen3-1.7B`, `L0` | AnyJev's model and calibration level |
| `MIN_CONFIDENCE` | `0.8` | Below this, a decision sends the result to review. A rule of thumb, not a guarantee |
| `CALIBRATION_DIR` | `calibration` | Per-task temperatures and thresholds made by `scripts.fit_calibration` |
| `COMPLIANCE_HASH_KEY` | random per process | Key for the compliance pattern hashes. Set it so identities survive a restart |
| `ARIZE_SPACE_ID`, `ARIZE_API_KEY`, `ARIZE_PROJECT_NAME` | none, none, `graphrag-compliance` | Arize export for the compliance filter |
| `LLM_BASE_URL`, `LLM_MODEL`, `LLM_API_KEY` | none | Optional OpenAI-compatible endpoint for explanations |
| `PRELOAD` | `false` | Load local models at start-up |

### API

| Method | Path | What it does |
|---|---|---|
| GET | `/api/health` | Application and pipeline versions, graph size, which backends are available and why not |
| POST | `/api/decide` | One backend: `{backend, state, questions}` with questions in Jev's format |
| POST | `/api/compare` | The same typed question on up to four decision backends (not graph databases) |
| POST | `/api/pipeline` | `{backend, request, preference}` through the whole pipeline |
| GET | `/api/testset` | The 584 labelled items |
| GET | `/api/results` | Saved benchmark results, with every decision |
| POST | `/api/eval` | Start a benchmark run; poll `GET /api/eval/{id}` |
| POST | `/api/compliance/example` | The worked compliance example: first attempt and repeat |
| POST | `/api/compliance/filter` | One payload through the compliance filter |
| POST | `/api/compliance/check` | Score one backend on the 30 labelled payloads |
| GET | `/api/compliance/eval` | Arize eval and cost view, or the sample fixture |
| GET | `/api/compliance/graph` | Pattern, attempt and decision nodes |
| GET | `/api/watts-strogatz` | The small-world example with its sources |
| GET | `/api/docs` | Interactive documentation |

```bash
curl -s localhost:8000/api/decide -H "Content-Type: application/json" -d '{
  "backend": "catalogue",
  "state": {"request": "Annual CO2 for Australia in 2024"},
  "questions": {"gate": {"type": "choice", "instructions": "Can the catalogue answer this request?",
    "criteria": {"answer": null, "clarify": null, "reject": null}}}}'
```

### Hosting

- **Set `API_TOKEN`** on anything others can reach. Without it, anyone who can reach the server
  can run the models and spend a Jev budget.
- Put the service behind HTTPS.
- Run a single worker. Rate limits and benchmark jobs are kept in memory, and each worker would
  load its own copy of the models.
- Kuzu upstream is archived at 0.11.3. The graph is rebuilt in a temporary directory at every
  start, so nothing depends on its file format.

## Adapt it to your own graph

The lab is small enough to change in a day or two. In order:

1. **Describe your catalogue** in `app/domain.py`: the entities (here pollutants and groups of
   pollutants), the dimensions and their levels, and the sources with what each holds.
2. **Build the graph** in `app/graph.py`. It creates the Kuzu schema, loads the catalogue and
   answers the discovery queries: candidates, roll-ups and minimal source sets. The pipeline
   reaches the graph only through this file, so another engine means replacing this file.
3. **Write the typed questions** in `app/tasks.py`, in Jev's format: `noul` (yes or no),
   `choice` or `score`, each with instructions and criteria. The pipeline and the benchmark ask
   exactly these questions, so the benchmark describes the pipeline's own decisions.
4. **Label decisions by hand** in `app/testset.py`, against written rules like
   [LABELLING.md](LABELLING.md). Keep the request, source or pair each decision came from, so the
   statistics resample whole units. A few dozen decisions per task show whether confidence can
   be trusted; choosing thresholds you can defend takes a few hundred.
5. **Adjust the checks and the flow**: `app/request.py` matches what a request states in
   catalogue terms, and `app/pipeline.py` runs the stages and decides what goes to review.
6. **Measure**, then fit thresholds on your own labels:

   ```bash
   python -m scripts.run_benchmark --backend laya
   python -m scripts.fit_calibration results/laya.json --out calibration/laya.json
   python -m scripts.build_page
   ```

## Repository layout

```
app/
  domain.py            catalogue: pollutants, dimensions, synthetic sources
  graph.py             two-layer knowledge graph in Kuzu; discovery, roll-ups, member filters
  request.py           catalogue checks: named terms, levels, places, dates, what is not held
  tasks.py             the typed questions, shared by the pipeline and the benchmark
  pipeline.py          checks, gate, enrich, query, discover, rank, explain, review
  decisions/           one interface: Jev, Laya, AnyJev, catalogue rules, uniform
  evaluation.py        accuracy, calibration error, temperature scaling
  stats.py             intervals over whole requests; held-out coverage over many splits
  testset.py           the 584 labelled items
  compliance.py        worked example: compliance filter in front of another agent
  compliance_labels.py the 30 hand-labelled payloads
  compliance_graph.py  Kuzu store for filter decisions and repeated patterns
  watts_strogatz.py    the small-world example and its sources
  arize_eval.py        Arize export, or the sample fixture without credentials
  main.py              HTTP API and the three pages
scripts/               run_benchmark, record_examples, compliance_check, fit_calibration, build_page
results/               recorded runs; legacy/ holds the version 1.0 runs
web/                   template.html (edit this), index.html (built), field-guide.html, small-world.html
labs/text2cypher-grpo/ GRPO lab: train a small model to write Cypher, with the graph as the reward
docs/images/           screenshots and charts used in this README
tests/                 no model weights, keys or network needed
```

[CHANGELOG.md](CHANGELOG.md) lists what changed between versions.

## Credits

- The explain-it-by-building-it style follows Tivadar Danka's newsletter
  [The Palindrome](https://thepalindrome.org/). The animations, code and figures here are
  original.
- Pipeline and the 22 paper requests: Diamantini, Mele, Mircoli, Potena, Rossetti and Storti,
  "A Graph RAG Approach to Enhance Explainability in Dataset Discovery", *Data Science and
  Engineering* 11:30 to 52 (2026),
  [doi:10.1007/s41019-025-00313-x](https://doi.org/10.1007/s41019-025-00313-x), as re-implemented
  in [Syntran-Labs/paper-rag-graph-4-datasets](https://github.com/Syntran-Labs/paper-rag-graph-4-datasets) (MIT).
- D. J. Watts and S. H. Strogatz, "Collective dynamics of 'small-world' networks", *Nature* 393,
  440 to 442 (1998), [doi:10.1038/30918](https://doi.org/10.1038/30918). MathWorks,
  [Build Watts-Strogatz Small World Graph Model](https://www.mathworks.com/help/matlab/math/build-watts-strogatz-small-world-graph-model.html),
  used as the reference results.
- [Laya](https://huggingface.co/convaiinnovations/laya), Convai Innovations, Apache 2.0.
  [AnyJev](https://github.com/nokia-applied-research/AnyJev), Nokia, Apache 2.0, with
  [Qwen3-1.7B](https://huggingface.co/Qwen/Qwen3-1.7B), Apache 2.0.
  [TypeSafe Jev](https://docs.typesafe.ai/), commercial API; its request format is used here, and
  this project is not affiliated with TypeSafe. [Kuzu](https://kuzudb.github.io/), MIT, archived
  upstream.
- Written and maintained by Anthony Lui.

## Licence and data

- **No licence has been chosen yet.** Until one is added, the default is all rights reserved.
  Check your organisation's policy before adding one or sharing the code outside it.
- **All data is synthetic**: the catalogue, its sources and every number in it, and every name,
  address and identifier in the compliance payloads. E-mail addresses use the reserved `.test`
  domain.
