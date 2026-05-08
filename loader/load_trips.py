from __future__ import annotations

import io
import os
import sys
import time
from pathlib import Path

import psycopg
import pyarrow.parquet as pq

DATA_DIR = Path(os.environ.get("PARQUET_DIR", "/data/nyc_taxi"))
DSN = os.environ["DATABASE_URL"]

DDL = """
CREATE TABLE IF NOT EXISTS yellow_tripdata (
    vendor_id              INTEGER,
    tpep_pickup_datetime   TIMESTAMP,
    tpep_dropoff_datetime  TIMESTAMP,
    passenger_count        BIGINT,
    trip_distance          DOUBLE PRECISION,
    ratecode_id            BIGINT,
    store_and_fwd_flag     TEXT,
    pu_location_id         INTEGER,
    do_location_id         INTEGER,
    payment_type           BIGINT,
    fare_amount            DOUBLE PRECISION,
    extra                  DOUBLE PRECISION,
    mta_tax                DOUBLE PRECISION,
    tip_amount             DOUBLE PRECISION,
    tolls_amount           DOUBLE PRECISION,
    improvement_surcharge  DOUBLE PRECISION,
    total_amount           DOUBLE PRECISION,
    congestion_surcharge   DOUBLE PRECISION,
    airport_fee            DOUBLE PRECISION,
    cbd_congestion_fee     DOUBLE PRECISION,
    source_file            TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS yellow_tripdata_pickup_idx
    ON yellow_tripdata (tpep_pickup_datetime);

CREATE TABLE IF NOT EXISTS _loaded_files (
    source_file TEXT PRIMARY KEY,
    rows        BIGINT NOT NULL,
    loaded_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);
"""

COLUMNS = (
    "vendor_id, tpep_pickup_datetime, tpep_dropoff_datetime, passenger_count, "
    "trip_distance, ratecode_id, store_and_fwd_flag, pu_location_id, "
    "do_location_id, payment_type, fare_amount, extra, mta_tax, tip_amount, "
    "tolls_amount, improvement_surcharge, total_amount, congestion_surcharge, "
    "airport_fee, cbd_congestion_fee, source_file"
)

PARQUET_TO_PG = [
    "VendorID", "tpep_pickup_datetime", "tpep_dropoff_datetime",
    "passenger_count", "trip_distance", "RatecodeID", "store_and_fwd_flag",
    "PULocationID", "DOLocationID", "payment_type", "fare_amount", "extra",
    "mta_tax", "tip_amount", "tolls_amount", "improvement_surcharge",
    "total_amount", "congestion_surcharge", "Airport_fee", "cbd_congestion_fee",
]


def wait_for_db(dsn: str, timeout_s: int = 60) -> None:
    deadline = time.monotonic() + timeout_s
    last: Exception | None = None
    while time.monotonic() < deadline:
        try:
            with psycopg.connect(dsn, connect_timeout=3) as conn:
                conn.execute("SELECT 1")
            return
        except Exception as e:
            last = e
            time.sleep(1)
    raise RuntimeError(f"Postgres not reachable: {last}")


def fmt(v: object) -> str:
    if v is None:
        return r"\N"
    s = str(v)
    return s.replace("\\", "\\\\").replace("\t", " ").replace("\n", " ").replace("\r", " ")


def load_file(conn: psycopg.Connection, path: Path) -> int:
    pf = pq.ParquetFile(path)
    total = 0
    with conn.cursor() as cur, cur.copy(f"COPY yellow_tripdata ({COLUMNS}) FROM STDIN") as copy:
        for batch in pf.iter_batches(batch_size=100_000):
            cols = {name: batch.column(name).to_pylist() for name in PARQUET_TO_PG}
            buf = io.StringIO()
            for i in range(batch.num_rows):
                row = [cols[name][i] for name in PARQUET_TO_PG] + [path.name]
                buf.write("\t".join(fmt(v) for v in row))
                buf.write("\n")
            copy.write(buf.getvalue())
            total += batch.num_rows
    return total


def main() -> int:
    wait_for_db(DSN)
    with psycopg.connect(DSN) as conn:
        conn.execute(DDL)
        conn.commit()
        loaded = {r[0] for r in conn.execute("SELECT source_file FROM _loaded_files")}

        files = sorted(DATA_DIR.glob("yellow_tripdata_*.parquet"))
        if not files:
            print(f"No Parquet files in {DATA_DIR}", file=sys.stderr)
            return 1

        for path in files:
            if path.name in loaded:
                print(f"skip {path.name}", flush=True)
                continue
            t0 = time.monotonic()
            print(f"load {path.name}", flush=True)
            try:
                rows = load_file(conn, path)
                conn.execute(
                    "INSERT INTO _loaded_files (source_file, rows) VALUES (%s, %s)",
                    (path.name, rows),
                )
                conn.commit()
                print(f"  {rows:,} rows in {time.monotonic() - t0:.1f}s", flush=True)
            except Exception:
                conn.rollback()
                raise
    return 0


if __name__ == "__main__":
    sys.exit(main())