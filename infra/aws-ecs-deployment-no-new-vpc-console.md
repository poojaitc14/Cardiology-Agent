# Deploying to AWS: ECR + ECS (Fargate), Reusing the Default VPC — via the Console

Companion to [`aws-ecs-deployment-no-new-vpc.md`](aws-ecs-deployment-no-new-vpc.md)
(the CLI version of this same delta) and to
[`aws-ecs-deployment-console.md`](aws-ecs-deployment-console.md) (the full
browser walkthrough this one trims down). Same resources, same section
numbers, but **skips creating a new VPC, subnets, and NAT Gateway** and
reuses the account's existing default VPC instead — done entirely by
clicking through the AWS Console.

Only sections 3, 4, 12, and 14 change. Everything else — ECR (§5), IAM (§6),
Secrets Manager (§7), CloudWatch log groups (§8), the Cloud Map namespace
(§9), the ECS cluster (§10), both task definitions (§11), HTTPS (§13), auto
scaling (§15), DNS (§16), the verification checklist (§17), and CI/CD notes
(§18) — is identical to `aws-ecs-deployment-console.md`. Follow those
sections there unchanged; this doc only covers what's different.

Status: **planning document only — nothing has been done.**

## The core tradeoff

Every AWS account has a **default VPC** per region, already set up with a
public subnet in every Availability Zone, an Internet Gateway, and routing
pre-wired — no NAT Gateway needed, since there's no private subnet to route
*through* one. This variant runs the ALB **and** the Fargate tasks directly
in those public subnets, with each task assigned a public IP.

That means the containers are reachable from the internet at the network
layer, not only through the ALB — access control shifts entirely onto
**security groups** (only the ALB's security group may reach the tasks;
nothing else can) instead of network isolation via private subnets. Same
tradeoff this project already made for the OpenSearch Serverless collection
(public network access, gated by IAM/security-group rules, not network
topology — see `opensearch-serverless.md`). It removes the NAT Gateway's
standing cost and a chunk of console setup, at the cost of one less layer of
defense-in-depth. Reasonable for a project at this stage.

## 3. Networking: use the existing default VPC

1. **VPC console → Your VPCs.** Look for the row where the **"Default VPC"**
   column reads **Yes** — note its VPC ID (`vpc-xxxxxxxx`).
2. **VPC console → Subnets** → filter by that VPC ID (use the search box or
   the VPC ID filter at the top of the table). Every subnet in a default VPC
   is public — the **"Auto-assign public IPv4 address"** column reads **Yes**
   for all of them.
3. Pick **two subnets in different Availability Zones** (check the
   "Availability Zone" column) — same resilience the full walkthrough's 2-AZ
   setup gives you. Note both subnet IDs.

No NAT Gateway, no route table edits, no Internet Gateway setup — the
default VPC already has all of that.

**If there's no row with "Default VPC: Yes"** (some accounts have it
deleted intentionally): on the VPC console's dashboard, look for an
**"Actions" → "Create default VPC"** option (available when the account has
none) — or, simpler, just pick two public subnets from any other *existing*
VPC you already have instead, using the same subnet-list lookup filtered by
that VPC's ID. "No new VPC" doesn't have to specifically mean the default
one, just not provisioning a fresh one.

## 4. Security groups

Same three groups as the full walkthrough's section 4 — **EC2 console →
Security Groups → Create security group** — just make sure the **VPC**
field on each is set to the default VPC you found above, not a new one:

1. `cardiology-agent-alb-sg` — inbound HTTP (80) and, if doing HTTPS, HTTPS
   (443), both from `0.0.0.0/0`.
2. `cardiology-agent-frontend-sg` — inbound Custom TCP 8501, source =
   `cardiology-agent-alb-sg`.
3. `cardiology-agent-backend-sg` — inbound Custom TCP 8000, source =
   `cardiology-agent-alb-sg`; second rule, Custom TCP 8000, source =
   `cardiology-agent-frontend-sg`.

**This matters more here than in the private-subnet version** — since the
tasks sit in a public subnet with public IPs, these rules are the only thing
stopping direct internet access to a container port, not a network boundary.

## 12. Application Load Balancer, target groups, listeners

Same as the full walkthrough's section 12, with one difference: when the
**"Create load balancer"** wizard asks for **VPC** and **Mappings**, select
the default VPC and the two public subnets found in section 3 above (instead
of two newly-created ones). Target group creation, health check paths, and
the `/api/*` listener rule are unchanged.

## 14. ECS services (with Service Connect)

Same **Create service** flow as the full walkthrough's section 14, with one
toggle flipped in the **Networking** step:

- VPC: the default VPC
- Subnets: the two public subnets from section 3
- Security group: `cardiology-agent-backend-sg` (or `...-frontend-sg` for
  the frontend service)
- **Public IP: ON** (this was OFF in the private-subnet version — a task in
  a public subnet needs this toggle on to actually get a public IP and
  reach the internet for OpenFDA/Azure OpenAI/OpenSearch calls, since
  there's no NAT Gateway providing that path instead)

Everything else in the service wizard — load balancer target group
selection, Service Connect namespace/discovery name — is unchanged from the
full walkthrough.

## Everything else

Follow `aws-ecs-deployment-console.md` unchanged for ECR (§5), IAM roles and
the OpenSearch Serverless data-access-policy update (§6), Secrets Manager
(§7), CloudWatch log groups (§8), the Cloud Map namespace (§9), the ECS
cluster (§10), both task definitions (§11), HTTPS via ACM (§13), auto
scaling (§15), DNS (§16), the verification checklist (§17), and CI/CD notes
(§18) — none of those touch the VPC, so nothing there needs to change.

## Cost notes / cleanup (delta)

No NAT Gateway to pay for or tear down — that's the whole point of this
variant. Standing costs are just the ALB and the Fargate tasks. Teardown is
the same as the full walkthrough's section 19 minus the NAT
Gateway/Elastic-IP/VPC-deletion steps, since nothing new was created there —
leave the default VPC in place; other things in the account may already
depend on it existing.
