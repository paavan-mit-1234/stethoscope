# Stethoscope Cloud — Deploy & Teardown Runbook

This is the exact sequence to stand up the AWS infrastructure, ship a build,
verify it, and tear it down. Steps marked **YOU** require human action;
**ME** steps are baked into the repo and run automatically.

> ⚠️ **Cost reminder built into every section.** This stack is designed as a
> portfolio demo on the AWS Free Plan ($100 credit, 6 months). It is **not**
> 24/7-safe. Tear down or scale to zero whenever you're not actively
> demonstrating it — instructions in [§Teardown](#teardown) and
> [§Scale to zero](#scale-to-zero).

---

## 0. Prerequisites (YOU, once)

### 0.1 AWS account

1. Sign up at https://aws.amazon.com — root email + card.
2. **Enable MFA on the root account** (Security credentials → MFA).
3. Create an IAM user `stethoscope-deploy` with **AdministratorAccess** (we'll
   tighten this later via the OIDC role from Terraform). Generate an access
   key, choose "Local code" purpose, copy the values.
4. Set a **Free Tier alert** in Billing preferences and a manual **Budget**
   at $10/month while you learn — the Terraform creates budgets too, but a
   second pair of eyes on the root account is wise.

### 0.2 Local tools

| Tool | Why | Install |
|---|---|---|
| AWS CLI v2 | run AWS commands | https://aws.amazon.com/cli/ |
| Terraform ≥ 1.5 | provision infra | https://developer.hashicorp.com/terraform/install |
| Docker Desktop | build the API image | https://docker.com/products/docker-desktop |
| pnpm + Node 20 | build the UI | https://pnpm.io/installation |
| Visual Studio Build Tools 2022 (Desktop C++ workload) | required for MSVC Rust toolchain — Phase 4 only | https://visualstudio.microsoft.com/downloads/ |
| rustup | Rust crates — Phase 4 only | https://rustup.rs |

```powershell
aws configure
# AWS Access Key ID: <from step 0.1>
# AWS Secret Access Key: <from step 0.1>
# Default region name: ap-south-1
# Default output format: json

aws sts get-caller-identity    # sanity check: prints your account + user
```

---

## 1. First Terraform apply (YOU)

### 1.1 Bootstrap variables

```powershell
cd cloud\infra
cp terraform.tfvars.example terraform.tfvars
notepad terraform.tfvars
```

Set at minimum:
- `db_password` — any strong password, 12+ chars
- `alert_email` — your email; AWS sends a confirmation link, click it
- `gh_repo` — `<your-gh-user>/stethoscope` (only if you want CI deploy)

Leave `api_desired_count` and `worker_desired_count` at **0** for now —
this brings up the network + DB + CF without paying for Fargate hours.

### 1.2 Initialize + plan

```powershell
terraform init
terraform fmt -check
terraform validate
terraform plan -out tfplan
```

Read the plan output. Expect ~75 resources to be created:
VPC, 4 subnets, NAT, IGW, 3 SGs, RDS, 2 ECS task defs + services,
ALB + target group + listener + rule, S3 (payloads + UI), CloudFront,
3 Secrets Manager secrets, Cognito user pool + client + domain, SQS queue
+ DLQ, 4 CloudWatch alarms, 2 Budgets, SNS topic + email subscription,
4 IAM roles, ECR repo. ~10 minutes to apply.

### 1.3 Apply

```powershell
terraform apply tfplan
```

If it fails with `EntityAlreadyExists` on the GitHub OIDC provider, your
account already has it from another project:

```powershell
terraform import 'aws_iam_openid_connect_provider.github[0]' `
  arn:aws:iam::<account-id>:oidc-provider/token.actions.githubusercontent.com
terraform apply
```

### 1.4 Save the outputs

```powershell
terraform output > ..\..\last-deploy-outputs.txt
```

You'll reference these for §2 (CI bootstrap) and §3 (first build).

> 💰 **At this point you are paying for**: ALB ($20/mo), NAT Gateway
> ($32/mo), RDS db.t3.micro (free for 750hr/mo for first 12 months on a new
> account, ~$13/mo after), CloudWatch + Secrets + S3 (cents). Approximately
> **₹4,500/mo** while idle. Tear down when not in use — see [§Teardown](#teardown).

### 1.5 Confirm the SNS subscription

Check your email. AWS sends a "Confirm subscription" link from
`no-reply@sns.amazonaws.com`. **Click it.** If you skip this, the
CloudWatch alarms can't reach you and the budget alerts won't fire.

---

## 2. Wire up GitHub Actions deploy (YOU, once)

Go to https://github.com/&lt;your-repo&gt;/settings/variables/actions and add
the following as **Repository variables** (not secrets — none are sensitive):

| Variable | Value (from `terraform output`) |
|---|---|
| `AWS_REGION` | `ap-south-1` |
| `AWS_ROLE_ARN` | `gh_deploy_role_arn` |
| `ECR_REPOSITORY` | `ecr_repository_url` |
| `ECS_CLUSTER` | `ecs_cluster_name` |
| `ECS_API_SERVICE` | `ecs_service_api` |
| `ECS_WORKER_SERVICE` | `ecs_service_worker` |
| `ECS_API_TASK_FAMILY` | `stethoscope-dev-api` (project + env) |
| `ECS_WORKER_TASK_FAMILY` | `stethoscope-dev-worker` |
| `UI_BUCKET` | `ui_bucket` |
| `CLOUDFRONT_DISTRIBUTION_ID` | `cloudfront_distribution_id` |
| `PUBLIC_API_URL` | `cloudfront_url` |

---

## 3. First build & deploy (YOU)

You have two choices for the first image push: GitHub Actions (easier, but
needs §2 done) or a local Docker push (more direct, useful for debugging).

### 3.1 Option A — push from your laptop

```powershell
$REGION = "ap-south-1"
$ECR = terraform -chdir=cloud\infra output -raw ecr_repository_url

aws ecr get-login-password --region $REGION | `
  docker login --username AWS --password-stdin $ECR

docker build -f cloud\Dockerfile -t "$ECR:v1" .
docker push "$ECR:v1"

# Tell ECS to roll the service:
$CLUSTER = terraform -chdir=cloud\infra output -raw ecs_cluster_name
$SERVICE = terraform -chdir=cloud\infra output -raw ecs_service_api
aws ecs update-service --cluster $CLUSTER --service $SERVICE --force-new-deployment
```

### 3.2 Option B — push from GitHub Actions

```powershell
git push origin main
```

Watch the run at https://github.com/&lt;your-repo&gt;/actions. The `deploy-api`
job builds and pushes; `deploy-ui` builds the SPA. If either fails, the
"Wire up GitHub Actions deploy" repo variables are the usual suspect.

### 3.3 Scale up the API task

The first apply set `api_desired_count = 0`. Bring it up:

```powershell
cd cloud\infra
terraform apply -var "api_desired_count=1"
```

Watch the ECS console — service should reach `runningCount = 1` within
~2 minutes. If it doesn't, the most common cause is the image failing
health checks; check CloudWatch Logs at
`/ecs/stethoscope-dev-api` for the uvicorn output.

---

## 4. Verify (YOU)

### 4.1 Hit the API

```powershell
$URL = terraform -chdir=cloud\infra output -raw cloudfront_url
curl "$URL/health"
# {"ok":true,"service":"stethoscope-cloud","env":"dev"}

curl "$URL/health/deep"
# {"ok":true,"db_error":null,"env":"dev"}    ← if db_error is set, see §6
```

### 4.2 Mint a tenant (admin-only in prod)

```powershell
# Fetch the admin token from Secrets Manager:
$ADMIN_SECRET_ARN = terraform -chdir=cloud\infra output -raw admin_token_secret_arn
$ADMIN = aws secretsmanager get-secret-value --secret-id $ADMIN_SECRET_ARN `
  --query SecretString --output text

# Create a tenant:
curl -X POST "$URL/tenants" `
  -H "Authorization: Bearer $ADMIN" `
  -H "Content-Type: application/json" `
  -d '{"name":"demo"}'
# {"tenant_id":"...","api_key":"sk_steth_..."}
```

### 4.3 Send a trace from an agent

```powershell
$env:STETHOSCOPE_TRANSPORT = "http"
$env:STETHOSCOPE_ENDPOINT = "$URL/v1/traces"
$env:STETHOSCOPE_API_KEY = "<api_key from 4.2>"
python examples\replayable_agent\agent.py

# Read it back:
curl "$URL/traces" -H "X-Stethoscope-Key: <api_key>"
```

### 4.4 View it in the UI

Open `$URL` in a browser. If `deploy-ui` ran, the SPA is at CloudFront's
root. Log in with the Cognito hosted UI (link from
`terraform output cognito_hosted_ui`) and confirm your tenant's traces
appear.

---

## 5. Scale to zero (YOU, between sessions)

The cheapest "still up" mode — kills Fargate hours but keeps the network,
DB, and Cognito so you can restart in 60 seconds.

```powershell
cd cloud\infra
terraform apply -var "api_desired_count=0" -var "worker_desired_count=0"
```

Still costs ~₹4,500/mo (ALB + NAT + RDS). For real zero, see §6.

---

## 6. Teardown (YOU)

**Do this whenever you're done demonstrating for the day.** Restoring
takes one `terraform apply` and ~10 minutes.

```powershell
cd cloud\infra
terraform destroy
```

Expect prompts about:
- The RDS snapshot — non-prod env destroys without a final snapshot.
- The ECR images — `force_delete = true` in dev wipes them.
- The S3 buckets — `force_destroy = true` empties them first.

After destroy, **verify the billing console**:
- https://console.aws.amazon.com/billing/home
- AWS Budgets → confirm your monthly forecast drops within 24h.
- Cost Explorer (enable it if you haven't) → daily spend.

> 💰 **Sanity check**: after a clean destroy, your daily spend should be
> under $0.10. If you see RDS or NAT hours days later, run `terraform
> destroy` again to clean up leftovers.

---

## 7. Operating it day to day

### 7.1 Reading logs

```powershell
aws logs tail /ecs/stethoscope-dev-api --since 10m --follow
aws logs tail /ecs/stethoscope-dev-worker --since 10m --follow
```

### 7.2 Connecting to the DB (debugging only)

The DB is in private subnets. To `psql` you need a bastion or a one-off
ECS task on the same SG:

```powershell
# Option A: ECS Exec into a running API task and use psql there
aws ecs execute-command --cluster <cluster> --task <task-id> `
  --container api --command "/bin/sh" --interactive

# Option B (production): create a bastion EC2 (not in TF — manual)
```

### 7.3 Rotating secrets

Secrets in `${project}/jwt-secret`, `${project}/database-url`,
`${project}/admin-token`. Use the console or:

```powershell
aws secretsmanager update-secret --secret-id stethoscope-dev/jwt-secret `
  --secret-string "$(python -c 'import secrets;print(secrets.token_urlsafe(48))')"
# then redeploy so the task picks it up:
aws ecs update-service --cluster <cluster> --service <api> --force-new-deployment
```

---

## 8. Replay — the honest deferral

The cloud `/branch` endpoint enqueues a job to SQS. The worker logs it and
acknowledges; **it does not actually run the replay**. The cloud can't, by
construction: replaying a customer's agent needs the agent's source code,
which lives on the customer's machine.

If you want replay to actually work, three options:

1. **Use the desktop app.** That path is unchanged — Tauri shell + the
   Python reference, which has the agent source locally.
2. **Build a customer-side runner CLI.** A small Python tool that
   subscribes to the replay queue (via a per-tenant scoped API token),
   pulls jobs, runs locally, ships traces back. Out of scope for this
   pass.
3. **Run agents in the cloud yourself.** Build the customer's Dockerfile
   into a per-tenant ECR image, run on Fargate per replay. Expensive,
   requires per-tenant secrets management.

For the portfolio demo, leave it as is — the queue + worker + IAM is the
*architecture*; the implementation gap is documented and honest.

---

## 9. Budget Action auto-stop (OPTIONAL, manual)

Terraform creates budget *notifications* but not budget *actions* (which
would automatically scale the API service to 0 when spend crosses the
hard cap). The action requires an SSM Automation document, which is
fiddly in TF.

If you want it:

1. Console → Systems Manager → Documents → Create automation.
2. Use `AWS-StopECSService` (or paste a custom doc that runs
   `aws ecs update-service --desired-count 0`).
3. Console → Budgets → your monthly budget → Actions → Add action →
   Run SSM document → select the document → 100% of budget → email +
   action. AWS will create the role and trust permissions for you.

Documented manual because the console flow is faster than the equivalent
~80 lines of HCL, and Budgets Actions APIs have changed shape recently.

---

## 10. The reminder block

**Before you leave for the day**, run through this:

```
[ ] terraform output cloudfront_url → still serving? if not, fine, ignore
[ ] aws ecs describe-services --cluster <c> --services <api> → desired_count
[ ] AWS Billing console → today's "Forecasted month-to-date" → green?
[ ] Decided: keep running, scale to zero, or destroy?
[ ] If destroy: cd cloud\infra && terraform destroy
```

If you're not sure whether to destroy: **destroy**. Bringing it back is
one command and 10 minutes.
