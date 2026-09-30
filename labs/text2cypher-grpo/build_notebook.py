"""Builds text2cypher_grpo.ipynb. Edit cells here, then run: python build_notebook.py"""
import nbformat as nbf

md, code = nbf.v4.new_markdown_cell, nbf.v4.new_code_cell
cells = [
md("""# Train a text-to-Cypher model with GRPO

A small open model learns to turn questions into Cypher queries for a knowledge graph. The reward comes from running each generated query against the graph and checking what it returns, so the model is rewarded for being right, not for resembling a reference query.

**You will**
1. Build a synthetic graph in Kuzu, an embedded engine that needs no server.
2. Measure a base model on questions it has never seen.
3. Train it with GRPO in Unsloth, using execution against the graph as the reward.
4. Measure it again, on new entities and on two-hop question types it was never trained on.

**Hardware.** The training cells need an NVIDIA GPU on Linux, because fast generation uses vLLM. A free Colab T4 runs the 4B model at a small batch size; a 24 GB card is comfortable. Sections 1 and 2 and the reward checker run on any laptop CPU.

**Licensing.** This uses the Unsloth library, which is Apache 2.0. It does not use Unsloth Studio, which is AGPL-3.0. Check with your legal team before introducing AGPL components into client work."""),

md("## 0. Install"),
code("""# Training environment (Linux + NVIDIA). On a CPU-only machine, install just: kuzu==0.11.3 datasets
%pip install -q unsloth vllm kuzu==0.11.3 datasets"""),

md("""## 1. Build the graph and the questions

`graphlab.py` holds everything that is not training: the schema, a seeded synthetic graph (invented names, no real people or firms), ten question templates with reference Cypher, and the reward.

The split is built to test generalisation, not memory:

| Split | What it contains | What it tests |
|---|---|---|
| `train` | 8 one-hop templates, 80% of entities, capped at 25 per template | |
| `test_seen` | Same templates, the other 20% of entities | Does it generalise to names it has not seen? |
| `test_unseen` | 2 two-hop templates never used in training | Does it learn to compose, or only to copy patterns? |

Kuzu upstream is archived at 0.11.3. That is fine for a disposable lab graph. For anything you keep, swap to a maintained fork or point `run()` at another engine."""),
code("""import collections
from graphlab import (make_graph_data, build_db, open_readonly, make_tasks, prompt_messages,
                      score, evaluate, print_report, SYSTEM_PROMPT)

DB_PATH = "lab_graph.kuzu"
data = make_graph_data(seed=7)
build_db(DB_PATH, data)
conn = open_readonly(DB_PATH)          # read-only, 2 second query timeout
tasks = make_tasks(conn, data)

print(collections.Counter(t.split for t in tasks))
for t in tasks[:3]:
    print(f"\\n{t.split}: {t.question}\\n  {t.gold_cypher}\\n  -> {t.gold_rows[:3]}")"""),

md("""### The reward

| Score | When |
|---|---|
| 1.0 | Returns exactly the reference rows (order and column names ignored) |
| 0.3 to 0.7 | Runs, but returns different rows; partial credit by overlap |
| 0.1 | A query was written but fails to run (including timeouts) |
| 0.0 | No ```cypher block found |
| -1.0 | Tries to write or call procedures. It is never executed. |

The graded middle matters. Early in training almost nothing is fully correct, and GRPO learns from differences between attempts at the same prompt. If every attempt scored 0 there would be nothing to learn from."""),
code("""t = tasks[0]
for attempt in [
    f"```cypher\\n{t.gold_cypher}\\n```",                  # correct
    "```cypher\\nMATCH (j:Project) RETURN j.name\\n```",   # runs, wrong rows
    "```cypher\\nMATCH (x:Nope) RETURN x\\n```",           # fails
    "The answer is probably Solar Kavo.",                 # no query
    "```cypher\\nMATCH (n) DETACH DELETE n\\n```",         # blocked
]:
    shown = attempt.replace("```cypher\\n", "").replace("\\n```", "")
    print(f"{score(attempt, t.gold_rows, conn)!s:22s} {shown[:70]}")"""),

md("""## 2. Load the model

Qwen3 4B Instruct is a good starting point: small enough for one GPU, and already able to write some Cypher. Other models Unsloth supports can be swapped in by changing `MODEL_NAME`."""),
code("""from unsloth import FastLanguageModel

MODEL_NAME = "unsloth/Qwen3-4B-Instruct-2507"
MAX_SEQ_LEN = 1024
LORA_RANK = 32

model, tokenizer = FastLanguageModel.from_pretrained(
    model_name=MODEL_NAME,
    max_seq_length=MAX_SEQ_LEN,
    load_in_4bit=True,            # set False on a large GPU for slightly better quality
    fast_inference=True,          # vLLM generation, which GRPO depends on for speed
    max_lora_rank=LORA_RANK,
    gpu_memory_utilization=0.6,   # lower this if you run out of memory
)
model = FastLanguageModel.get_peft_model(
    model,
    r=LORA_RANK,
    lora_alpha=LORA_RANK * 2,
    target_modules=["q_proj", "k_proj", "v_proj", "o_proj", "gate_proj", "up_proj", "down_proj"],
    use_gradient_checkpointing="unsloth",
    random_state=3407,
)"""),

md("""## 3. Baseline

`evaluate()` takes any function that maps prompts to completions. The same harness can score a hosted model, so you can compare the fine-tuned model with a frontier model on identical questions. Generation is greedy (temperature 0) so results are repeatable."""),
code("""from vllm import SamplingParams

greedy = SamplingParams(temperature=0.0, max_tokens=200)

def make_generator(lora_request=None):
    def generate(batch):
        texts = [tokenizer.apply_chat_template(m, tokenize=False, add_generation_prompt=True) for m in batch]
        outs = model.fast_generate(texts, sampling_params=greedy, lora_request=lora_request)
        return [o.outputs[0].text for o in outs]
    return generate

before = evaluate(make_generator(), tasks, conn)
print_report("Base model", before)
for q, out, why in before["test_seen"]["examples"][:3]:
    print(f"\\n[{why}] {q}\\n{out}")"""),

md("""## 4. Train with GRPO

For each question, GRPO samples several queries, runs them all, and pushes the model towards the ones that scored above the group's average. Each prompt carries only a `task_id`; the reward function looks up the reference rows, so nothing has to survive conversion into a dataset table.

Start with `max_steps=100` to check the loop works, then run longer. Watch the `reward` column in the log: it should climb, and `reward_std` should stay above zero. If the standard deviation hits zero, every attempt at a prompt is scoring the same and the model has stopped learning from it."""),
code("""from datasets import Dataset
from trl import GRPOConfig, GRPOTrainer

train = [t for t in tasks if t.split == "train"]
train_ds = Dataset.from_list([{"prompt": prompt_messages(t.question), "task_id": i} for i, t in enumerate(train)])
reasons = collections.Counter()

def execution_reward(prompts, completions, task_id, **kwargs):
    scores = []
    for completion, i in zip(completions, task_id):
        s, why = score(completion[0]["content"], train[i].gold_rows, conn)
        reasons[why] += 1
        scores.append(s)
    return scores

config = GRPOConfig(
    learning_rate=5e-6,
    lr_scheduler_type="cosine",
    warmup_ratio=0.1,
    optim="adamw_8bit",
    per_device_train_batch_size=4,
    gradient_accumulation_steps=1,
    num_generations=4,            # queries sampled per question; must divide the batch size
    max_prompt_length=512,
    max_completion_length=200,
    max_steps=300,
    logging_steps=5,
    save_steps=100,
    output_dir="outputs",
    report_to="none",
)
trainer = GRPOTrainer(model=model, processing_class=tokenizer, reward_funcs=[execution_reward],
                      args=config, train_dataset=train_ds)
trainer.train()
print("Outcomes during training:", dict(reasons))"""),

md("## 5. Measure again"),
code("""model.save_lora("text2cypher_lora")
after = evaluate(make_generator(model.load_lora("text2cypher_lora")), tasks, conn)
print_report("After GRPO", after)

print(f"\\n{'split':12s} {'before':>8s} {'after':>8s}")
for split in before:
    print(f"{split:12s} {before[split]['accuracy']:8.0%} {after[split]['accuracy']:8.0%}")
print("\\nBy template (test_seen):", after["test_seen"]["by_template"])
print("By template (test_unseen):", after["test_unseen"]["by_template"])"""),

md("""## 6. Reading the result

- **`test_seen` improves, `test_unseen` does not.** The model learned the eight trained patterns, not how to compose hops. Add a few two-hop templates to training and keep different ones held out.
- **Both improve.** The model is learning the schema and composing from it. This is the result worth reporting.
- **Accuracy rises but `write blocked` or `error` appear in training outcomes.** Read the failing completions before trusting the number.
- **Nothing moves.** Check that the base model already scores above zero. GRPO sharpens an existing ability; it cannot create one from scratch. If the baseline is near zero, do a short supervised fine-tune on the training pairs first.

Report the base model, the fine-tuned model and a frontier model on the same test splits, with cost and latency per query. A fine-tuned 4B model that matches a frontier model on your schema is a real saving. One that only matches it on seen templates is not.

## 7. Next steps

- **Another engine.** Replace `run()` in `graphlab.py` with a Neo4j or FalkorDB client. The reward and evaluation do not change.
- **A harder reward.** Add a small penalty for queries that return far more rows than needed. This is the same budget pressure as the small-world page.
- **Export.** `model.save_pretrained_merged("text2cypher_merged", tokenizer, save_method="merged_16bit")` produces a standalone model; Unsloth can also export GGUF for local serving."""),
]

nb = nbf.v4.new_notebook(cells=cells, metadata={
    "kernelspec": {"name": "python3", "display_name": "Python 3", "language": "python"},
    "language_info": {"name": "python"},
})
nbf.write(nb, "text2cypher_grpo.ipynb")
print("written", len(cells), "cells")
