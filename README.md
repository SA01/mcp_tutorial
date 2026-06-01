# Building Production-Grade MCP Servers

Companion repository for the article **[Building Production-Grade MCP Servers](<Add link>)**.

This repo builds an MCP (Model Context Protocol) server over a PostgreSQL database of NYC Yellow Taxi trips (~48 million rows), and then progressively rebuilds it the way you would for production — moving from a single `run_sql` tool to a layered design with scoped database roles, narrow tools, a validated query builder, resources, and prompts.

Each stage lives on its own branch, so you can check out any layer and run it as it existed at that point in the article.

## What this demonstrates

- Why exposing a raw `run_sql` tool is dangerous (schema inspection, destructive operations, expensive scans).
- Applying least privilege with a read-only PostgreSQL role — and what it does *not* catch.
- Replacing raw SQL with narrow, single-purpose tools, and the trade-offs that come with them.
- A validated, generic query builder that restores flexibility without exposing arbitrary SQL.
- Using MCP **resources** to give the model authoritative context (zone lookups, schema, samples).
- Using MCP **prompts** to encode correct usage for common analyses.

The article also covers the production concerns beyond the code — scaling, authentication, and monitoring.

## Branch guide

The repository is structured as a sequence of branches, each corresponding to a stage in the article:

| Branch | Stage |
|---|---|
| `feature/_00_initial_setup` | Database, data loader, and project setup |
| `feature/_01_simple_mcp` | The naive version: a single `run_sql` tool |
| `feature/_02_scoped_tools` | Read-only database role (least privilege) |
| `feature/_03_specific_tools` | Narrow, single-purpose tools |
| `feature/_04_advanced_generic_tool` | Validated generic query builder |
| `feature/_05_resources` | Resources |
| `feature/_06_prompts` | Prompts |

Check out any branch to see the server at that stage:

```bash
git checkout feature/_03_specific_tools
```

## Quickstart

Requires **Python 3.12**, **uv**, **Docker**, and **Docker Compose**.

```bash
# Clone and check out the starting point
git clone https://github.com/SA01/mcp_tutorial.git
cd mcp_tutorial
git checkout feature/_00_initial_setup

# Download the NYC Yellow Taxi 2025 Parquet files into data/nyc_taxi/
# (see the article or the TLC Trip Record Data page)

# Bring up PostgreSQL and load the data (~10 min on first run)
uv sync
docker compose up
```

The TLC Trip Record Data is available at: https://www.nyc.gov/site/tlc/about/tlc-trip-record-data.page

Once the data is loaded, run the MCP server and the MCP Inspector:

```bash
uv run mcp dev server.py
```

See the article for connecting the server to Claude Code or Claude Desktop, and for the full walkthrough of each stage.

## A note on security

This is a teaching repository. The database credentials, open permissions, and configuration here are deliberately simple so the examples are easy to follow, they are **not** production-ready as written. The whole point of the article is what you need to add and change before something like this is safe to deploy. Please read it before adapting any of this for real use.

## The article

The full write-up, including the reasoning behind each design decision, the failure modes at each stage, and the production concerns (scaling, authentication, monitoring) is here:

**[Building Production-Grade MCP Servers](<Add link>)**