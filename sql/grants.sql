-- Run this after the loader has finished creating yellow_tripdata.
-- Scopes mcp_reader to exactly one table.
GRANT SELECT ON yellow_tripdata TO mcp_reader;
