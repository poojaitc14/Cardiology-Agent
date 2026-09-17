# Deploying to AWS: ECR + ECS (Fargate), Reusing the Default VPC

Companion to [`aws-ecs-deployment.md`](aws-ecs-deployment.md) — same resources,
same section numbers, but **skips creating a new VPC, subnets, and NAT
Gateway** entirely and reuses the account's existing default VPC instead.
Only sections 3, 4, 12, and 14 change; everything else (ECR, IAM, Secrets
Manager, CloudWatch, Cloud Map namespace, ECS cluster, task definitions,
HTTPS, auto scaling, DNS, verification, CI/CD) is identical to the main
doc — follow those sections there unchanged.

Status: **planning document only — nothing in this file has been run.**

Prefer clicking through the AWS Console over running CLI commands? See
[`aws-ecs-deployment-no-new-vpc-console.md`](aws-ecs-deployment-no-new-vpc-console.md)
— same delta, browser steps instead of `aws` commands.

## The core tradeoff

Every AWS account has a **default VPC** per region, pre-configured with a
public subnet in every Availability Zone, an Internet Gateway, and route
tables already wired up — no NAT Gateway needed because there's no private
subnet to route *through* one. This doc runs the ALB **and** the Fargate
tasks directly in those public subnets, with each task given a public IP
(`assignPublicIp=ENABLED`).

That means the backend and frontend containers are reachable from the
internet at the network layer, not just through the ALB — access control
shifts entirely onto **security groups** (only the ALB's security group may
reach the tasks; nothing else can) rather than network isolation via private
subnets. This is the same tradeoff already made for the OpenSearch Serverless
collection in this project (see `opensearch-serverless.md`): public network
access, access actually gated by IAM/security-group rules, not network
topology. It removes the NAT Gateway's ~$32-64/month standing cost (1-2
gateways) and a chunk of setup complexity, at the cost of one less layer of
defense-in-depth. Reasonable for a project at this stage; revisit if this
becomes a real production deployment handling real patient data.

## 3. Networking: use the existing default VPC

Look up the default VPC and its public subnets instead of creating anything:

```bash
DEFAULT_VPC_ID=$(aws ec2 describe-vpcs --filters Name=is-default,Values=true \
  --query 'Vpcs[0].VpcId' --output text)
echo "$DEFAULT_VPC_ID"

aws ec2 describe-subnets --filters Name=vpc-id,Values=$DEFAULT_VPC_ID \
  --query 'Subnets[].[SubnetId,AvailabilityZone,MapPublicIpOnLaunch]' --output table
```

Every subnet in a default VPC has `MapPublicIpOnLaunch: true` -- pick two
from **different Availability Zones** (for the same resilience the main doc's
2-AZ setup gives you) and note their IDs as `<SUBNET_A>` / `<SUBNET_B>`. No
NAT Gateway, no route table changes, no internet gateway setup -- all already
there.

**If `describe-vpcs` returns nothing** (the default VPC was deleted, which
some accounts do intentionally): either restore it —

```bash
aws ec2 create-default-vpc
```

— or point `<SUBNET_A>` / `<SUBNET_B>` at two public subnets of any other
*existing* VPC you already have instead (same lookup, filtered by that VPC's
ID rather than `is-default`). "No new VPC" doesn't have to mean specifically
the default one, just not provisioning a fresh one.

VPC Gateway Endpoints for DynamoDB (mentioned in the main doc's section 3) are
optional here and skippable — without a NAT Gateway there's no per-GB NAT
data-processing charge to save on the DynamoDB traffic anyway; the endpoint
would only save a little on egress pricing, not worth the extra setup for
this variant.

## 4. Security groups

Same three groups as the main doc's section 4, just created against
`$DEFAULT_VPC_ID` instead of a new one:

```bash
aws ec2 create-security-group --group-name cardiology-agent-alb-sg \
  --description "ALB ingress" --vpc-id $DEFAULT_VPC_ID
aws ec2 create-security-group --group-name cardiology-agent-backend-sg \
  --description "backend ingress" --vpc-id $DEFAULT_VPC_ID
aws ec2 create-security-group --group-name cardiology-agent-frontend-sg \
  --description "frontend ingress" --vpc-id $DEFAULT_VPC_ID
```

Same ingress rules as the main doc: ALB open on 80/443 to `0.0.0.0/0`;
backend open on 8000 to the ALB's and frontend's security groups only;
frontend open on 8501 to the ALB's security group only. **This is the one
control that actually matters more here than in the private-subnet
version** — since the tasks sit in a public subnet with public IPs, these
rules are the only thing stopping direct internet access to a container
port, not a network boundary.

## 12. Application Load Balancer, target groups, listeners

Identical to the main doc's section 12, except the load balancer's subnet
mapping uses the default VPC's public subnets:

```bash
aws elbv2 create-load-balancer --name cardiology-agent-alb \
  --subnets $SUBNET_A $SUBNET_B \
  --security-groups <ALB_SG_ID> --scheme internet-facing --type application
```

Target groups, listeners, and the `/api/*` path rule are unchanged from the
main doc.

## 14. ECS services (with Service Connect)

Same as the main doc's section 14, with two changes: the **public** subnets
instead of private ones, and `assignPublicIp=ENABLED` instead of `DISABLED`
(a Fargate task in a public subnet needs this to actually get a public IP
and reach the internet for OpenFDA/Azure OpenAI/OpenSearch calls, since
there's no NAT Gateway providing that path instead):

```bash
aws ecs create-service \
  --cluster cardiology-agent-cluster \
  --service-name cardiology-agent-backend \
  --task-definition cardiology-agent-backend \
  --desired-count 2 \
  --launch-type FARGATE \
  --network-configuration "awsvpcConfiguration={subnets=[$SUBNET_A,$SUBNET_B],securityGroups=[<BACKEND_SG_ID>],assignPublicIp=ENABLED}" \
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
  --network-configuration "awsvpcConfiguration={subnets=[$SUBNET_A,$SUBNET_B],securityGroups=[<FRONTEND_SG_ID>],assignPublicIp=ENABLED}" \
  --load-balancers "targetGroupArn=<FRONTEND_TG_ARN>,containerName=frontend,containerPort=8501" \
  --service-connect-configuration '{
    "enabled": true,
    "namespace": "cardiology.local",
    "services": [{ "portName": "frontend", "discoveryName": "frontend", "clientAliases": [{ "port": 8501 }] }]
  }'
```

Service Connect still works exactly the same way in a public subnet — the
frontend still reaches the backend at `http://backend:8000` over the
namespace, not over the internet, regardless of `assignPublicIp`.

## Everything else

Unchanged from `aws-ecs-deployment.md`: ECR (section 5), IAM roles and the
OpenSearch Serverless data-access-policy update (section 6), Secrets Manager
(section 7), CloudWatch log groups (section 8), the Cloud Map namespace
(section 9), the ECS cluster (section 10), both task definitions (section
11), HTTPS via ACM (section 13), auto scaling (section 15), DNS (section 16),
the verification checklist (section 17), and CI/CD notes (section 18) — none
of those reference the VPC directly, so nothing there needs to change. A
console-only (browser-clicks, no CLI) version of all of this exists too, at
[`aws-ecs-deployment-console.md`](aws-ecs-deployment-console.md) — the same
default-VPC swap applies there: skip its section 3 VPC-creation wizard, look
up the default VPC's subnets in the VPC console's Subnets list instead, and
toggle "Public IP: ON" in the ECS service wizard's networking step instead
of OFF.

## Cost notes / cleanup (delta from the main doc's section 19)

No NAT Gateway to pay for or tear down — that's the entire point of this
variant. Standing costs are just the ALB and the Fargate tasks themselves.
Teardown is the same as the main doc's section 19 minus the NAT
Gateway/Elastic-IP/VPC-deletion steps, since nothing new was created there to
delete — leave the default VPC in place (other things in the account may
already depend on it existing).
