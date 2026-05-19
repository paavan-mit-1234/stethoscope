# Stethoscope Cloud (post-1.0) — multi-tenant SaaS

The desktop app is local-first; **Cloud** is the hosted multi-tenant version
(PRD §8 post-1.0). Same pattern as the rest of the project: the **canonical**
target is Postgres on AWS Fargate (Terraform, deploy-by-you); a **runnable
reference** (FastAPI + per-tenant DuckDB) lets you verify tenancy/ingestion
locally with no AWS/Docker/Postgres.

## What's here

| Path | Role |
|---|---|
| `cloud/api/app.py` | FastAPI: OTLP/HTTP ingest + tenant-scoped read API |
| `cloud/api/tenancy.py` | API-key → tenant; per-tenant store (reference: DuckDB) |
| `cloud/api/store_pg.py` + `schema_pg.sql` | **Canon**: Postgres, `tenant_id`-scoped (RDS) |
| `cloud/infra/*.tf` | Terraform: VPC/ALB/ECS Fargate/RDS/S3/ECR/Secrets |
| `cloud/Dockerfile` | API container image |

The API reuses `tools/ref_ingest` (mapper/store/bp) and `tools/ref_replay`
**unchanged** — single source of truth.

## Run the reference locally (no cloud needed)

```bash
pip install fastapi "uvicorn[standard]"
uvicorn cloud.api.app:app --port 8080            # from repo root

# create a tenant -> get an API key
curl -s localhost:8080/tenants -d '{"name":"acme"}' -H content-type:application/json

# point an agent at the cloud endpoint:
export STETHOSCOPE_TRANSPORT=http
export STETHOSCOPE_ENDPOINT=http://localhost:8080/v1/traces
export STETHOSCOPE_API_KEY=<key from above>
python examples/replayable_agent/agent.py

# read it back (tenant-scoped by the key):
curl -s localhost:8080/traces -H "x-stethoscope-key: <key>"
```

Tenants are isolated: a key only ever sees its own traces.

## Deploy to AWS (you run this — needs AWS creds + Terraform + Docker)

```bash
cd cloud/infra
cp terraform.tfvars.example terraform.tfvars     # set a strong db_password
terraform init && terraform apply

# build + push the image to the ECR repo Terraform created:
aws ecr get-login-password --region <r> | docker login --username AWS --password-stdin <ecr_url>
docker build -f cloud/Dockerfile -t <ecr_url>:v1 .
docker push <ecr_url>:v1
terraform apply -var image_tag=v1                # roll the service

# apply the Postgres schema once:
psql "$(aws secretsmanager get-secret-value --secret-id stethoscope/database-url \
  --query SecretString --output text)" -f ../api/schema_pg.sql

# API base = terraform output api_url  ->  agents use <api_url>/v1/traces
```

The web Workbench (`packages/ui`) deploys as a static SPA to S3+CloudFront
with `VITE_STETH_API=<api_url>` (Cloud Phase 2 wires this + Cognito).

## Phase 1 scope / deliberate defers (documented)

- Phase 1 image runs the **DuckDB reference** (correct, but single-instance).
  Production swap: set `STETHOSCOPE_STORE=postgres` + `STETHOSCOPE_DATABASE_URL`
  and change `tenancy.store_for` to return `PgStore(conn, tenant)` — the
  method surface is identical, so nothing else changes. RDS is already
  provisioned by Terraform for this.
- **Deferred to Cloud Phase 2/3:** Cognito auth + user accounts (Phase 1
  uses raw API keys; `/tenants` is open — gate it), S3 blob offload
  (payloads inline for now, same as the embedded store), shareable links
  (PRD §4.11), replay as a job/worker (the reference uses a subprocess —
  not container-ideal), CI/CD (GH Actions → ECR/ECS), autoscaling, billing.
- Not deployed/verified from the build machine (no AWS creds/CLI/Docker
  here) — same status as the uncompiled Rust crates. Verified instead via
  the local FastAPI reference (see above).
