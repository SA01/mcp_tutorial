FROM python:3.12-slim

RUN pip install --no-cache-dir "psycopg[binary]==3.3.4" "pyarrow==24.0.0"

WORKDIR /app
COPY load_trips.py .

ENTRYPOINT ["python", "load_trips.py"]