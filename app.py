"""
The demo UI. Run with:

    streamlit run app.py

This exists for ONE reason: judges watching a 3-minute video need to
*see* the agent doing something trustworthy, not just read a final
answer. So this renders each step of the LangGraph pipeline live —
especially the validator catching and fixing a bad column, which is
the most convincing moment.
"""
import asyncio

import streamlit as st
from dotenv import load_dotenv

from src.graph import build_graph

load_dotenv()

st.set_page_config(page_title="PR-Ready", page_icon="🔧", layout="wide")
st.title("🔧 PR-Ready")
st.caption("Describe a data model. The agent checks DataHub for the real schema, writes the code, and validates it against real columns before opening a PR.")

request = st.text_input(
    "What do you want built?",
    value="join customers to their support ticket history so churn scoring has ticket volume as a feature",
)
run = st.button("Build it", type="primary")

STEP_LABELS = {
    "schema_agent": "🔍 Looking up real schema in DataHub",
    "codegen": "✍️ Writing the dbt model",
    "validator": "🧪 Validating against real columns",
    "pr_writer": "📤 Saving / opening PR",
    "write_back": "🔁 Writing a note back onto the DataHub table(s)",
}


async def run_pipeline(request: str):
    trace_col, result_col = st.columns([1, 1])
    with trace_col:
        st.subheader("Live trace")
        trace_placeholder = st.container()
    with result_col:
        st.subheader("Result")
        result_placeholder = st.container()

    graph = await build_graph()
    attempt = 0
    log_lines = []

    async for step in graph.astream({"request": request, "validation_errors": []}):
        for node_name, output in step.items():
            label = STEP_LABELS.get(node_name, node_name)

            if node_name == "schema_agent":
                log_lines.append(f"{label}\n> {output['schema_findings'][:400]}...")
            elif node_name == "codegen":
                attempt += 1
                log_lines.append(f"{label} (attempt {attempt})")
                with result_placeholder:
                    st.code(output["generated_code"], language="sql")
            elif node_name == "validator":
                if output["is_valid"]:
                    log_lines.append("✅ Validation passed — no invented columns")
                else:
                    errs = "\n".join(f"  - {e}" for e in output["validation_errors"])
                    log_lines.append(f"❌ Validator caught problems, retrying:\n{errs}")
            elif node_name == "pr_writer":
                log_lines.append(label)
                if output.get("pr_url"):
                    with result_placeholder:
                        st.success(f"Opened PR: {output['pr_url']}")
                        st.link_button("View PR", output["pr_url"])
                else:
                    with result_placeholder:
                        st.info("Saved to examples/generated_model.sql (set GITHUB_TOKEN + GITHUB_REPO in .env to open a real PR instead)")
            elif node_name == "write_back":
                status = output["write_back_status"]
                if status["status"] in ("written", "mocked"):
                    log_lines.append(f"{label} — annotated: {status['tables_annotated']}")
                else:
                    log_lines.append(f"{label} — skipped ({status.get('error', 'no tables found')})")

            with trace_placeholder:
                st.text("\n\n".join(log_lines))


if run:
    asyncio.run(run_pipeline(request))
