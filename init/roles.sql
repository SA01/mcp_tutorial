-- Read-only role used by the MCP server.
-- Table-level SELECT is granted separately by grants.sql, after the loader
-- has created yellow_tripdata. DML and DDL are denied implicitly.

CREATE ROLE mcp_reader LOGIN PASSWORD 'mcp_reader';

GRANT CONNECT ON DATABASE nyc_taxi TO mcp_reader;
GRANT USAGE ON SCHEMA public TO mcp_reader;