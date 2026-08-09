# PR-Ready

An agent that reads your real data catalog (DataHub) before writing data
pipeline code so the code it generates references tables and columns
that actually exist, instead of guessing.

Built for DataHub's Agent Hackathon (Aug 2026).

## The idea in one sentence

You describe what you want ("join customers to their support tickets"),
the agent looks up the *real* schema in DataHub, writes a dbt model,
double-checks its own work against that schema, and only then saves/opens
a PR.

## How it works (read this before touching code)

```
your request
     |
     v
[schema_agent]   asks DataHub: what tables exist? what are their exact
                 columns? how do they relate? (this is "grounding" 
                 giving the LLM facts instead of letting it guess)
     |
     v
[codegen]        writes SQL using ONLY the columns schema_agent found
     |
     v
[validator]      a second LLM call re-reads the SQL and checks: did
                 codegen invent anything that isn't in the real schema?
     |
   invalid? -----> back to [codegen] with the specific error, retry (x3)
     |
   valid
     |
     v
[pr_writer]      saves the file, or opens a real GitHub PR if you've
                 set GITHUB_TOKEN
     |
     v
[write_back]     annotates the DataHub table(s) we actually used with a
                 note + link back to the PR  so the catalog itself now
                 shows "a model was generated from this table." This is
                 what makes it a two-way agent, not just a reader.
```

This "generate → verify against ground truth → retry" loop is the whole
point of the project, and it's also the most demo-able moment: you can
literally show the validator catching a hallucinated column and the
agent fixing it.

## Setup

### 1. Install Python deps
```bash
pip install -r requirements.txt
```

### 2. Copy the env file
```bash
cp .env.example .env
```
Add your `ANTHROPIC_API_KEY`. Leave `USE_MOCK_DATAHUB=true` for now —
this lets us build and demo the whole pipeline today, using the sample
schema in `src/mock_schema.json`, with zero DataHub setup.

### 3. Run it against mock data

Command line version:
```bash
python main.py "join customers to their support ticket history"
```
You should see: what the agent found in the (fake) catalog → the
generated SQL → confirmation it validated.

Visual version (this is what you'll actually demo/record):
```bash
streamlit run app.py
```
Opens a browser UI. Type a request, hit "Build it", and watch the live
trace on the left (schema lookup → codegen → validation, including any
retry if the validator catches a bad column) with the generated SQL and
final PR link on the right. This is the moment to screen-record for the
submission video.

### 4. When you're ready for the real DataHub (do this once mock mode works end-to-end)

Install Docker Desktop if you don't have it, then:
```bash
python3 -m pip install --upgrade acryl-datahub
datahub docker quickstart
# wait a few minutes, then check http://localhost:9002 (login: datahub / datahub)
```
This spins up a real DataHub instance with the UI, backend, and search index.

Then ingest some sample data so there's something to query  DataHub's
quickstart docs / the hackathon's Resources tab has sample datasets you
can load with `datahub ingest -c <config>.yml`.

Node.js is required too (the DataHub MCP server runs via `npx`):
check with `node --version`; install from nodejs.org if missing.

Finally, flip the switch in `.env`:
```
USE_MOCK_DATAHUB=false
DATAHUB_GMS_URL=http://localhost:8080
```
Re-run the same `python main.py "..."` command — same code, real data.

### 5. (Optional, for the demo) Open real PRs
Create a public GitHub repo (any starter repo works — even an empty one
with a `models/` folder). Generate a
[GitHub token](https://github.com/settings/tokens) with `repo` scope, set
`GITHUB_TOKEN` and `GITHUB_REPO=yourname/your-repo` in `.env`. Now
`pr_writer` opens a real pull request instead of just saving a local file.


## Example requests to try

The demo data is DataHub's built-in `showcase-ecommerce` sample pack — an
order-entry system with customers, orders, order_items, products,
product_categories, warehouses, and promotions. These requests are
confirmed to work end-to-end against that real data (each one opens a
genuinely new PR — branches are timestamped, so run any of these as many
times as you like):

- `summarize order_items revenue by product category`
- `summarize the orders table: total order value and average delivery cost, grouped by delivery type`
- `total orders and average order value by order status`
- `join orders to warehouses to see order volume by warehouse`
- `join orders to promotions to see how many orders used a promotion`


## Project structure
```
pr-ready/
├── main.py              # run this
├── requirements.txt
├── .env.example
├── src/
│   ├── graph.py          # the LangGraph agent — the heart of the project
│   ├── datahub_client.py # mock vs real DataHub tools, swapped via .env
│   └── mock_schema.json  # fake schema for building without DataHub
└── examples/
    └── generated_model.sql   # gets created when you run it
```

## What to learn as we build (don't skip this — it's the point)

- **Tools / function calling**: an LLM can't "do" anything by itself — it
  can only write text. A "tool" is just a normal Python function we hand
  to the LLM along with a description; the LLM decides *when* to call it,
  we just run it and hand back the result as text. `search_tables`,
  `get_table_schema`, `get_lineage` in `datahub_client.py` are exactly this.
- **MCP**: a standard way of packaging tools so any AI app (Claude
  Desktop, Cursor, your own agent) can plug into any data source without
  custom glue code each time. We use `langchain-mcp-adapters` to turn
  DataHub's MCP tools into normal LangChain tools with one function call.
- **LangGraph**: instead of one giant prompt, we break the job into
  small steps (nodes) with clear inputs/outputs, wired together as a
  graph. This makes each step debuggable in isolation and lets us add a
  retry loop (validator → codegen) that a single prompt couldn't do.
- **Grounding / retrieval-augmented generation**: the core trick behind
  reducing hallucination  look up facts *before* generating, instead of
  trusting the model's memory.

