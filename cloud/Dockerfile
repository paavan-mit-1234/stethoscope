# Stethoscope Cloud API image. Build context = repo root:
#   docker build -f cloud/Dockerfile -t stethoscope-api .
#
# Multi-stage to keep the runtime image small. The first stage caches deps;
# the second copies code only. Prod env vars are set as defaults so the
# Fargate task definition only needs to override what's truly per-env
# (database URL, JWT secret, CORS origins, S3 bucket, SQS queue URL).

FROM python:3.12-slim AS deps

WORKDIR /build
COPY cloud/requirements.txt /build/requirements.txt
RUN pip install --no-cache-dir --prefix=/install -r /build/requirements.txt


FROM python:3.12-slim AS runtime

# Copy the prebuilt site-packages from the deps stage.
COPY --from=deps /install /usr/local

WORKDIR /app

# The API reuses the proven reference modules unchanged. The cloud package
# is the only thing that's strictly "cloud" code.
COPY tools/ /app/tools/
COPY cloud/ /app/cloud/

# Production defaults. The ECS task definition overrides the secrets
# (database URL, JWT secret, S3 bucket, SQS URL, CORS origins, admin token).
ENV PYTHONUNBUFFERED=1 \
    STETHOSCOPE_ENV=prod \
    STETHOSCOPE_STORE=postgres

EXPOSE 8080

# Two-worker uvicorn for low-traffic Fargate; bump via task definition
# command override when scaling vertically.
CMD ["uvicorn", "cloud.api.app:app", \
     "--host", "0.0.0.0", "--port", "8080", \
     "--workers", "2", "--proxy-headers", \
     "--forwarded-allow-ips", "*"]
