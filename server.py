import psycopg

from mcp.server.fastmcp import FastMCP

connection_string = "postgresql://mcp_reader:mcp_reader@localhost:5432/nyc_taxi"

mcp = FastMCP("NYC Taxi Trips")

@mcp.tool()
def run_sql(sql: str) -> dict:
    with psycopg.connect(connection_string) as conn, conn.cursor() as cur:
        cur.execute(sql)
        columns = [d.name for d in cur.description] if cur.description else []
        rows = cur.fetchall() if cur.description else []
    return {"columns": columns, "rows": rows}

if __name__ == '__main__':
    mcp.run()