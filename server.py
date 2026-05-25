import csv
import json
from datetime import date
from pathlib import Path
from typing import Annotated, Any

import psycopg
from pydantic import Field

from mcp.server.fastmcp import FastMCP

connection_string = "postgresql://mcp_reader:mcp_reader@localhost:5432/nyc_taxi"

mcp = FastMCP("NYC Taxi Trips")

# @mcp.tool()  # temporarily hidden — screenshotting date_range only
def trips_per_month(
    start_month: Annotated[str, Field(description="First month to include, inclusive, as 'YYYY-MM' (e.g. '2024-01').", pattern=r"^\d{4}-(0[1-9]|1[0-2])$")],
    end_month: Annotated[str, Field(description="Last month to include, inclusive, as 'YYYY-MM' (e.g. '2024-03').", pattern=r"^\d{4}-(0[1-9]|1[0-2])$")],
) -> list[dict]:
    """Yellow-taxi trip counts grouped by calendar month over a month range.

    Both bounds are inclusive month identifiers. Returns one row per month in the
    range that has any trips, ordered chronologically; each row is {month: 'YYYY-MM', trips: int}.
    """
    sql = """
        SELECT to_char(date_trunc('month', tpep_pickup_datetime), 'YYYY-MM') AS month,
               count(*) AS trips
        FROM yellow_tripdata
        WHERE tpep_pickup_datetime >= to_date(%s, 'YYYY-MM')
          AND tpep_pickup_datetime <  to_date(%s, 'YYYY-MM') + interval '1 month'
        GROUP BY 1
        ORDER BY 1
    """
    with psycopg.connect(connection_string) as conn, conn.cursor() as cur:
        cur.execute(sql, (start_month, end_month))
        return [{"month": m, "trips": t} for m, t in cur.fetchall()]


# @mcp.tool()  # temporarily hidden — screenshotting date_range only
def top_pickup_zones(
    start_date: Annotated[date, Field(description="Inclusive lower bound on pickup date (ISO 8601).")],
    end_date: Annotated[date, Field(description="Exclusive upper bound on pickup date.")],
    limit: Annotated[int, Field(description="Maximum number of zones to return, ranked by trip count descending.", gt=0)],
) -> list[dict]:
    """Top pickup zones by trip count over a date range.

    Returns up to `limit` rows of {zone_id, trips}, ordered by trips descending.
    zone_id is the NYC TLC taxi-zone identifier (integer) — not a human-readable name.
    """
    sql = """
        SELECT pu_location_id AS zone_id,
               count(*) AS trips
        FROM yellow_tripdata
        WHERE tpep_pickup_datetime >= %s
          AND tpep_pickup_datetime <  %s
        GROUP BY 1
        ORDER BY trips DESC
        LIMIT %s
    """
    with psycopg.connect(connection_string) as conn, conn.cursor() as cur:
        cur.execute(sql, (start_date, end_date, limit))
        return [{"zone_id": z, "trips": t} for z, t in cur.fetchall()]


# @mcp.tool()  # temporarily hidden — screenshotting date_range only
def trip_spike_detection(
    start_date: Annotated[date, Field(description="First day to evaluate for spikes (inclusive, ISO 8601).")],
    end_date: Annotated[date, Field(description="Last day to evaluate for spikes (inclusive, ISO 8601).")],
    threshold_pct: Annotated[float, Field(description="Minimum percent above baseline to qualify as a spike. E.g. 50 means 'flag days where trip count exceeds the baseline by more than 50%'.")],
    baseline_window_days: Annotated[int, Field(description="Number of days immediately preceding each evaluated day used to compute the baseline (rolling mean of daily trip counts).")],
) -> list[dict]:
    """Flag days within a range whose trip count exceeds a rolling-mean baseline by more than a given percent.

    For each day D in [start_date, end_date], the baseline is the mean of daily trip counts
    over the baseline_window_days days immediately before D (D-N .. D-1). A day is returned
    only if (trips(D) - baseline) / baseline * 100 > threshold_pct.

    Returns rows of {day, trips, baseline, pct_above_baseline}, ordered chronologically.
    Days too close to start_date to have a full baseline window still receive one — the query
    reads baseline_window_days of history before start_date for this reason.
    """
    sql = """
        WITH daily AS (
            SELECT date_trunc('day', tpep_pickup_datetime)::date AS day,
                   count(*) AS trips
            FROM yellow_tripdata
            WHERE tpep_pickup_datetime >= %s::date - (%s::int * interval '1 day')
              AND tpep_pickup_datetime <  %s::date + interval '1 day'
            GROUP BY 1
        ),
        with_baseline AS (
            SELECT day,
                   trips,
                   avg(trips) OVER (
                       ORDER BY day
                       ROWS BETWEEN %s PRECEDING AND 1 PRECEDING
                   ) AS baseline
            FROM daily
        )
        SELECT day, trips, baseline,
               round(((trips - baseline) / baseline * 100)::numeric, 2) AS pct_above_baseline
        FROM with_baseline
        WHERE day BETWEEN %s AND %s
          AND baseline IS NOT NULL
          AND (trips - baseline) / baseline * 100 > %s
        ORDER BY day
    """
    with psycopg.connect(connection_string) as conn, conn.cursor() as cur:
        cur.execute(
            sql,
            (
                start_date, baseline_window_days,
                end_date,
                baseline_window_days,
                start_date, end_date,
                threshold_pct,
            ),
        )
        return [
            {
                "day": d.isoformat(),
                "trips": int(trips),
                "baseline": float(baseline),
                "pct_above_baseline": float(pct),
            }
            for d, trips, baseline, pct in cur.fetchall()
        ]


COLUMN_ALIASES: dict[str, str] = {
    "vendor":                "vendor_id",
    "pickup_datetime":       "tpep_pickup_datetime",
    "dropoff_datetime":      "tpep_dropoff_datetime",
    "passengers":            "passenger_count",
    "distance":              "trip_distance",
    "ratecode":              "ratecode_id",
    "store_and_fwd_flag":    "store_and_fwd_flag",
    "pickup_zone":           "pu_location_id",
    "dropoff_zone":          "do_location_id",
    "payment_type":          "payment_type",
    "fare":                  "fare_amount",
    "extra":                 "extra",
    "mta_tax":               "mta_tax",
    "tip":                   "tip_amount",
    "tolls":                 "tolls_amount",
    "improvement_surcharge": "improvement_surcharge",
    "total":                 "total_amount",
    "congestion_surcharge":  "congestion_surcharge",
    "airport_fee":           "airport_fee",
    "cbd_congestion_fee":    "cbd_congestion_fee",
}

ALLOWED_AGGREGATES: set[str] = {"count", "sum", "avg", "min", "max"}
ALLOWED_ORDER_DIRECTIONS: set[str] = {"asc", "desc"}

MAX_ROWS = 1000


_ALLOWED_COLUMN_NAMES = sorted(COLUMN_ALIASES.keys())


def _validate_columns(label: str, names: list[str]) -> None:
    bad = [c for c in names if c not in COLUMN_ALIASES]
    if bad:
        raise ValueError(
            f"{label} contains unknown column(s): {bad}. Allowed: {_ALLOWED_COLUMN_NAMES}"
        )


def _validate_select_and_group(select: list[str], group_by: list[str] | None) -> None:
    _validate_columns("select", select)
    if group_by is None:
        return
    _validate_columns("group_by", group_by)
    not_grouped = [c for c in select if c not in group_by]
    if not_grouped:
        raise ValueError(
            f"select columns must also appear in group_by when grouping: {not_grouped}"
        )


def _validate_aggregate(
    aggregate: dict[str, str] | None, group_by: list[str] | None
) -> None:
    if aggregate is None:
        return
    if not group_by:
        raise ValueError("`aggregate` requires `group_by` to be set.")
    _validate_columns("aggregate", list(aggregate.keys()))
    bad_funcs = [f for f in aggregate.values() if f not in ALLOWED_AGGREGATES]
    if bad_funcs:
        raise ValueError(
            f"aggregate function(s) not allowed: {bad_funcs}. "
            f"Allowed: {sorted(ALLOWED_AGGREGATES)}"
        )


def _validate_filters(filters: dict[str, list[Any]] | None) -> None:
    if filters is None:
        return
    _validate_columns("filters", list(filters.keys()))
    empty = [c for c, v in filters.items() if not v]
    if empty:
        raise ValueError(f"filters value lists must be non-empty: {empty}")


def _validate_range_filters(
    range_filters: dict[str, dict[str, Any]] | None,
) -> None:
    if range_filters is None:
        return
    _validate_columns("range_filters", list(range_filters.keys()))
    for col, bounds in range_filters.items():
        if not isinstance(bounds, dict):
            raise ValueError(
                f"range_filters['{col}'] must be a dict with 'low' and 'high' keys."
            )
        extra = set(bounds) - {"low", "high"}
        if extra:
            raise ValueError(
                f"range_filters['{col}'] has unexpected key(s) {sorted(extra)}; "
                f"expected exactly 'low' and 'high'."
            )
        if "low" not in bounds or "high" not in bounds:
            raise ValueError(
                f"range_filters['{col}'] must provide both 'low' and 'high'."
            )


def _sortable_names(
    select: list[str],
    group_by: list[str] | None,
    aggregate: dict[str, str] | None,
) -> set[str]:
    """Names that may appear in `order_by` — anything visible in the result row."""
    aggregate_aliases = {f"{func}_{col}" for col, func in (aggregate or {}).items()}
    return set(select) | set(group_by or ()) | aggregate_aliases


def _validate_order_by(
    order_by: dict[str, str] | None, sortable: set[str]
) -> None:
    if order_by is None:
        return
    bad = [c for c in order_by if c not in sortable]
    if bad:
        raise ValueError(
            f"order_by references column(s) that are not selected, grouped, or "
            f"aggregated: {bad}. Sortable in this query: {sorted(sortable)}"
        )
    bad_dirs = [d for d in order_by.values() if d.lower() not in ALLOWED_ORDER_DIRECTIONS]
    if bad_dirs:
        raise ValueError(
            f"order_by directions must be 'asc' or 'desc', got: {bad_dirs}"
        )


def _build_select_clause(
    select: list[str], aggregate: dict[str, str] | None
) -> tuple[str, list[str]]:
    """Return the SELECT-list SQL and the list of result-row keys it produces."""
    terms = [f"{COLUMN_ALIASES[c]} AS {c}" for c in select]
    output_keys = list(select)
    for col, func in (aggregate or {}).items():
        alias = f"{func}_{col}"
        terms.append(f"{func}({COLUMN_ALIASES[col]}) AS {alias}")
        output_keys.append(alias)
    return ", ".join(terms), output_keys


def _build_where_clause(
    filters: dict[str, list[Any]] | None,
    range_filters: dict[str, dict[str, Any]] | None,
) -> tuple[str, list[Any]]:
    clauses: list[str] = []
    params: list[Any] = []

    for col, values in (filters or {}).items():
        placeholders = ", ".join(["%s"] * len(values))
        clauses.append(f"{COLUMN_ALIASES[col]} IN ({placeholders})")
        params.extend(values)

    # Half-open [low, high): low is inclusive, high is exclusive. Lets callers
    # say "July 2025" as low=2025-07-01, high=2025-08-01 without picking up
    # midnight on Aug 1.
    for col, bounds in (range_filters or {}).items():
        internal = COLUMN_ALIASES[col]
        clauses.append(f"{internal} >= %s AND {internal} < %s")
        params.append(bounds["low"])
        params.append(bounds["high"])

    if not clauses:
        return "", []
    return "WHERE " + " AND ".join(clauses), params


def _build_group_by_clause(group_by: list[str] | None) -> str:
    if not group_by:
        return ""
    return "GROUP BY " + ", ".join(COLUMN_ALIASES[c] for c in group_by)


def _build_order_by_clause(order_by: dict[str, str] | None) -> str:
    # `order_by` keys are validated as either a public column name (handled by the
    # `<internal> AS <public>` alias in SELECT) or an aggregate alias (also in SELECT).
    # Either way, sorting by the public name resolves correctly in Postgres.
    if not order_by:
        return ""
    return "ORDER BY " + ", ".join(f"{c} {d.upper()}" for c, d in order_by.items())


def _build_sql(
    select: list[str],
    group_by: list[str] | None,
    aggregate: dict[str, str] | None,
    filters: dict[str, list[Any]] | None,
    range_filters: dict[str, dict[str, Any]] | None,
    order_by: dict[str, str] | None,
    limit: int,
) -> tuple[str, list[Any], list[str]]:
    """Assemble the SQL string, bind parameters, and result-row keys."""
    select_sql, output_keys = _build_select_clause(select, aggregate)
    where_sql, where_params = _build_where_clause(filters, range_filters)

    parts = [
        f"SELECT {select_sql}",
        "FROM yellow_tripdata",
        where_sql,
        _build_group_by_clause(group_by),
        _build_order_by_clause(order_by),
        "LIMIT %s",
    ]
    sql = "\n".join(p for p in parts if p)
    params = [*where_params, limit]
    return sql, params, output_keys


def _run_query(sql: str, params: list[Any], output_keys: list[str]) -> list[dict]:
    with psycopg.connect(connection_string) as conn, conn.cursor() as cur:
        cur.execute(sql, params)
        return [dict(zip(output_keys, row)) for row in cur.fetchall()]


# @mcp.tool()  # temporarily hidden — screenshotting date_range only
def query_trips(
    select: Annotated[
        list[str],
        Field(
            description=(
                "Columns to return as-is (no aggregation). Must be a subset of the allowed column "
                "names listed below. When `group_by` is given, every entry in `select` must also "
                "appear in `group_by` — SQL would otherwise reject the column as not grouped. Pass "
                "an empty list if you only want aggregates.\n\n"
                f"Allowed column names: {_ALLOWED_COLUMN_NAMES}"
            ),
        ),
    ],
    group_by: Annotated[
        list[str] | None,
        Field(
            description=(
                "Columns to GROUP BY. Optional. Required when `aggregate` is given. Every entry "
                "must be one of the allowed column names."
            ),
        ),
    ] = None,
    aggregate: Annotated[
        dict[str, str] | None,
        Field(
            description=(
                "Aggregations to compute, as a mapping {column: function}. The function must be one "
                "of: count, sum, avg, min, max. `count` accepts any column (including non-numeric); "
                "the others require a numeric column. Result keys are '<func>_<column>' (e.g. "
                "{'fare': 'avg'} -> 'avg_fare'). Requires `group_by` to be set."
            ),
        ),
    ] = None,
    filters: Annotated[
        dict[str, list[Any]] | None,
        Field(
            description=(
                "Equality (IN) filters, as {column: [value, ...]}. A row matches when the column "
                "equals one of the listed values; multiple columns are combined with AND. Use this "
                "for discrete-value columns (payment_type, pickup_zone, vendor, ...). "
                "DO NOT use this for date or timestamp ranges — listing two dates here means "
                "'exactly these two instants', not 'between them'. Use `range_filters` instead."
            ),
        ),
    ] = None,
    range_filters: Annotated[
        dict[str, dict[str, Any]] | None,
        Field(
            description=(
                "Half-open range filters, as {column: {'low': L, 'high': H}}. A row matches when "
                "`L <= column < H` (low inclusive, high exclusive). Multiple columns are combined "
                "with AND, and may be combined with `filters` on other columns. "
                "Designed for date/timestamp and numeric ranges — e.g. all of July 2025 is "
                "{'pickup_datetime': {'low': '2025-07-01', 'high': '2025-08-01'}}. Values are "
                "passed as bind parameters; types must match the underlying column."
            ),
        ),
    ] = None,
    order_by: Annotated[
        dict[str, str] | None,
        Field(
            description=(
                "Sort order, as {column_or_alias: 'asc'|'desc'}. Each key must be either (a) a "
                "column listed in `select` / `group_by`, or (b) an aggregate output name of the "
                "form '<func>_<column>' that matches an entry in `aggregate`. Sorting by a column "
                "that wasn't selected or grouped is rejected. Insertion order of the dict defines "
                "sort priority."
            ),
        ),
    ] = None,
    limit: Annotated[
        int,
        Field(
            description=(
                f"Maximum number of rows to return. Capped at {MAX_ROWS}. Applies after grouping."
            ),
            gt=0,
            le=MAX_ROWS,
        ),
    ] = 100,
) -> list[dict]:
    """Generic, validated query against the yellow-taxi trips dataset.

    A constrained alternative to a raw-SQL tool: callers describe *what* they want
    (columns, grouping, aggregates, equality filters, sort order) and the server
    assembles a parameterized SQL statement. Only an allow-listed set of column
    names and aggregate functions are accepted; everything else is rejected before
    any SQL runs.

    All column names in arguments and result keys use the public alias names, not
    the underlying database column names.

    Shape:
      - `select` lists plain columns to return.
      - `group_by` + `aggregate` together produce a GROUP BY query. If `aggregate`
        is set, `group_by` must also be set, and every `select` column must appear
        in `group_by`.
      - `filters` is a dict of equality-in-set predicates (SQL `IN`), joined with
        AND across keys: `{"pickup_zone": [132, 138], "payment_type": [1]}` becomes
        `pickup_zone IN (132, 138) AND payment_type IN (1)`. Use for discrete values
        only; for date/timestamp/numeric ranges use `range_filters`.
      - `range_filters` is a dict of half-open ranges, joined with AND with each
        other and with `filters`: `{"pickup_datetime": {"low": "2025-07-01",
        "high": "2025-08-01"}}` becomes `tpep_pickup_datetime >= '2025-07-01' AND
        tpep_pickup_datetime < '2025-08-01'`.
      - `order_by` sorts the result. Keys must be either a selected/grouped
        column name or an aggregate output alias (e.g. `avg_fare`).
      - `limit` caps the result row count.

    Returns a list of {column_or_alias: value} dicts. Aggregate columns are named
    `<func>_<column>` using the public column alias (e.g. `avg_fare`,
    `count_pickup_zone`). Use `data_date_range` first if you need to know the
    available date span before constructing filters.
    """
    if not select and not aggregate:
        raise ValueError("Provide at least one of `select` or `aggregate`.")

    _validate_select_and_group(select, group_by)
    _validate_aggregate(aggregate, group_by)
    _validate_filters(filters)
    _validate_range_filters(range_filters)
    _validate_order_by(order_by, _sortable_names(select, group_by, aggregate))

    sql, params, output_keys = _build_sql(
        select, group_by, aggregate, filters, range_filters, order_by, limit
    )
    return _run_query(sql, params, output_keys)


# ---------------------------------------------------------------------------
# Resources
#
#   taxitrips://schema            — the tool surface as JSON (static)
#   taxitrips://zones             — the TLC zone_id → name lookup (static)
#   taxitrips://date-range        — earliest/latest pickup dates in the dataset (dynamic)
#   taxitrips://samples/{tool}    — a live sample of each tool's output (dynamic)
# ---------------------------------------------------------------------------


_SCHEMA: dict[str, Any] = {
    "trips_per_month": {
        "description": "Trip counts grouped by calendar month over a month range.",
        "inputs": {
            "start_month": "string, 'YYYY-MM', inclusive",
            "end_month": "string, 'YYYY-MM', inclusive",
        },
        "output": {
            "shape": "array of objects",
            "fields": {"month": "'YYYY-MM'", "trips": "integer"},
        },
    },
    "top_pickup_zones": {
        "description": "Top pickup zones by trip count over a date range.",
        "inputs": {
            "start_date": "ISO 8601 date, inclusive",
            "end_date": "ISO 8601 date, exclusive",
            "limit": "integer > 0",
        },
        "output": {
            "shape": "array of objects",
            "fields": {
                "zone_id": "TLC zone id (integer); resolve via taxitrips://zones",
                "trips": "integer",
            },
        },
    },
    "trip_spike_detection": {
        "description": "Days whose trip count exceeds a rolling baseline by more than a given percent.",
        "inputs": {
            "start_date": "ISO 8601 date, inclusive",
            "end_date": "ISO 8601 date, inclusive",
            "threshold_pct": "float; percent above baseline that qualifies as a spike",
            "baseline_window_days": "integer; rolling window size",
        },
        "output": {
            "shape": "array of objects",
            "fields": {
                "day": "ISO 8601 date",
                "trips": "integer",
                "baseline": "float",
                "pct_above_baseline": "float",
            },
        },
    },
    "query_trips": {
        "description": (
            "Generic, validated query against yellow_tripdata. Callers describe what they "
            "want; the server assembles a parameterized SQL statement."
        ),
        "inputs": {
            "select": "list[str]; allowed column names only",
            "group_by": "list[str] | null; required when aggregate is set",
            "aggregate": "{column: function} | null; function in {count, sum, avg, min, max}",
            "filters": "{column: [values]} | null; IN-set equality, ANDed across keys",
            "range_filters": "{column: {low, high}} | null; half-open [low, high)",
            "order_by": "{column_or_alias: 'asc'|'desc'} | null",
            "limit": f"integer, 1..{MAX_ROWS}",
        },
        "output": {
            "shape": "array of objects",
            "fields": (
                "keys match `select` entries; aggregate columns are named '<func>_<column>' "
                "(e.g. avg_fare)"
            ),
        },
        "allowed_columns": _ALLOWED_COLUMN_NAMES,
        "allowed_aggregates": sorted(ALLOWED_AGGREGATES),
    },
}


@mcp.resource(
    "taxitrips://schema",
    name="schema",
    description="Tool surface as JSON: inputs, outputs, allow-listed columns and aggregates.",
    mime_type="application/json",
)
def schema_resource() -> str:
    return json.dumps(_SCHEMA, indent=2)


_ZONES_CSV = Path(__file__).parent / "data" / "taxi_zone_lookup.csv"


def _load_zones() -> list[dict]:
    with _ZONES_CSV.open(newline="") as f:
        reader = csv.DictReader(f)
        return [
            {
                "location_id": int(row["LocationID"]),
                "borough": row["Borough"],
                "zone": row["Zone"],
                "service_zone": row["service_zone"],
            }
            for row in reader
        ]


@mcp.resource(
    "taxitrips://zones",
    name="zones-lookup",
    description="TLC taxi-zone lookup: Maps location IDs (pickup and drop off location IDs) to borough, zone, and service_zone.",
    mime_type="application/json",
)
def zones_resource() -> str:
    return json.dumps(_load_zones(), indent=2)


def _query_date_range() -> dict:
    """Earliest and latest trip pickup dates available in the dataset."""
    sql = """
        SELECT min(tpep_pickup_datetime)::date AS start_date,
               max(tpep_pickup_datetime)::date AS end_date
        FROM yellow_tripdata
    """
    with psycopg.connect(connection_string) as conn, conn.cursor() as cur:
        cur.execute(sql)
        start, end = cur.fetchone()
        return {
            "start_date": start.isoformat() if start else None,
            "end_date": end.isoformat() if end else None,
        }


@mcp.resource(
    "taxitrips://date-range",
    name="date-range",
    description="Earliest and latest pickup dates available in the dataset.",
    mime_type="application/json",
)
def date_range_resource() -> str:
    return json.dumps(_query_date_range(), indent=2)


# Sample resource template. Each branch runs a real query against the live DB
# so the returned shape reflects current data. Kept small (10 rows) so the
# response stays cheap to fetch — these are illustrative, not analytical.

def _sample_trips_per_month() -> Any:
    bounds = _query_date_range()
    end = bounds["end_date"]
    if end is None:
        return []
    end_month = end[:7]
    # ten months ending at the latest available month
    year, month = int(end_month[:4]), int(end_month[5:7])
    start_month_idx = (year * 12 + (month - 1)) - 9
    sy, sm = divmod(start_month_idx, 12)
    start_month = f"{sy:04d}-{sm + 1:02d}"
    return trips_per_month(start_month=start_month, end_month=end_month)


def _sample_top_pickup_zones() -> Any:
    bounds = _query_date_range()
    if bounds["end_date"] is None:
        return []
    end_date = date.fromisoformat(bounds["end_date"])
    start_date = date(end_date.year, end_date.month, 1)
    return top_pickup_zones(start_date=start_date, end_date=end_date, limit=10)


def _sample_trip_spike_detection() -> Any:
    bounds = _query_date_range()
    if bounds["end_date"] is None:
        return []
    end_date = date.fromisoformat(bounds["end_date"])
    start_date = date(end_date.year, end_date.month, 1)
    return trip_spike_detection(
        start_date=start_date,
        end_date=end_date,
        threshold_pct=10.0,
        baseline_window_days=7,
    )


def _sample_query_trips() -> Any:
    """A few representative shapes — not exhaustive."""
    bounds = _query_date_range()
    if bounds["end_date"] is None:
        return {}
    end_date = date.fromisoformat(bounds["end_date"])
    month_start = date(end_date.year, end_date.month, 1)
    month_str = month_start.isoformat()
    end_str = end_date.isoformat()

    plain_select = query_trips(
        select=["pickup_zone", "fare", "tip"],
        range_filters={"pickup_datetime": {"low": month_str, "high": end_str}},
        limit=10,
    )
    grouped_aggregate = query_trips(
        select=["payment_type"],
        group_by=["payment_type"],
        aggregate={"fare": "avg", "tip": "avg"},
        range_filters={"pickup_datetime": {"low": month_str, "high": end_str}},
        order_by={"avg_fare": "desc"},
        limit=10,
    )
    top_zones_by_avg_fare = query_trips(
        select=["pickup_zone"],
        group_by=["pickup_zone"],
        aggregate={"fare": "avg", "pickup_zone": "count"},
        range_filters={"pickup_datetime": {"low": month_str, "high": end_str}},
        order_by={"avg_fare": "desc"},
        limit=10,
    )
    return {
        "plain_select": plain_select,
        "grouped_aggregate": grouped_aggregate,
        "top_zones_by_avg_fare": top_zones_by_avg_fare,
    }


_SAMPLERS = {
    "trips_per_month": _sample_trips_per_month,
    "top_pickup_zones": _sample_top_pickup_zones,
    "trip_spike_detection": _sample_trip_spike_detection,
    "query_trips": _sample_query_trips,
}


@mcp.resource(
    "taxitrips://samples/{tool}",
    name="samples",
    description=(
        "Live sample output for a given tool. Path values: "
        "trips_per_month, top_pickup_zones, trip_spike_detection, query_trips."
    ),
    mime_type="application/json",
)
def samples_resource(tool: str) -> str:
    sampler = _SAMPLERS.get(tool)
    if sampler is None:
        raise ValueError(
            f"Unknown tool '{tool}'. Available: {sorted(_SAMPLERS)}"
        )
    result = sampler()
    return json.dumps(result, indent=2, default=str)


if __name__ == '__main__':
    mcp.run()
