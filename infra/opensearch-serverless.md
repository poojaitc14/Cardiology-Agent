# OpenSearch Serverless -- status

The RAG vector store runs on AWS OpenSearch Serverless. Network access is
**public**, data access is **IAM/SigV4-gated** -- no VPC, no VPN, no in-network
split between Docker and native runs. (An earlier iteration of this used a
VPC-only collection reachable only via an AWS Client VPN tunnel; that entire
setup -- VPC, subnet, security group, VPC endpoint, Client VPN endpoint, and its
ACM certificates -- was built, live-verified, and then deliberately torn down
once the added isolation was judged not worth the ~$72+/month standing VPN cost
and the "must connect before RAG works" friction for a project at this stage.
IAM/SigV4 was the actual authorization boundary the whole time; the VPC only
added a network-level restriction on top of it.)

## Live resources (AWS account 666127452756, region eu-west-2)

| Resource | ID / ARN |
|---|---|
| Network security policy | `cardiology-agent-net` -- **public** (`AllowFromPublic: true`) |
| Data access policy | `cardiology-agent-access` -- grants `arn:aws:iam::666127452756:role/aws-reserved/sso.amazonaws.com/eu-west-2/AWSReservedSSO_AdministratorAccess_a03ab89203a24f9a` read/write on `index/cardiology-agent-rag/*` |
| Encryption policy | `cardiology-agent-enc` (AWS-owned key) |
| **Collection** | `cardiology-agent-rag`, id `2yq4tyj49f8urs2o93jf` -- **ACTIVE**, 15 documents indexed |
| Collection endpoint | `https://2yq4tyj49f8urs2o93jf.eu-west-2.aoss.amazonaws.com` |
| `.env` `OPENSEARCH_HOST` | `2yq4tyj49f8urs2o93jf.eu-west-2.aoss.amazonaws.com` (bare hostname, unchanged since the collection was created -- only the network policy changed) |

## Torn down (no longer exist, no longer billing)

VPC, private subnet, security group, the OpenSearch Serverless VPC endpoint,
the Client VPN endpoint (and its target-network association + ingress
authorization), and all three ACM certificates (server v1, server v2, client
root/CA) generated for the VPN's mutual-TLS auth. Deleted in dependency order:
disassociate target network &rarr; delete Client VPN endpoint &rarr; delete
OpenSearch VPC endpoint &rarr; delete security group &rarr; delete subnet &rarr;
delete VPC &rarr; delete ACM certs. Verified gone via `describe-vpcs` /
`describe-client-vpn-endpoints` returning `NotFound`; the collection itself was
never touched and stayed `ACTIVE` with its data intact throughout.

## Two issues hit and fixed while the VPC/VPN setup was live (kept for reference)

1. **`InvalidParameterValue: Certificate ... does not have a domain`** -- the
   first server cert had `CN=server` (not DNS-shaped).
2. **TLS handshake failure on connect** -- the certs had no Key Usage /
   Extended Key Usage extensions; AWS's exported OpenVPN config requires
   `extendedKeyUsage=serverAuth` on the server cert via `remote-cert-tls server`.
3. **`illegal_argument_exception: Document ID is not supported in create/index
   operation request`** -- OpenSearch Serverless rejects a client-supplied `_id`
   on writes entirely (unlike a normal OpenSearch cluster). This fix is
   **permanent and still in effect** regardless of network policy: see
   `rag/ingestion/pipeline.py`'s `index_chunks()`, which never passes `id=` to
   `.index()` -- the deterministic `chunk_id` is kept inside the document body
   instead, and OpenSearch auto-assigns the real `_id`. Re-running the indexing
   script appends duplicate documents rather than upserting; delete and
   recreate the index first if a clean re-index is ever needed.

## Code changes (all committed, still in effect)

- `rag/opensearch_client.py` -- shared SigV4-authenticated client builder
  (`build_serverless_client`), service name `aoss`. This is what makes network
  policy (public vs. VPC-only) a pure infrastructure toggle with zero code
  changes -- the client always signs with SigV4 regardless of network path.
- `rag/retrieval/cardiology_rag.py` -- `from_environment()` builds a
  SigV4-signed client; requires `AWS_REGION`.
- `rag/ingestion/index_dummy_documents_cli.py` -- same client change; tolerates
  `indices.refresh()` not being supported by Serverless.
- `rag/ingestion/pipeline.py` -- `index_chunks()` never sends a client-side
  document `id` (see issue 3 above).
- `requirements.txt` / `pyproject.toml` -- added `requests` (needed by
  `RequestsHttpConnection`).
- `docker-compose.yml` -- no local `opensearch` service; `OPENSEARCH_HOST`
  passes through from `.env` unchanged.
- Local `cardiology-opensearch` Docker container and its data volume (from the
  pre-Serverless setup) were stopped and deleted earlier in this migration.
