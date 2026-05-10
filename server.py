import logging
import sys

import psycopg
from mcp.server.fastmcp import FastMCP

# Log to stderr — stdout is reserved for the MCP protocol stream over stdio.
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    stream=sys.stderr,
)
logger = logging.getLogger("nyc-taxi")

connection_string = "postgresql://postgres:postgres@localhost:5432/nyc_taxi"

mcp = FastMCP("nyc-taxi")


@mcp.tool()
def run_sql(sql_query: str) -> dict:
    logger.info("query passed: %s", sql_query)
    with psycopg.connect(connection_string) as conn, conn.cursor() as cur:
        cur.execute(sql_query)
        columns = [d.name for d in cur.description] if cur.description else []
        rows = cur.fetchall() if cur.description else []
    return {"columns": columns, "rows": rows}


if __name__ == "__main__":
    mcp.run()
