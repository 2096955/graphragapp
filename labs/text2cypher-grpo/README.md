# Text-to-Cypher with GRPO

Train a small open model to write Cypher for a knowledge graph, using the graph itself as the reward. Each generated query is run against the graph and scored on what it returns.

## What is in this folder

| File | Purpose |
|---|---|
| `text2cypher_grpo.ipynb` | The lab: build the graph, measure a base model, train with GRPO, measure again. |
| `graphlab.py` | Schema, synthetic graph, question templates, reward and evaluation. Runs on any CPU. |
| `build_notebook.py` | Generates the notebook. Edit cells here rather than in the `.ipynb`. |
| `requirements.txt` | Pinned versions for the CPU parts. |

## Running it

- **Sections 1 and 2 and the reward checker** run on a laptop: `pip install -r requirements.txt`.
- **Training** needs Linux with an NVIDIA GPU, because fast generation uses vLLM. A free Colab T4 works at a small batch size; a 24 GB card is comfortable. Start with `max_steps=100` to check the loop before a longer run.

## How the test is built

| Split | Contents | Tests |
|---|---|---|
| `train` | 8 one-hop templates on 80% of entities, capped at 25 per template | |
| `test_seen` | Same templates, the held-out 20% of entities | Generalising to new names |
| `test_unseen` | 2 two-hop templates never trained on | Composing hops, not copying patterns |

## The reward

| Score | When |
|---|---|
| 1.0 | Exactly the reference rows (order and column names ignored) |
| 0.3 to 0.7 | Runs, wrong rows; partial credit by overlap |
| 0.1 | Fails to run or times out (2 seconds) |
| 0.0 | No query found |
| -1.0 | Attempts a write or procedure call. Blocked before execution. |

The database is opened read-only as a second line of defence.

## What has and has not been tested

- **Tested on CPU:** graph build, task generation and split (no test entity appears in training), every reference query scores 1.0, each reward tier, the timeout, the evaluation harness, and the reward function with completions in the format TRL passes.
- **Checked against source:** every `GRPOConfig` field used exists in TRL 0.24.0, the highest version Unsloth 2026.9.12 allows.
- **Not yet run:** the GPU training cells. Expect to adjust batch size and `gpu_memory_utilization` for your card. Record the before and after numbers here once run.

## Caveats

- **Licensing:** this uses the Unsloth library (Apache 2.0), not Unsloth Studio (AGPL-3.0). Check with legal before adding AGPL components to client work.
- **Kuzu:** upstream is archived at 0.11.3. That is fine for a throwaway lab graph. For anything kept, use a maintained fork or swap `run()` in `graphlab.py` for another engine's client.
- **Synthetic data:** templated questions are easier than real ones. Treat results as evidence the method works, not as an accuracy figure for a client schema.
- **Vendor claims:** Unsloth's speed and memory figures are its own. Log time and memory for each run.
