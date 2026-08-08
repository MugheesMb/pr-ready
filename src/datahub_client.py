
import json
import os
from pathlib import Path

from langchain_core.tools import tool

MOCK_SCHEMA_PATH = Path(__file__).parent / "mock_schema.json"


def _load_mock_schema() -> dict:
    with open(MOCK_SCHEMA_PATH) as f:
        return json.load(f)


def _build_mock_tools() -> list:
    """Fake but realistic versions of what the real DataHub MCP server exposes."""
    schema = _load_mock_schema()["tables"]

    @tool
    def search_tables(query: str) -> str:
        """Search for tables in the data catalog by keyword. Returns matching
        table names and their one-line descriptions."""
        query_lower = query.lower()
        hits = [
            f"{name}: {info['description']}"
            for name, info in schema.items()
            if query_lower in name.lower() or query_lower in info["description"].lower()
        ]
        return "\n".join(hits) if hits else "No matching tables found."

    @tool
    def get_table_schema(table_name: str) -> str:
        """Get the exact column names and types for a given table. ALWAYS call
        this before writing any code that references a table's columns —
        never guess column names."""
        info = schema.get(table_name)
        if not info:
            return f"Table '{table_name}' not found. Try search_tables first."
        cols = "\n".join(
            f"  - {c['name']} ({c['type']})" + (" [PRIMARY KEY]" if c.get("is_primary_key") else "")
            for c in info["columns"]
        )
        return f"Table: {table_name}\nOwner: {info['owner']}\nColumns:\n{cols}"

    @tool
    def get_lineage(table_name: str) -> str:
        """Get upstream (sources) and downstream (consumers) tables for a
        given table, so generated code respects existing data flow."""
        info = schema.get(table_name)
        if not info:
            return f"Table '{table_name}' not found."
        up = info.get("upstream", [])
        down = info.get("downstream", [])
        return f"Upstream: {up or 'none'}\nDownstream: {down or 'none'}"

    return [search_tables, get_table_schema, get_lineage]


async def _build_real_tools() -> list:
    """Connects to a REAL, running DataHub instance via its MCP Server.

    Requires:
      1. `datahub docker quickstart` running locally (see README)
      2. DATAHUB_GMS_URL / DATAHUB_GMS_TOKEN set in .env
      3. `uv` installed (the DataHub MCP server is a Python package, run
         via `uvx` — install with `brew install uv` on macOS)
    """
    from langchain_mcp_adapters.client import MultiServerMCPClient

    client = MultiServerMCPClient(
        {
            "datahub": {
                "command": "uvx",
                "args": ["mcp-server-datahub"],
                "env": {
                    "DATAHUB_GMS_URL": os.environ["DATAHUB_GMS_URL"],
                    "DATAHUB_GMS_TOKEN": os.environ.get("DATAHUB_GMS_TOKEN", ""),
                },
                "transport": "stdio",
            }
        }
    )
    return await client.get_tools()


async def get_datahub_tools() -> list:
    """Entry point the rest of the app calls. Reads USE_MOCK_DATAHUB from
    the environment so switching from fake -> real data is a one-line
    change in .env, never a code change."""
    use_mock = os.environ.get("USE_MOCK_DATAHUB", "true").lower() == "true"
    if use_mock:
        return _build_mock_tools()
    return await _build_real_tools()


def write_back(tables_used: list[str], reference_url: str, request: str) -> dict:
    """Closes the loop: after we've generated + validated code from a
    table's schema, leave a note ON that table in DataHub, so the next
    person who opens it in the DataHub UI sees "a model was generated
    from this table, here's the PR." This is what makes the agent an
    active participant in the catalog instead of a read-only consumer.

    Mock mode: appends to a local JSON log (examples/write_back_log.json)
    so the demo still shows the step happening.

    Real mode: uses the DataHub Python SDK to attach an "Institutional
    Memory" link (the same mechanism DataHub's own UI uses for "Links"
    on a dataset page) to each table. NOTE: this REPLACES any existing
    links on the dataset rather than appending — fine for a hackathon
    demo, but flag it if you build on this later. It also assumes DataHub's
    default URN shape (`urn:li:dataset:(urn:li:dataPlatform:dbt,<name>,PROD)`)
    — if your real instance's tables came from a different platform/env,
    check one dataset's URN in the DataHub UI (top of its page) and adjust
    `_guess_dataset_urn` below to match.
    """
    use_mock = os.environ.get("USE_MOCK_DATAHUB", "true").lower() == "true"
    description = f'Generated model for: "{request}"'

    if use_mock:
        log_path = Path("examples/write_back_log.json")
        log_path.parent.mkdir(exist_ok=True)
        entries = json.loads(log_path.read_text()) if log_path.exists() else []
        entries.append({"tables": tables_used, "url": reference_url, "description": description})
        log_path.write_text(json.dumps(entries, indent=2))
        return {"status": "mocked", "tables_annotated": tables_used}

    try:
        import time

        from datahub.emitter.mcp import MetadataChangeProposalWrapper
        from datahub.emitter.rest_emitter import DatahubRestEmitter
        from datahub.metadata.schema_classes import (
            AuditStampClass,
            InstitutionalMemoryClass,
            InstitutionalMemoryMetadataClass,
        )

        emitter = DatahubRestEmitter(
            gms_server=os.environ["DATAHUB_GMS_URL"],
            token=os.environ.get("DATAHUB_GMS_TOKEN") or None,
        )
        now = int(time.time() * 1000)
        annotated = []
        for table_name in tables_used:
            # Real MCP tool calls (list_schema_fields/get_entity) already
            # give us full URNs — only guess one if we somehow got a bare
            # name (e.g. from the mock tools' plain table_name strings).
            urn = table_name if table_name.startswith("urn:li:dataset:") else _guess_dataset_urn(table_name)
            memory = InstitutionalMemoryClass(
                elements=[
                    InstitutionalMemoryMetadataClass(
                        url=reference_url,
                        description=description,
                        createStamp=AuditStampClass(time=now, actor="urn:li:corpuser:pr-ready-agent"),
                    )
                ]
            )
            emitter.emit(MetadataChangeProposalWrapper(entityUrn=urn, aspect=memory))
            annotated.append(table_name)
        return {"status": "written", "tables_annotated": annotated}
    except Exception as e:
        # Never let write-back failure kill the whole pipeline — the PR
        # already exists and matters more than this annotation.
        return {"status": "failed", "error": str(e), "tables_annotated": []}


def _guess_dataset_urn(table_name: str, platform: str = "dbt", env: str = "PROD") -> str:
    """Best-effort URN construction — see the note in write_back() above."""
    return f"urn:li:dataset:(urn:li:dataPlatform:{platform},{table_name},{env})"
