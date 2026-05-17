from datetime import date

import psycopg

from mcp.server.fastmcp import FastMCP

connection_string = "postgresql://mcp_reader:mcp_reader@localhost:5432/nyc_taxi"

mcp = FastMCP("NYC Taxi Trips")

@mcp.tool()
def trips_per_month(start_date: date, end_date: date) -> list[dict]:
    sql = """
        SELECT to_char(date_trunc('month', tpep_pickup_datetime), 'YYYY-MM') AS month,
               count(*) AS trips
        FROM yellow_tripdata
        WHERE tpep_pickup_datetime >= %s
          AND tpep_pickup_datetime <  %s
        GROUP BY 1
        ORDER BY 1
    """
    with psycopg.connect(connection_string) as conn, conn.cursor() as cur:
        cur.execute(sql, (start_date, end_date))
        return [{"month": m, "trips": t} for m, t in cur.fetchall()]


@mcp.tool()
def spike_detection(
    start_date: date,
    end_date: date,
    threshold_pct: float,
    baseline_window_days: int,
) -> list[dict]:
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


@mcp.tool()
def top_pickup_zones(start_date: date, end_date: date, limit: int) -> list[dict]:
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


if __name__ == '__main__':
    mcp.run()
