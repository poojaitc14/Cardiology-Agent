# Deploying to AWS: ECR + ECS (Fargate) Runbook

Status: **planning document only — nothing in this file has been run.** It is a
step-by-step deployment guide for taking the existing `Dockerfile.backend` /
`Dockerfile.frontend` images to a production ECS deployment, fronted by an
Application Load Balancer, with the two services discovering each other over
an internal namespace.

This assumes the AWS-hosted dependencies documented in
[`opensearch-serverless.md`](opensearch-serverless.md) already exist (DynamoDB
table `PatientClinicalRecords`, OpenSearch Serverless collection
`cardiology-agent-rag` / index `cardiology-approved-documents`) — this runbook
deploys the two *application* containers around them, it doesn't recreate the
data layer.

Placeholders used throughout: `<ACCOUNT_ID>`, `<REGION>` (e.g. `eu-west-2`),
`<VPC_ID>`, `<SUBNET_...>`. Replace before running anything for real.

Prefer clicking through the AWS Console over running CLI commands? See
[`aws-ecs-deployment-console.md`](aws-ecs-deployment-console.md) — same
resources, same section order, browser steps instead of `aws` commands.

Want to skip creating a new VPC/subnets/NAT Gateway and reuse the account's
existing default VPC instead? See
[`aws-ecs-deployment-no-new-vpc.md`](aws-ecs-deployment-no-new-vpc.md) — a
delta doc covering just the sections that change (networking, security
groups, the ALB, and the ECS services' network config); everything else here
stays the same.

---

## 0. Prerequisites

- AWS CLI v2 configured with an identity that can create IAM roles, VPC
  resources, ECR repos, ECS resources, an ALB, and Cloud Map namespaces.
- Docker installed locally (or a CI runner that has it).
- The app's real secrets ready to hand: `AZURE_OPENAI_API_KEY`,
  `AZURE_OPENAI_ENDPOINT`, `OPENFDA_API_KEY`, and (if enabling tracing)
  `LANGFUSE_PUBLIC_KEY` / `LANGFUSE_SECRET_KEY`.
- A domain + hosted zone in Route 53 if you want a real DNS name and HTTPS
  (optional — the ALB's own DNS name works without one, HTTP only).

## 1. Naming conventions ("namespaces")

Two distinct things both reasonably called "namespace" apply here — this
runbook uses both:

1. **ECR repository namespacing** — group the two images under one prefix so
   they read as one application in the registry:
   - `cardiology-agent/backend`
   - `cardiology-agent/frontend`
2. **Cloud Map / ECS Service Connect namespace** — the private DNS namespace
   ECS services use to find each other without going back out through the
   ALB. This runbook creates `cardiology.local` and has the frontend reach the
   backend at `http://backend:8000` inside it — the same hostname pattern the
   project's `docker-compose.yml` already uses (`FASTAPI_URL: http://backend:8000`),
   so no application code changes are needed, only the env var's target
   changes from a Compose service name to a Service Connect one.

Suggested resource naming across the rest of this runbook:
`cardiology-agent-<resource>` (cluster, ALB, target groups, security groups,
log groups) so everything is identifiable and groupable in the console/cost
explorer.

## 2. Target architecture

```
Internet
   |
   v
[Route 53 alias]  (optional)
   |
   v
[Application Load Balancer]  -- public subnets, 2 AZs
   |                       |
   | /api/*                | / (default)
   v                       v
[backend-tg :8000]     [frontend-tg :8501]
   |                       |
   v                       v
[ECS Service: backend]  [ECS Service: frontend]     -- private subnets, 2 AZs
   |  (Fargate, awsvpc)     |  (Fargate, awsvpc)
   |                        |
   +--- Service Connect: frontend calls http://backend:8000 internally -----+
   |
   v
[NAT Gateway] --> Internet: OpenFDA API, Azure OpenAI, OpenSearch Serverless
   |
   v
[DynamoDB / OpenSearch Serverless via IAM task role, SigV4]
```

Both services run as **Fargate** tasks (serverless containers) inside one
**ECS cluster**, in **private subnets**, reachable from the internet only
through the **ALB** in **public subnets**. Outbound calls to external
services (OpenFDA, Azure OpenAI) go through a **NAT Gateway**. AWS-internal
calls (DynamoDB, OpenSearch Serverless) are authenticated via the task's
**IAM role**, not stored credentials — no `~/.aws` volume mount like local
Docker Compose uses.

## 3. VPC & networking

Reuse an existing VPC if you have one with public + private subnets across 2+
AZs; otherwise create one:

```bash
aws ec2 create-vpc --cidr-block 10.20.0.0/16 --region <REGION> \
  --tag-specifications 'ResourceType=vpc,Tags=[{Key=Name,Value=cardiology-agent-vpc}]'

# 2 public subnets (ALB, NAT Gateway)
aws ec2 create-subnet --vpc-id <VPC_ID> --cidr-block 10.20.0.0/24 --availability-zone <REGION>a \
  --tag-specifications 'ResourceType=subnet,Tags=[{Key=Name,Value=cardiology-agent-public-a}]'
aws ec2 create-subnet --vpc-id <VPC_ID> --cidr-block 10.20.1.0/24 --availability-zone <REGION>b \
  --tag-specifications 'ResourceType=subnet,Tags=[{Key=Name,Value=cardiology-agent-public-b}]'

# 2 private subnets (ECS tasks)
aws ec2 create-subnet --vpc-id <VPC_ID> --cidr-block 10.20.10.0/24 --availability-zone <REGION>a \
  --tag-specifications 'ResourceType=subnet,Tags=[{Key=Name,Value=cardiology-agent-private-a}]'
aws ec2 create-subnet --vpc-id <VPC_ID> --cidr-block 10.20.11.0/24 --availability-zone <REGION>b \
  --tag-specifications 'ResourceType=subnet,Tags=[{Key=Name,Value=cardiology-agent-private-b}]'
```

Then: internet gateway attached to the VPC + route to `0.0.0.0/0` for the
public subnets; a NAT Gateway in one public subnet with an Elastic IP + a
route from the private subnets' route table to it. (Standard VPC wiring —
omitted here for length; the AWS VPC wizard or a Terraform/CDK module covers
this in one step if you'd rather not do it by hand.)

**Cost tip**: add VPC Gateway Endpoints for DynamoDB and S3 (free, no NAT
data-processing charges for that traffic):

```bash
aws ec2 create-vpc-endpoint --vpc-id <VPC_ID> --service-name com.amazonaws.<REGION>.dynamodb \
  --route-table-ids <PRIVATE_RT_ID> --vpc-endpoint-type Gateway
```

OpenSearch Serverless (`aoss`) doesn't have a Gateway endpoint option under
the current **public** network policy this project uses (see
`opensearch-serverless.md`) — that traffic goes out through the NAT Gateway
like OpenFDA and Azure OpenAI do.

## 4. Security groups

```bash
# ALB: public HTTP/HTTPS in
aws ec2 create-security-group --group-name cardiology-agent-alb-sg \
  --description "ALB ingress" --vpc-id <VPC_ID>
aws ec2 authorize-security-group-ingress --group-id <ALB_SG_ID> --protocol tcp --port 80 --cidr 0.0.0.0/0
aws ec2 authorize-security-group-ingress --group-id <ALB_SG_ID> --protocol tcp --port 443 --cidr 0.0.0.0/0

# backend service: only from the ALB and from the frontend service
aws ec2 create-security-group --group-name cardiology-agent-backend-sg \
  --description "backend ingress" --vpc-id <VPC_ID>
aws ec2 authorize-security-group-ingress --group-id <BACKEND_SG_ID> --protocol tcp --port 8000 --source-group <ALB_SG_ID>
aws ec2 authorize-security-group-ingress --group-id <BACKEND_SG_ID> --protocol tcp --port 8000 --source-group <FRONTEND_SG_ID>

# frontend service: only from the ALB
aws ec2 create-security-group --group-name cardiology-agent-frontend-sg \
  --description "frontend ingress" --vpc-id <VPC_ID>
aws ec2 authorize-security-group-ingress --group-id <FRONTEND_SG_ID> --protocol tcp --port 8501 --source-group <ALB_SG_ID>
```

(`<FRONTEND_SG_ID>` is created before the backend rule that references it, or
add that one rule after both groups exist.)

## 5. ECR: create repos, build, tag, push

```bash
aws ecr create-repository --repository-name cardiology-agent/backend --region <REGION>
aws ecr create-repository --repository-name cardiology-agent/frontend --region <REGION>

aws ecr get-login-password --region <REGION> \
  | docker login --username AWS --password-stdin <ACCOUNT_ID>.dkr.ecr.<REGION>.amazonaws.com

# Tag with the git SHA (or a semantic version) -- never deploy floating "latest"
TAG=$(git rev-parse --short HEAD)

docker build -f Dockerfile.backend -t <ACCOUNT_ID>.dkr.ecr.<REGION>.amazonaws.com/cardiology-agent/backend:$TAG .
docker push <ACCOUNT_ID>.dkr.ecr.<REGION>.amazonaws.com/cardiology-agent/backend:$TAG

docker build -f Dockerfile.frontend -t <ACCOUNT_ID>.dkr.ecr.<REGION>.amazonaws.com/cardiology-agent/frontend:$TAG .
docker push <ACCOUNT_ID>.dkr.ecr.<REGION>.amazonaws.com/cardiology-agent/frontend:$TAG
```

Both Dockerfiles already `COPY . .` and install from `requirements.txt` — no
changes needed to build for ECS specifically, but note both currently `COPY`
the *entire* repo (including `tests/`, `.git`, etc.); adding a `.dockerignore`
before the production build is worth doing to shrink the image, though not
required to deploy.

## 6. IAM: task execution role + task role

Two different roles, two different jobs — ECS conflates them if you're not
careful, but they're not the same thing:

- **Execution role**: used by the *ECS agent itself* to pull the image from
  ECR and write logs to CloudWatch. Not visible to your application code.
- **Task role**: assumed by *your application* at runtime — this is what
  boto3's default credential chain picks up inside the container, replacing
  the `~/.aws` volume mount local Docker Compose uses.

```bash
# Execution role -- trust policy allows ecs-tasks.amazonaws.com to assume it
aws iam create-role --role-name cardiology-agent-ecs-execution-role \
  --assume-role-policy-document file://ecs-trust-policy.json
aws iam attach-role-policy --role-name cardiology-agent-ecs-execution-role \
  --policy-arn arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy
# + the secrets-read policy created in step 7, attached after that secret exists

# Task role -- same trust policy, different permissions
aws iam create-role --role-name cardiology-agent-ecs-task-role \
  --assume-role-policy-document file://ecs-trust-policy.json
```

`ecs-trust-policy.json`:

```json
{
  "Version": "2012-10-17",
  "Statement": [{
    "Effect": "Allow",
    "Principal": { "Service": "ecs-tasks.amazonaws.com" },
    "Action": "sts:AssumeRole"
  }]
}
```

Task role permissions (only the backend container needs these — the frontend
task role can be empty/minimal):

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": ["dynamodb:GetItem", "dynamodb:Query", "dynamodb:PutItem"],
      "Resource": "arn:aws:dynamodb:<REGION>:<ACCOUNT_ID>:table/PatientClinicalRecords"
    },
    {
      "Effect": "Allow",
      "Action": "aoss:APIAccessAll",
      "Resource": "arn:aws:aoss:<REGION>:<ACCOUNT_ID>:collection/<COLLECTION_ID>"
    }
  ]
}
```

**Don't skip this**: the OpenSearch Serverless collection's **data access
policy** (`cardiology-agent-access`, a resource-level policy separate from
IAM — see `opensearch-serverless.md`) also has to be updated to grant this
new task role's ARN read/write on the index, the same way it currently grants
the SSO admin role used for local development:

```bash
aws opensearchserverless update-access-policy --name cardiology-agent-access --type data \
  --policy-version <CURRENT_VERSION> \
  --policy '[{"Rules":[{"ResourceType":"index","Resource":["index/cardiology-agent-rag/*"],"Permission":["aoss:*"]}],
              "Principal":["arn:aws:iam::<ACCOUNT_ID>:role/cardiology-agent-ecs-task-role", "<existing principals...>"]}]'
```

Skipping this step is the single most likely way this deployment silently
loses RAG functionality in production (same failure mode as the local
AuthorizationException hit earlier in this project's OpenSearch migration —
see the "Two issues hit and fixed" section of `opensearch-serverless.md`).

## 7. Secrets Manager

Store every real key here rather than as plaintext task-definition
environment variables — `environment` values in a task definition are
visible in plain text to anyone who can call `DescribeTaskDefinition`
(including anyone with read-only ECS console access); `secrets` values are
not, and access is governed by IAM instead.

Four keys the backend needs at runtime: `AZURE_OPENAI_API_KEY`,
`OPENFDA_API_KEY`, `LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY`.

### 7.1 Create one consolidated secret

Rather than four separate Secrets Manager resources (each billed
individually, ~$0.40/secret/month), store them as one JSON secret and
reference individual keys from it in the task definition — the standard
pattern for a handful of related app-level secrets:

```bash
aws secretsmanager create-secret \
  --name cardiology-agent/app-secrets \
  --description "Runtime API keys for the cardiology-agent backend" \
  --tags Key=Project,Value=cardiology-agent Key=Environment,Value=production \
  --secret-string '{
    "AZURE_OPENAI_API_KEY": "<value>",
    "OPENFDA_API_KEY": "<value>",
    "LANGFUSE_PUBLIC_KEY": "<value>",
    "LANGFUSE_SECRET_KEY": "<value>"
  }'
```

Capture the ARN it returns (or fetch it separately) — task definitions should
reference the full ARN, not just the name, so an accidental same-named secret
elsewhere in the account can't get picked up instead:

```bash
SECRET_ARN=$(aws secretsmanager describe-secret \
  --secret-id cardiology-agent/app-secrets --query ARN --output text)
```

By default this is encrypted with the AWS-managed `aws/secretsmanager` KMS
key, which is fine for this use case and needs no extra key policy work (see
7.3). Use `--kms-key-id` at creation time instead if your org requires a
customer-managed key for audit/rotation-policy reasons.

**Alternative**: if you'd rather have separate IAM blast-radius boundaries
per key (e.g. a different team owns the Langfuse keys), create four secrets
instead — `cardiology-agent/azure-openai-api-key`,
`cardiology-agent/openfda-api-key`, `cardiology-agent/langfuse-public-key`,
`cardiology-agent/langfuse-secret-key` — and reference each directly in the
task definition's `secrets` block without a `:key::` suffix. Functionally
equivalent, just four resources instead of one.

### 7.2 Reference individual keys in the task definition

Pull one field out of a JSON secret with the `<secret-arn>:<json-key>::`
suffix syntax — this is what step 11's backend task definition uses:

```json
"secrets": [
  { "name": "AZURE_OPENAI_API_KEY", "valueFrom": "<SECRET_ARN>:AZURE_OPENAI_API_KEY::" },
  { "name": "OPENFDA_API_KEY",      "valueFrom": "<SECRET_ARN>:OPENFDA_API_KEY::" },
  { "name": "LANGFUSE_PUBLIC_KEY",  "valueFrom": "<SECRET_ARN>:LANGFUSE_PUBLIC_KEY::" },
  { "name": "LANGFUSE_SECRET_KEY",  "valueFrom": "<SECRET_ARN>:LANGFUSE_SECRET_KEY::" }
]
```

The ECS agent resolves these at container *start*, injecting each as a
regular environment variable inside the container — the application code
(`AzureOpenAIConfig`, `OpenFDAService`, Langfuse's client) reads them via
`os.environ` exactly as it does locally, no code changes needed.

### 7.3 Grant the execution role read access

The **execution role**, not the task role, needs this — it's the ECS agent
that resolves `secrets` entries before the container starts, not your
application code:

```bash
cat > secrets-read-policy.json <<EOF
{
  "Version": "2012-10-17",
  "Statement": [{
    "Effect": "Allow",
    "Action": "secretsmanager:GetSecretValue",
    "Resource": "$SECRET_ARN"
  }]
}
EOF

aws iam put-role-policy --role-name cardiology-agent-ecs-execution-role \
  --policy-name cardiology-agent-secrets-read \
  --policy-document file://secrets-read-policy.json
```

Scoped to the one secret's exact ARN, not `"Resource": "*"`. If using the
default `aws/secretsmanager` KMS key, `secretsmanager:GetSecretValue` alone
is enough — no separate `kms:Decrypt` grant needed. Switching to a
customer-managed KMS key means the execution role also needs `kms:Decrypt`
on that key's policy.

### 7.4 Updating a key later

Task definitions resolve secrets once, at container start — updating the
secret's value does **not** hot-reload into already-running tasks:

```bash
aws secretsmanager update-secret --secret-id cardiology-agent/app-secrets \
  --secret-string '{"AZURE_OPENAI_API_KEY": "<new-value>", "OPENFDA_API_KEY": "<value>", "LANGFUSE_PUBLIC_KEY": "<value>", "LANGFUSE_SECRET_KEY": "<value>"}'

# then force running tasks to pick it up:
aws ecs update-service --cluster cardiology-agent-cluster \
  --service cardiology-agent-backend --force-new-deployment
```

(`update-secret` replaces the whole JSON blob — include all four keys each
time, not just the one changing.) Secrets Manager's native automatic
rotation (Lambda-triggered) is built for RDS/native AWS credentials; these
are external API keys with no AWS-side rotator, so rotation here is this
manual update-then-redeploy, on whatever cadence your key-rotation policy
requires.

### 7.5 Cleanup

```bash
aws secretsmanager delete-secret --secret-id cardiology-agent/app-secrets \
  --recovery-window-in-days 7   # or --force-delete-without-recovery for immediate
```

## 8. CloudWatch log groups

```bash
aws logs create-log-group --log-group-name /ecs/cardiology-agent/backend
aws logs create-log-group --log-group-name /ecs/cardiology-agent/frontend
```

## 9. Cloud Map namespace + Service Connect

```bash
aws servicediscovery create-http-namespace --name cardiology.local
```

This namespace is attached at the **service** level in step 12 (ECS Service
Connect config), not as a separate resource per service — no further setup
needed here.

## 10. ECS cluster

```bash
aws ecs create-cluster --cluster-name cardiology-agent-cluster \
  --capacity-providers FARGATE FARGATE_SPOT \
  --settings name=containerInsights,value=enabled
```

`containerInsights` is optional but worth it for CPU/memory dashboards
without extra setup.

## 11. Task definitions

`<SECRET_ARN>` below is the `cardiology-agent/app-secrets` ARN captured in
step 7.1.

**Backend** (`backend-task-def.json`):

```json
{
  "family": "cardiology-agent-backend",
  "networkMode": "awsvpc",
  "requiresCompatibilities": ["FARGATE"],
  "cpu": "512",
  "memory": "1024",
  "executionRoleArn": "arn:aws:iam::<ACCOUNT_ID>:role/cardiology-agent-ecs-execution-role",
  "taskRoleArn": "arn:aws:iam::<ACCOUNT_ID>:role/cardiology-agent-ecs-task-role",
  "containerDefinitions": [{
    "name": "backend",
    "image": "<ACCOUNT_ID>.dkr.ecr.<REGION>.amazonaws.com/cardiology-agent/backend:<TAG>",
    "portMappings": [{ "containerPort": 8000, "name": "backend" }],
    "essential": true,
    "environment": [
      { "name": "AWS_REGION", "value": "<REGION>" },
      { "name": "DYNAMODB_PATIENT_TABLE", "value": "PatientClinicalRecords" },
      { "name": "OPENFDA_BASE_URL", "value": "https://api.fda.gov/drug/label.json" },
      { "name": "OPENFDA_TIMEOUT_SECONDS", "value": "10" },
      { "name": "AZURE_OPENAI_ENDPOINT", "value": "https://<your-resource>.cognitiveservices.azure.com" },
      { "name": "AZURE_OPENAI_API_VERSION", "value": "2024-08-01-preview" },
      { "name": "AZURE_OPENAI_DEPLOYMENT_NAME", "value": "gpt-4.1-mini" },
      { "name": "AZURE_OPENAI_EMBEDDING_DEPLOYMENT_NAME", "value": "text-embedding-3-small" },
      { "name": "AZURE_OPENAI_EMBEDDING_MODEL", "value": "text-embedding-3-small" },
      { "name": "OPENSEARCH_HOST", "value": "<collection-id>.<REGION>.aoss.amazonaws.com" },
      { "name": "OPENSEARCH_INDEX", "value": "cardiology-approved-documents" },
      { "name": "RAG_EMBEDDING_DIMENSIONS", "value": "1536" },
      { "name": "LANGFUSE_ENABLED", "value": "true" },
      { "name": "LANGFUSE_HOST", "value": "https://cloud.langfuse.com" },
      { "name": "LOG_LEVEL", "value": "INFO" },
      { "name": "CORS_ORIGINS", "value": "https://<your-frontend-domain>" }
    ],
    "secrets": [
      { "name": "AZURE_OPENAI_API_KEY", "valueFrom": "<SECRET_ARN>:AZURE_OPENAI_API_KEY::" },
      { "name": "OPENFDA_API_KEY", "valueFrom": "<SECRET_ARN>:OPENFDA_API_KEY::" },
      { "name": "LANGFUSE_PUBLIC_KEY", "valueFrom": "<SECRET_ARN>:LANGFUSE_PUBLIC_KEY::" },
      { "name": "LANGFUSE_SECRET_KEY", "valueFrom": "<SECRET_ARN>:LANGFUSE_SECRET_KEY::" }
    ],
    "logConfiguration": {
      "logDriver": "awslogs",
      "options": {
        "awslogs-group": "/ecs/cardiology-agent/backend",
        "awslogs-region": "<REGION>",
        "awslogs-stream-prefix": "backend"
      }
    },
    "healthCheck": {
      "command": ["CMD-SHELL", "python -c \"import urllib.request; urllib.request.urlopen('http://localhost:8000/health')\" || exit 1"],
      "interval": 30, "timeout": 5, "retries": 3, "startPeriod": 10
    }
  }]
}
```

**Frontend** (`frontend-task-def.json`) — the key difference from
`docker-compose.yml` is `FASTAPI_URL`, which now points at the Service
Connect DNS name instead of the Compose service name (same hostname pattern,
different underlying mechanism):

```json
{
  "family": "cardiology-agent-frontend",
  "networkMode": "awsvpc",
  "requiresCompatibilities": ["FARGATE"],
  "cpu": "256",
  "memory": "512",
  "executionRoleArn": "arn:aws:iam::<ACCOUNT_ID>:role/cardiology-agent-ecs-execution-role",
  "taskRoleArn": "arn:aws:iam::<ACCOUNT_ID>:role/cardiology-agent-ecs-task-role",
  "containerDefinitions": [{
    "name": "frontend",
    "image": "<ACCOUNT_ID>.dkr.ecr.<REGION>.amazonaws.com/cardiology-agent/frontend:<TAG>",
    "portMappings": [{ "containerPort": 8501, "name": "frontend" }],
    "essential": true,
    "environment": [
      { "name": "FASTAPI_URL", "value": "http://backend:8000" },
      { "name": "API_TIMEOUT", "value": "30" }
    ],
    "logConfiguration": {
      "logDriver": "awslogs",
      "options": {
        "awslogs-group": "/ecs/cardiology-agent/frontend",
        "awslogs-region": "<REGION>",
        "awslogs-stream-prefix": "frontend"
      }
    },
    "healthCheck": {
      "command": ["CMD-SHELL", "python -c \"import urllib.request; urllib.request.urlopen('http://localhost:8501/_stcore/health')\" || exit 1"],
      "interval": 30, "timeout": 5, "retries": 3, "startPeriod": 15
    }
  }]
}
```

Register both:

```bash
aws ecs register-task-definition --cli-input-json file://backend-task-def.json
aws ecs register-task-definition --cli-input-json file://frontend-task-def.json
```

## 12. Application Load Balancer, target groups, listeners

```bash
aws elbv2 create-load-balancer --name cardiology-agent-alb \
  --subnets <PUBLIC_SUBNET_A> <PUBLIC_SUBNET_B> \
  --security-groups <ALB_SG_ID> --scheme internet-facing --type application

aws elbv2 create-target-group --name cardiology-agent-backend-tg \
  --protocol HTTP --port 8000 --vpc-id <VPC_ID> --target-type ip \
  --health-check-path /health --health-check-interval-seconds 30

aws elbv2 create-target-group --name cardiology-agent-frontend-tg \
  --protocol HTTP --port 8501 --vpc-id <VPC_ID> --target-type ip \
  --health-check-path /_stcore/health --health-check-interval-seconds 30

# HTTP listener, default action -> frontend
aws elbv2 create-listener --load-balancer-arn <ALB_ARN> --protocol HTTP --port 80 \
  --default-actions Type=forward,TargetGroupArn=<FRONTEND_TG_ARN>

# Path rule: anything under /api/* -> backend
aws elbv2 create-rule --listener-arn <LISTENER_ARN> --priority 10 \
  --conditions Field=path-pattern,Values='/api/*' \
  --actions Type=forward,TargetGroupArn=<BACKEND_TG_ARN>
```

`target-type ip` is required for Fargate (tasks don't have a fixed EC2
instance to register by ID). If you expose the backend at `/api/*` behind the
ALB, note the FastAPI app's routes don't currently have an `/api` prefix
(`/query`, `/patient/...`, `/patients`, `/rag/documents` are all at root) — either
add a path-stripping rule at the ALB, put a prefix on the FastAPI routes, or
route the backend on a separate subdomain instead (`api.<domain>` →
backend-tg with no path rewriting needed). Decide this before wiring the
listener rule for real.

## 13. HTTPS (optional but recommended)

```bash
aws acm request-certificate --domain-name <your-domain> --validation-method DNS
# validate via the DNS CNAME ACM gives you, then:
aws elbv2 create-listener --load-balancer-arn <ALB_ARN> --protocol HTTPS --port 443 \
  --certificates CertificateArn=<CERT_ARN> \
  --default-actions Type=forward,TargetGroupArn=<FRONTEND_TG_ARN>
# redirect plain HTTP -> HTTPS
aws elbv2 modify-listener --listener-arn <HTTP_LISTENER_ARN> \
  --default-actions Type=redirect,RedirectConfig='{Protocol=HTTPS,Port=443,StatusCode=HTTP_301}'
```

## 14. ECS services (with Service Connect)

```bash
aws ecs create-service \
  --cluster cardiology-agent-cluster \
  --service-name cardiology-agent-backend \
  --task-definition cardiology-agent-backend \
  --desired-count 2 \
  --launch-type FARGATE \
  --network-configuration "awsvpcConfiguration={subnets=[<PRIVATE_SUBNET_A>,<PRIVATE_SUBNET_B>],securityGroups=[<BACKEND_SG_ID>],assignPublicIp=DISABLED}" \
  --load-balancers "targetGroupArn=<BACKEND_TG_ARN>,containerName=backend,containerPort=8000" \
  --service-connect-configuration '{
    "enabled": true,
    "namespace": "cardiology.local",
    "services": [{ "portName": "backend", "discoveryName": "backend", "clientAliases": [{ "port": 8000 }] }]
  }'

aws ecs create-service \
  --cluster cardiology-agent-cluster \
  --service-name cardiology-agent-frontend \
  --task-definition cardiology-agent-frontend \
  --desired-count 2 \
  --launch-type FARGATE \
  --network-configuration "awsvpcConfiguration={subnets=[<PRIVATE_SUBNET_A>,<PRIVATE_SUBNET_B>],securityGroups=[<FRONTEND_SG_ID>],assignPublicIp=DISABLED}" \
  --load-balancers "targetGroupArn=<FRONTEND_TG_ARN>,containerName=frontend,containerPort=8501" \
  --service-connect-configuration '{
    "enabled": true,
    "namespace": "cardiology.local",
    "services": [{ "portName": "frontend", "discoveryName": "frontend", "clientAliases": [{ "port": 8501 }] }]
  }'
```

`desired-count 2` for both, spread across the two private subnets/AZs by
default, so a single AZ outage doesn't take the app down. Both services now
sit "under" `cardiology-agent-cluster` and are reachable from each other at
`http://backend:8000` / `http://frontend:8501` via Service Connect, and from
the internet via the ALB.

## 15. Auto scaling (optional)

```bash
aws application-autoscaling register-scalable-target \
  --service-namespace ecs --resource-id service/cardiology-agent-cluster/cardiology-agent-backend \
  --scalable-dimension ecs:service:DesiredCount --min-capacity 2 --max-capacity 6

aws application-autoscaling put-scaling-policy \
  --service-namespace ecs --resource-id service/cardiology-agent-cluster/cardiology-agent-backend \
  --scalable-dimension ecs:service:DesiredCount --policy-name backend-cpu-tracking \
  --policy-type TargetTrackingScaling \
  --target-tracking-scaling-policy-configuration '{
    "TargetValue": 60.0,
    "PredefinedMetricSpecification": { "PredefinedMetricType": "ECSServiceAverageCPUUtilization" }
  }'
```

Repeat for the frontend service with its own resource-id if desired (the
Streamlit frontend is unlikely to need it as much as the backend, which does
the LLM/tool-call work).

## 16. DNS (optional)

```bash
aws route53 change-resource-record-sets --hosted-zone-id <ZONE_ID> --change-batch '{
  "Changes": [{ "Action": "UPSERT", "ResourceRecordSet": {
    "Name": "<your-domain>", "Type": "A",
    "AliasTarget": { "HostedZoneId": "<ALB_HOSTED_ZONE_ID>", "DNSName": "<ALB_DNS_NAME>", "EvaluateTargetHealth": true }
  }}]
}'
```

## 17. Verification checklist

- [ ] `aws ecs describe-services --cluster cardiology-agent-cluster --services cardiology-agent-backend cardiology-agent-frontend` — both `runningCount == desiredCount`, no stopped tasks looping
- [ ] Target groups healthy: `aws elbv2 describe-target-health --target-group-arn <BACKEND_TG_ARN>` / `<FRONTEND_TG_ARN>`
- [ ] `curl http://<alb-dns-name>/health` → `{"status":"healthy",...}`
- [ ] Open the frontend in a browser at the ALB DNS name (or your domain), register a test patient, ask a question, confirm the "thinking" trace and an answer come back
- [ ] `GET /rag/documents` returns all 15 documents (confirms the OpenSearch Serverless data access policy update in step 6 actually took)
- [ ] CloudWatch Logs (`/ecs/cardiology-agent/backend`, `/ecs/cardiology-agent/frontend`) show clean startup, no `NoCredentialsError` / `AuthorizationException`
- [ ] Delete the test patient/data created during verification

## 18. CI/CD (brief — not detailed here)

A minimal pipeline: on push to `main`, build both images tagged with the git
SHA, push to ECR, then `aws ecs update-service --cluster cardiology-agent-cluster
--service cardiology-agent-backend --task-definition cardiology-agent-backend:<new-revision>
--force-new-deployment` for each service. GitHub Actions with the
`aws-actions/amazon-ecs-deploy-task-definition` action is the standard way to
do this; out of scope to fully write up here, flagged as a natural next step.

## 19. Cost notes / cleanup

Standing costs once this is live: 2 NAT Gateway hours + data processing, ALB
hours + LCU usage, 4 Fargate tasks (2 backend + 2 frontend) around the clock,
CloudWatch Logs storage. DynamoDB and OpenSearch Serverless are already
pay-per-use per `opensearch-serverless.md`. If this is a demo/eval
environment rather than a real production deployment, consider `desired-count
1` for both services and skip the second NAT Gateway (single AZ) to cut
costs — document that tradeoff explicitly if you do, since it removes the
multi-AZ resilience described in step 14.

To tear down: delete the ECS services (sets desired count to 0 first), delete
the cluster, deregister task definitions, delete the ALB + target groups,
delete the NAT Gateway + release its Elastic IP, delete the Cloud Map
namespace, delete the ECR repos (or just the images, keep the repos), and
remove the task role's grant from the OpenSearch Serverless data access
policy. The DynamoDB table and OpenSearch Serverless collection are
independent of this teardown — leave them alone unless you're decommissioning
the whole project.
