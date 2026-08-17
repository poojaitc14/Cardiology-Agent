# Deploying to AWS: ECR + ECS (Fargate) via the Console

Companion to [`aws-ecs-deployment.md`](aws-ecs-deployment.md) — same end
result, same resources, same section order for easy cross-reference, but
every step done by clicking through the AWS Console in a browser instead of
running AWS CLI commands.

Status: **planning document only — nothing has been done.**

**One unavoidable exception**: pushing a Docker image to ECR requires the
Docker CLI in a terminal — there is no browser-based image upload. The ECR
console generates the exact copy-paste commands for that one step (section
5); every other step below is done entirely in browser tabs.

Want to skip creating a new VPC/subnets/NAT Gateway and reuse the account's
existing default VPC instead? See
[`aws-ecs-deployment-no-new-vpc-console.md`](aws-ecs-deployment-no-new-vpc-console.md)
— a delta doc covering just the sections that change; everything else here
stays the same.

---

## 0. Prerequisites

- AWS account with console access and permission to create VPC, IAM, ECR,
  ECS, ELB, Secrets Manager, and Cloud Map resources (or an admin login for a
  first pass).
- Docker Desktop installed locally, for the one terminal step in section 5.
- The real secret values ready to paste in: Azure OpenAI key, OpenFDA key,
  Langfuse public/secret keys.
- (Optional) a domain registered/hosted in Route 53, for real DNS + HTTPS.

## 1. Naming conventions ("namespaces")

Same as the CLI doc — no console action here, just names to use consistently
as you click through the wizards below:

- ECR repos: `cardiology-agent/backend`, `cardiology-agent/frontend`
- Cloud Map / Service Connect namespace: `cardiology.local`, with the
  frontend reaching the backend at `http://backend:8000` inside it — the same
  hostname pattern `docker-compose.yml` already uses locally.
- Everything else prefixed `cardiology-agent-<resource>` (cluster, ALB,
  target groups, security groups, log groups, roles).

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

## 3. VPC & networking

1. **VPC console → Your VPCs → Create VPC.**
2. Choose the **"VPC and more"** option (not "VPC only") — this wizard
   creates subnets, route tables, an internet gateway, and NAT gateway(s) in
   one pass instead of one resource at a time.
3. Fill in:
   - Name tag auto-generation: `cardiology-agent`
   - IPv4 CIDR block: `10.20.0.0/16`
   - Number of Availability Zones: **2**
   - Number of public subnets: **2**
   - Number of private subnets: **2**
   - NAT gateways: **"1 per AZ"** for full resilience, or **"In 1 AZ"** to
     save cost on a demo/eval environment (see section 19's tradeoff note —
     the same one-vs-two-NAT decision as the CLI doc)
   - VPC endpoints: check **S3 Gateway** (free, no reason not to)
4. Click **Create VPC**.
5. Add a DynamoDB Gateway endpoint separately (free, avoids NAT charges for
   that traffic): **VPC console → Endpoints → Create endpoint** → search
   "dynamodb" → select the **Gateway** type endpoint for
   `com.amazonaws.<region>.dynamodb` → select your new VPC → check both
   private route tables → **Create endpoint**.

OpenSearch Serverless (`aoss`) has no Gateway/Interface endpoint option under
this project's **public** network policy (see `opensearch-serverless.md`) —
that traffic goes out through the NAT Gateway like OpenFDA and Azure OpenAI.

## 4. Security groups

**EC2 console → Security Groups → Create security group**, three times:

1. **`cardiology-agent-alb-sg`** — VPC: the one you just created.
   Inbound rules: HTTP (80) from `0.0.0.0/0`; HTTPS (443) from `0.0.0.0/0` if
   doing HTTPS (section 13).
2. **`cardiology-agent-frontend-sg`** — inbound rule: Custom TCP, port 8501,
   source = `cardiology-agent-alb-sg` (search and select it by name in the
   source field, not a raw CIDR).
3. **`cardiology-agent-backend-sg`** — inbound rule: Custom TCP, port 8000,
   source = `cardiology-agent-alb-sg`; **add a second inbound rule**, Custom
   TCP port 8000, source = `cardiology-agent-frontend-sg`.

(Create frontend-sg before backend-sg's second rule, since that rule needs to
reference it — or create backend-sg first and come back to edit its inbound
rules afterward.)

## 5. ECR: create repos, then push (the one terminal step)

1. **ECR console → Repositories → Create repository.** Name:
   `cardiology-agent/backend`. Leave "Scan on push" on if you want automatic
   vulnerability scanning. Create. Repeat for `cardiology-agent/frontend`.
2. Click into `cardiology-agent/backend` → **"View push commands"** button
   (top right) — it prints the exact `docker login` / `build` / `tag` /
   `push` commands for your OS, with your account ID and region already
   filled in. Run those in a terminal, from the project root, adjusting the
   `docker build` line to point at `Dockerfile.backend`:
   ```
   docker build -f Dockerfile.backend -t cardiology-agent/backend .
   ```
3. Repeat "View push commands" and the build/push for the frontend repo,
   using `Dockerfile.frontend`.
4. Refresh each repository's page — the pushed image tag/digest should now
   be listed under "Images." Note the **image URI** shown there (you'll paste
   it into the task definition in section 11).

## 6. IAM: task execution role + task role

1. **IAM console → Roles → Create role.**
   - Trusted entity type: **AWS service**
   - Use case: **Elastic Container Service → Elastic Container Service Task**
   - Next.
2. **Execution role**: on the permissions page, attach
   `AmazonECSTaskExecutionRolePolicy`. Name it
   `cardiology-agent-ecs-execution-role`. Create role. (You'll come back to
   add an inline secrets-read policy once the secret exists — section 7.)
3. **Task role**: repeat the role wizard, but on the permissions page click
   **"Create inline policy"** instead → JSON tab → paste:
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
   Name the policy `cardiology-agent-task-permissions`, name the role
   `cardiology-agent-ecs-task-role`, Create role.
4. **Don't skip this**: **OpenSearch Serverless console → Collections →
   `cardiology-agent-rag` → Data access** tab → open the
   `cardiology-agent-access` policy → **Edit** → add the new task role's ARN
   (`arn:aws:iam::<ACCOUNT_ID>:role/cardiology-agent-ecs-task-role`) as an
   additional principal on the existing rule (or add a new rule) → **Save**.
   Skipping this is the single most likely way this deployment silently loses
   RAG functionality in production — same failure mode as the local
   `AuthorizationException` hit earlier in this project's OpenSearch
   migration (see the "Two issues hit and fixed" section of
   `opensearch-serverless.md`).

## 7. Secrets Manager

1. **Secrets Manager console → Store a new secret.**
   - Secret type: **Other type of secret**
   - **Key/value pairs** tab → add four rows: `AZURE_OPENAI_API_KEY`,
     `OPENFDA_API_KEY`, `LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY`, pasting
     the real value into each
   - Encryption key: leave the default `aws/secretsmanager` (fine for this
     use case, needs no extra key-policy work)
   - Next.
2. Secret name: `cardiology-agent/app-secrets`. Add a description. Next.
3. Rotation: skip (no AWS-native rotator applies to external API keys —
   see section 7's "updating a key later" note below). Next → Review →
   **Store**.
4. Click into the secret → copy the **Secret ARN** shown near the top. Save
   it somewhere — you'll need it in section 11 (task definition) and the
   next step.
5. Back in **IAM console → Roles → `cardiology-agent-ecs-execution-role`** →
   Add permissions → **Create inline policy** → JSON tab:
   ```json
   {
     "Version": "2012-10-17",
     "Statement": [{
       "Effect": "Allow",
       "Action": "secretsmanager:GetSecretValue",
       "Resource": "<SECRET_ARN>"
     }]
   }
   ```
   Name it `cardiology-agent-secrets-read`, Create policy. Scoped to the one
   secret's exact ARN, not `"Resource": "*"`.

**Alternative**: create four separate secrets instead of one JSON blob if you
want stricter per-key IAM boundaries — functionally equivalent, just four
resources to manage (and four times the monthly per-secret cost) instead of
one.

**Updating a key later**: task definitions resolve secrets once, at
container start. In the console: open the secret → **Retrieve secret value →
Edit** → change the value → Save. Then **ECS console → cluster → Services →
cardiology-agent-backend → Update service → check "Force new deployment" →
Update** — running tasks won't pick up the new value without this.

## 8. CloudWatch log groups

Usually not a separate step — the ECS task-definition wizard in section 11
can create the log group for you inline. To pre-create manually:
**CloudWatch console → Log groups → Create log group** → name
`/ecs/cardiology-agent/backend` → retention (e.g. 30 days) → Create. Repeat
for `/ecs/cardiology-agent/frontend`.

## 9. Cloud Map namespace

Also usually created inline — the ECS "Create service" wizard offers to
create a new namespace the first time you enable Service Connect (section
14). To pre-create it instead: **Cloud Map console → Create namespace** →
**API calls and DNS queries (HTTP)** → name `cardiology.local` → Create.

## 10. ECS cluster

**ECS console → Clusters → Create cluster.**
- Cluster name: `cardiology-agent-cluster`
- Infrastructure: check **AWS Fargate (serverless)**
- Monitoring: check **Use Container Insights** if you want CPU/memory
  dashboards without extra setup
- Create.

## 11. Task definitions

**ECS console → Task definitions → Create new task definition.**

The **JSON tab** is the fastest path in the console — paste the same JSON
from `aws-ecs-deployment.md` section 11, with your account ID, region, image
URI (from section 5), role ARNs (section 6), and `<SECRET_ARN>:KEY::` values
(section 7) filled in, then **Create**.

If you'd rather use the guided form instead of JSON:
1. Family name: `cardiology-agent-backend`
2. Launch type: **AWS Fargate**; task size **0.5 vCPU / 1 GB**
3. Task role and Task execution role: select the two roles from section 6
4. Container 1: name `backend`; image URI pasted from the ECR repo page
   ("Copy URI" button); container port `8000`
5. **Environment variables**: click "Add environment variable" once per row
   for every non-secret var listed in `aws-ecs-deployment.md` section 11
   (`AWS_REGION`, `DYNAMODB_PATIENT_TABLE`, `OPENSEARCH_HOST`, etc.)
6. **Secrets**: click "Add secret" — the console gives you a dedicated
   picker: select **Secrets Manager**, pick `cardiology-agent/app-secrets`
   from the dropdown, then pick the specific JSON key (e.g.
   `AZURE_OPENAI_API_KEY`) from a second dropdown. No manual ARN/suffix
   typing needed here, unlike the CLI/JSON path. Repeat for all four keys.
7. **HealthCheck**: command
   `CMD-SHELL,python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')" || exit 1`
8. **Logging**: toggle "Use log collection" — this auto-fills the `awslogs`
   driver and creates the log group from section 8 if it doesn't exist yet.
9. Create.

Repeat the whole thing for `cardiology-agent-frontend` (image from the
frontend ECR repo, container port `8501`, only `FASTAPI_URL=http://backend:8000`
and `API_TIMEOUT=30` as environment variables, no secrets, health check
against `/_stcore/health`, task size 0.25 vCPU / 0.5 GB).

## 12. Application Load Balancer, target groups, listeners

Two ways to get here:

**(a) Pre-create it standalone** (clearer for wiring two services to one ALB
with path rules):
1. **EC2 console → Load Balancers → Create load balancer → Application Load
   Balancer.**
2. Name `cardiology-agent-alb`; scheme **Internet-facing**; VPC = the one
   from section 3; mappings = the two **public** subnets.
3. Security group: `cardiology-agent-alb-sg`.
4. Listener HTTP:80 → under it, click **Create target group** (opens in a
   new tab):
   - Target type: **IP addresses** (required for Fargate — tasks have no
     fixed EC2 instance ID to register by)
   - Protocol/port: HTTP / 8000
   - Health check path: `/health`
   - Name: `cardiology-agent-backend-tg`
   - Next → skip registering targets manually (the ECS service does this) →
     Create target group.
5. Repeat for `cardiology-agent-frontend-tg` (port 8501, health check path
   `/_stcore/health`).
6. Back on the load balancer page, set listener HTTP:80's default action to
   forward to `cardiology-agent-frontend-tg` → **Create load balancer**.
7. **Load Balancers → cardiology-agent-alb → Listeners tab → view/edit rules
   → Add rule**: condition **Path** is `/api/*` → action **Forward to**
   `cardiology-agent-backend-tg` → priority `10` → Save.

**(b) Or skip this whole section** and let the ECS "Create service" wizard in
section 14 create the ALB, listener, and target group for you inline — faster
for a first single-service deployment, though doing it by hand as in (a) is
clearer once a second service needs to share the same ALB with a path rule.

Note: the backend's routes (`/query`, `/patient`, `/patients`,
`/rag/documents`) aren't currently under an `/api` prefix in the FastAPI app.
Routing `/api/*` at the ALB as written above needs either a path-rewrite
rule, adding that prefix to the app's routes, or using a separate
`api.<domain>` subdomain/listener instead — decide this before wiring the
rule for real, same flag as the CLI doc.

## 13. HTTPS (optional but recommended)

1. **Certificate Manager console → Request certificate → Request a public
   certificate.** Domain name: your domain. Validation method: **DNS**.
   Request.
2. Click into the certificate → **"Create records in Route 53"** button (one
   click, if your hosted zone is in the same account) → wait for status to
   flip to **Issued**.
3. **EC2 console → Load Balancers → cardiology-agent-alb → Listeners tab →
   Add listener.** Protocol/port HTTPS:443 → select the certificate → default
   action forward to `cardiology-agent-frontend-tg` → Add.
4. Edit the HTTP:80 listener → change its default action to **Redirect to...**
   → HTTPS, port 443, status code 301 → Save.

## 14. ECS services (with Service Connect)

**ECS console → Clusters → cardiology-agent-cluster → Services tab →
Create.**

**Backend service:**
- Compute options: **Launch type**, Fargate
- Task definition family: `cardiology-agent-backend`, latest revision
- Service name: `cardiology-agent-backend`
- Desired tasks: `2`
- Networking: select the VPC, the two **private** subnets, security group
  `cardiology-agent-backend-sg`, **Public IP: OFF**
- Load balancing: toggle **Use load balancing** → Application Load Balancer →
  select `cardiology-agent-alb` → container to load balance: `backend:8000` →
  target group: **Use an existing target group** →
  `cardiology-agent-backend-tg`
- Service Connect: toggle **Use Service Connect** → namespace: create new,
  name `cardiology.local` (or select it if section 9 pre-created it) → the
  `backend:8000` port mapping is listed automatically → set its **Discovery
  name** to `backend`
- Create.

**Frontend service** — repeat with: task definition
`cardiology-agent-frontend`, service name `cardiology-agent-frontend`,
desired tasks `2`, security group `cardiology-agent-frontend-sg`, load
balancer target group `cardiology-agent-frontend-tg` on container port
`8501`, Service Connect discovery name `frontend`, same `cardiology.local`
namespace.

Both now sit "under" `cardiology-agent-cluster`, reachable from the internet
via the ALB and from each other via Service Connect
(`http://backend:8000`) — no code change needed from the
`docker-compose.yml` hostname pattern the app already uses locally.

## 15. Auto scaling (optional)

**ECS console → cluster → Services → cardiology-agent-backend →** the
service detail page has an **"Auto Scaling"** tab (or "Update service" →
scroll to the auto scaling section, depending on console version):
- Check **Use service auto scaling**
- Minimum tasks: `2`, Maximum tasks: `6`
- Add scaling policy → **Target tracking** → metric **ECS service average CPU
  utilization** → target value `60` → Save.

Repeat for the frontend service if desired — the Streamlit UI is less likely
to need it than the backend, which does the LLM/tool-call work.

## 16. DNS (optional)

**Route 53 console → Hosted zones → your domain → Create record.**
- Record name: blank for the apex, or a subdomain
- Record type: **A**
- Toggle **Alias** on → Route traffic to → **Alias to Application and
  Classic Load Balancer** → select the region → select
  `cardiology-agent-alb`
- Create records.

## 17. Verification checklist

- **ECS console → cluster → Services tab**: both services show "Running
  count" equal to "Desired count," no tasks stuck restarting
- **EC2 console → Target Groups →** click each target group → **Targets**
  tab: all targets show **healthy**
- Open the ALB's DNS name (or your domain) in a browser — the Streamlit UI
  loads
- Register a test patient, ask a question, confirm the "thinking" trace and
  an answer come back, including the tool-status cards
- Hit the backend's `/rag/documents` route through however you routed it —
  all 15 documents listed (confirms the OpenSearch Serverless data access
  policy update in section 6 actually took effect)
- **CloudWatch console → Log groups → `/ecs/cardiology-agent/backend`** (and
  `/frontend`) → open the latest log stream → confirm clean startup, no
  `NoCredentialsError` / `AuthorizationException`
- Delete the test patient/data created during verification

## 18. CI/CD

Out of scope for a console-only walkthrough by nature (CI/CD is automation,
the opposite of clicking through a console each time). If you want an
AWS-console-native equivalent to a GitHub Actions pipeline later,
**CodePipeline + CodeBuild** (both configurable through their own consoles)
is the standard AWS-native option — flagged here as a next step, not detailed.

## 19. Cost notes / cleanup

Same standing costs as the CLI doc: NAT Gateway hours + data processing, ALB
hours + LCU usage, 4 Fargate tasks around the clock, CloudWatch Logs storage.
For a demo/eval environment rather than real production traffic, consider
`Desired tasks: 1` for both services and a single NAT Gateway (section 3) —
document that tradeoff if you do, since it removes the multi-AZ resilience
described in section 14.

**Console teardown, in order:**
1. ECS console → Services → select both → **Update service** → desired count
   `0` for each → once stopped, **Delete service** for each.
2. ECS console → Clusters → cardiology-agent-cluster → **Delete cluster**.
3. EC2 console → Load Balancers → delete `cardiology-agent-alb` → Target
   Groups → delete both target groups.
4. VPC console → your VPC → **Actions → Delete VPC** (the console offers a
   combined delete that removes the NAT Gateway, subnets, route tables, and
   internet gateway together — remember to release the NAT Gateway's Elastic
   IP afterward if it isn't released automatically).
5. Cloud Map console → delete the `cardiology.local` namespace.
6. ECR console → delete the two repositories (or just delete the image tags
   inside them and keep the empty repos).
7. Secrets Manager console → delete `cardiology-agent/app-secrets` (choose a
   recovery window, or force-delete for immediate removal).
8. IAM console → delete `cardiology-agent-ecs-execution-role` and
   `cardiology-agent-ecs-task-role` (detach/delete their inline policies
   first if the console requires it).
9. OpenSearch Serverless console → Collections → `cardiology-agent-rag` →
   Data access → remove the task role's principal from
   `cardiology-agent-access`.

The DynamoDB table and OpenSearch Serverless collection are independent of
this teardown — leave them alone unless decommissioning the whole project.
