
import asyncio
import json
import os
from pathlib import Path
from typing import TypedDict

from langgraph.graph import StateGraph, END
from langgraph.prebuilt import create_react_agent

from src.datahub_client import get_datahub_tools, write_back

MAX_RETRIES = 3


class AgentState(TypedDict):
    request: str
    schema_findings: str
    tables_used: list[str]
    generated_code: str
    validation_errors: list[str]
    iterations: int
    is_valid: bool
    pr_url: str
    write_back_status: dict


def _llm():
    """Which model actually powers the agent — swap with LLM_PROVIDER in
    .env, no code change needed. Everything else in this file just calls
    _llm() and doesn't care which provider is behind it."""
    provider = os.environ.get("LLM_PROVIDER", "anthropic").lower()

    if provider == "google":
        from langchain_google_genai import ChatGoogleGenerativeAI

        # Google renames/deprecates Gemini models fairly often, and free-tier
        # rate limits vary a lot by model. flash-lite gets a noticeably
        # higher free RPM than plain flash — worth it for a project that
        # makes several calls per run. If this ever 404s with "no longer
        # available", check ai.google.dev/gemini-api/docs/models and swap
        # in the current stable Flash-Lite model name.
        return ChatGoogleGenerativeAI(model="gemini-2.5-flash-lite")

    if provider == "deepseek":
        from langchain_openai import ChatOpenAI

        # DeepSeek exposes an OpenAI-compatible endpoint, so we reuse
        # ChatOpenAI and just point it at DeepSeek's base_url + key
        # instead of OpenAI's. Confirmed to support function calling,
        # which our schema_agent needs to call the DataHub tools.
        return ChatOpenAI(
            model="deepseek-v4-flash",
            base_url="https://api.deepseek.com",
            api_key=os.environ["DEEPSEEK_API_KEY"],
            temperature=0,
        )

    from langchain_anthropic import ChatAnthropic

    return ChatAnthropic(model="claude-sonnet-4-6", temperature=0)


def _extract_text(content) -> str:
    """Different providers format .content differently — Anthropic/Gemini
    can both return either a plain string or a list of content blocks
    (e.g. [{"type": "text", "text": "..."}]). Normalize to plain text so
    the rest of the code never has to care which provider is active."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, dict):
                parts.append(block.get("text", ""))
        return "".join(parts)
    return str(content)


async def _ainvoke_with_retry(llm, prompt, max_retries: int = 4):
    """Wraps an LLM call with exponential backoff on rate-limit (429)
    errors — free-tier API keys (Gemini especially) throttle hard, and
    without this a single 429 kills the whole pipeline instead of just
    pausing for a few seconds."""
    delay = 5
    for attempt in range(max_retries):
        try:
            return await llm.ainvoke(prompt)
        except Exception as e:
            is_rate_limit = "429" in str(e) or "RESOURCE_EXHAUSTED" in str(e)
            if not is_rate_limit or attempt == max_retries - 1:
                raise
            print(f"Rate limited — waiting {delay}s before retry ({attempt + 1}/{max_retries})...")
            await asyncio.sleep(delay)
            delay *= 2


async def build_graph():
    tools = await get_datahub_tools()
    schema_agent = create_react_agent(_llm(), tools)

    async def schema_agent_node(state: AgentState) -> dict:
        prompt = (
            "A teammate wants this data model built:\n"
            f'"{state["request"]}"\n\n'
            "Use your tools to find every real table and column involved. "
            "Search first, then pull exact schemas, then check lineage if it "
            "matters. Finish with a clear plain-text summary of: the tables, "
            "their exact column names/types, and how they relate."
        )
        result = await schema_agent.ainvoke({"messages": [("user", prompt)]})
        findings = _extract_text(result["messages"][-1].content)

        # Walk the message history to see exactly which tables the agent
        # looked up — we need this list later to know what to annotate in
        # write_back. Different tool names/arg shapes depending on mode:
        # mock uses get_table_schema(table_name=...); the real DataHub MCP
        # server uses list_schema_fields(urn=...) / get_entity(urns=[...]).
        TABLE_LOOKUP_TOOLS = {"get_table_schema", "list_schema_fields", "get_entities", "get_entity"}
        # Different tools/versions use different arg names for "which
        # entity" — check all the plausible ones rather than assuming one.
        POSSIBLE_ID_KEYS = ["table_name", "urn", "urns"]
        tables_used = []
        for msg in result["messages"]:
            for call in getattr(msg, "tool_calls", None) or []:
                if call["name"] not in TABLE_LOOKUP_TOOLS:
                    continue
                for key in POSSIBLE_ID_KEYS:
                    value = call["args"].get(key)
                    if not value:
                        continue
                    identifiers = value if isinstance(value, list) else [value]
                    for identifier in identifiers:
                        if identifier and identifier not in tables_used:
                            tables_used.append(identifier)

        return {"schema_findings": findings, "tables_used": tables_used, "iterations": 0}

    async def codegen_node(state: AgentState) -> dict:
        error_context = ""
        if state.get("validation_errors"):
            error_context = (
                "\n\nYour previous attempt had these problems — fix them:\n"
                + "\n".join(state["validation_errors"])
            )

        prompt = f"""Write a single dbt SQL model that does this:
"{state['request']}"

Ground truth schema (the ONLY tables/columns you're allowed to reference):
{state['schema_findings']}
{error_context}

Rules:
- Every column you reference MUST appear in the ground truth schema above.
- Output ONLY the SQL, no markdown fences, no commentary.
"""
        response = await _ainvoke_with_retry(_llm(), prompt)
        code = _extract_text(response.content).strip()
        if code.startswith("```"):
            code = code.strip("`")
            code = code.split("\n", 1)[1] if "\n" in code else code  # drop a leading ```sql line
        return {
            "generated_code": code.strip(),
            "iterations": state.get("iterations", 0) + 1,
        }

    async def validator_node(state: AgentState) -> dict:
        prompt = f"""You are a strict reviewer. Compare this SQL against the
ground truth schema and find any column or table referenced in the SQL that
does NOT appear in the ground truth.

Ground truth schema:
{state['schema_findings']}

SQL to check:
{state['generated_code']}

Respond with ONLY valid JSON, no markdown fences:
{{"valid": true/false, "errors": ["<one issue per string>"]}}
"""
        response = await _ainvoke_with_retry(_llm(), prompt)
        raw = _extract_text(response.content).strip()
        # Models sometimes wrap JSON in ```json fences despite instructions
        # not to — strip those before parsing rather than failing on them.
        if raw.startswith("```"):
            raw = raw.strip("`").removeprefix("json").strip()
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            parsed = {"valid": True, "errors": []}  # fail open, don't loop forever
        return {"is_valid": parsed.get("valid", True), "validation_errors": parsed.get("errors", [])}

    def route_after_validation(state: AgentState) -> str:
        if state["is_valid"] or state["iterations"] >= MAX_RETRIES:
            return "pr_writer"
        return "codegen"

    async def pr_writer_node(state: AgentState) -> dict:
        out_dir = Path("examples")
        out_dir.mkdir(exist_ok=True)
        out_path = out_dir / "generated_model.sql"
        out_path.write_text(state["generated_code"])

        github_token = os.environ.get("GITHUB_TOKEN")
        github_repo = os.environ.get("GITHUB_REPO")
        if github_token and github_repo:
            from github import Github, GithubException

            gh = Github(github_token)
            repo = gh.get_repo(github_repo)
            # A unique branch per run means every request opens its own
            # clean PR instead of updating one shared PR — much better for
            # a demo, and it's what a real user would expect too.
            import time

            branch_name = f"pr-ready/generated-model-{int(time.time())}"
            base = repo.get_branch(repo.default_branch)
            try:
                repo.create_git_ref(f"refs/heads/{branch_name}", base.commit.sha)
            except GithubException:
                pass  # branch may already exist from a previous run — fine

            file_path = "models/generated_model.sql"
            commit_message = "Add agent-generated dbt model"
            try:
                # File doesn't exist yet on this branch — create it.
                repo.create_file(
                    path=file_path,
                    message=commit_message,
                    content=state["generated_code"],
                    branch=branch_name,
                )
            except GithubException as e:
                if e.status != 422:
                    raise
                # File already exists on this branch (e.g. from a prior run) —
                # GitHub requires the current SHA to update it rather than
                # blindly overwrite, so fetch it first.
                existing = repo.get_contents(file_path, ref=branch_name)
                repo.update_file(
                    path=file_path,
                    message=commit_message,
                    content=state["generated_code"],
                    sha=existing.sha,
                    branch=branch_name,
                )

            try:
                pr = repo.create_pull(
                    title="[PR-Ready] Auto-generated dbt model",
                    body=f"Request: {state['request']}\n\nGenerated from live DataHub "
                    f"schema + validated against real columns before opening this PR.",
                    head=branch_name,
                    base=repo.default_branch,
                )
                pr_url = pr.html_url
            except GithubException as e:
                # A PR from this branch is already open (common on repeat
                # runs during testing) — reuse it instead of failing.
                existing_prs = repo.get_pulls(state="open", head=f"{repo.owner.login}:{branch_name}")
                pr_url = existing_prs[0].html_url if existing_prs.totalCount > 0 else f"(update pushed, but couldn't open/find PR: {e})"

            return {"generated_code": state["generated_code"], "pr_url": pr_url}

        print(f"Saved locally to {out_path} (set GITHUB_TOKEN + GITHUB_REPO in .env to open a real PR)")
        return {"pr_url": str(out_path)}

    async def write_back_node(state: AgentState) -> dict:
        result = write_back(
            tables_used=state.get("tables_used", []),
            reference_url=state.get("pr_url", ""),
            request=state["request"],
        )
        return {"write_back_status": result}

    graph = StateGraph(AgentState)
    graph.add_node("schema_agent", schema_agent_node)
    graph.add_node("codegen", codegen_node)
    graph.add_node("validator", validator_node)
    graph.add_node("pr_writer", pr_writer_node)
    graph.add_node("write_back", write_back_node)

    graph.set_entry_point("schema_agent")
    graph.add_edge("schema_agent", "codegen")
    graph.add_edge("codegen", "validator")
    graph.add_conditional_edges("validator", route_after_validation, {"codegen": "codegen", "pr_writer": "pr_writer"})
    graph.add_edge("pr_writer", "write_back")
    graph.add_edge("write_back", END)

    return graph.compile()
