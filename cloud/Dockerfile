# Stethoscope Cloud API image. Build context = repo root:
#   docker build -f cloud/Dockerfile -t stethoscope-api .
FROM python:3.12-slim

WORKDIR /app

COPY cloud/requirements.txt /app/cloud/requirements.txt
RUN pip install --no-cache-dir -r /app/cloud/requirements.txt

# The API reuses the proven reference modules unchanged.
COPY tools/ /app/tools/
COPY cloud/ /app/cloud/

ENV PYTHONUNBUFFERED=1
EXPOSE 8080

# Phase 1 image runs the reference (per-tenant DuckDB). For the Postgres
# canon, set STETHOSCOPE_STORE=postgres + STETHOSCOPE_DATABASE_URL and wire
# tenancy.store_for -> PgStore (one-line swap, see cloud/README.md).
CMD ["uvicorn", "cloud.api.app:app", "--host", "0.0.0.0", "--port", "8080"]
