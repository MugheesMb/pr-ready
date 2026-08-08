import asyncio
import sys

from dotenv import load_dotenv
from rich import print
from rich.panel import Panel

from src.graph import build_graph


async def main():
    load_dotenv()
    request = " ".join(sys.argv[1:]) or (
        "add a nightly table that joins customers to their support ticket "
        "history, so churn scoring has ticket volume as a feature"
    )

    print(Panel(request, title="Request"))

    graph = await build_graph()
    final_state = await graph.ainvoke({"request": request, "validation_errors": []})

    print(Panel(final_state["schema_findings"], title="1. What the agent found in DataHub"))
    print(Panel(final_state["generated_code"], title="2. Generated dbt model", style="green"))
    if final_state.get("pr_url"):
        print(Panel(final_state["pr_url"], title="3. Opened PR", style="bold green"))

    tables_used = final_state.get("tables_used", [])
    wb = final_state.get("write_back_status", {})
    print(Panel(
        f"tables_used (captured from tool calls): {tables_used}\n"
        f"write_back result: {wb}",
        title="4. Write-back diagnostics",
        style="bold cyan",
    ))


if __name__ == "__main__":
    asyncio.run(main())
