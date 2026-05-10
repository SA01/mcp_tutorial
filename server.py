from __future__ import annotations

import logging
import os
import sys

import psycopg
from mcp.server.fastmcp import FastMCP

# Log to stderr — stdout is reserved for the MCP protocol stream over stdio.
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    stream=sys.stderr,
)
log = logging.getLogger("nyc-taxi")

DSN = os.environ.get(
    "DATABASE_URL",
    "postgresql://postgres:postgres@localhost:5432/nyc_taxi",
)

mcp = FastMCP("nyc-taxi")


@mcp.tool()
def run_sql(sql: str) -> dict:
    """Run a SQL query against the NYC taxi database and return rows."""
    log.info("query passed: %s", sql)
    with psycopg.connect(DSN) as conn, conn.cursor() as cur:
        cur.execute(sql)
        columns = [d.name for d in cur.description] if cur.description else []
        rows = cur.fetchall() if cur.description else []
    return {"columns": columns, "rows": rows}


if __name__ == "__main__":
    mcp.run()
