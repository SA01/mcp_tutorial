from datetime import date
from typing import Annotated

import psycopg
from pydantic import Field

from mcp.server.fastmcp import FastMCP

connection_string = "postgresql://mcp_reader:mcp_reader@localhost:5432/nyc_taxi"

mcp = FastMCP("NYC Taxi Trips")

@mcp.tool()
def data_date_range() -> dict:
    """Earliest and latest trip pickup dates available in the dataset.

    Use this first to discover the bounds of the data before calling tools that take
    start_date / end_date arguments. Returns {start_date, end_date} as ISO 8601 date strings.
    Returns nulls for both fields if the table is empty.
    """
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


@mcp.tool()
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


@mcp.tool()
def top_pickup_zones(
    start_date: Annotated[date, Field(description="Inclusive lower bound on pickup date (ISO 8601).")],
    end_date: Annotated[date, Field(description="Exclusive upper bound on pickup date.")],
    limit: Annotated[int, Field(description="Maximum number of zones to return, ranked by trip count descending.", gt=0)],
) -> list[dict]:
    """Top pickup zones by trip count over a date range.

    Returns up to `limit` rows of {zone_id, trips}, ordered by trips descending.
    zone_id is the NYC TLC taxi-zone identifier (integer) — not a human-readable name.
    A zone-to-name mapping is not loaded in this tutorial; callers should treat zone_id as opaque.
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


@mcp.tool()
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


if __name__ == '__main__':
    mcp.run()
