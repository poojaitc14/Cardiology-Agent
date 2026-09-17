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
  (`build_serverless_client`), service name `aoss`. Still used by the legacy
  `rag/retrieval/cardiology_rag.py` read path, kept in the repo but no longer
  wired into `backend/main.py` (see below).
- `rag/ingestion/pipeline.py` -- `index_chunks()`/`chunk_sections()` never send
  a client-side document `id` (see issue 3 above); still the shared chunking
  logic used by both the old and new ingestion paths.
- `requirements.txt` / `pyproject.toml` -- added `requests` (needed by
  `RequestsHttpConnection`).
- `docker-compose.yml` -- no local `opensearch` service; `OPENSEARCH_HOST`
  passes through from `.env` unchanged.
- Local `cardiology-opensearch` Docker container and its data volume (from the
  pre-Serverless setup) were stopped and deleted earlier in this migration.

## LangChain + LangGraph migration (embeddings, RAG, agent orchestration)

Replaced the raw opensearch-py RAG read/write path and the `HashEmbeddingProvider`
development stand-in with a LangChain-based one using real Azure OpenAI
`text-embedding-3-small` embeddings, and re-platformed the agent's control flow
as a LangGraph `StateGraph` with an added guardrail step. Full design rationale
in the chat history; summary here for anyone landing on this file cold.

- `rag/langchain_vectorstore.py` -- builds `AzureOpenAIEmbeddings` and a
  `langchain_community.vectorstores.OpenSearchVectorSearch` (engine `"faiss"`,
  the AOSS-required engine), authenticated the same SigV4 way as everything
  else in this app. `langchain-community` is officially "sunset" upstream but
  still the only mature AOSS integration; the newer standalone
  `langchain-opensearch` package is at v0.0.x and not yet trusted for this.
- `rag/retrieval/langchain_cardiology_rag.py` -- read path, returns the same
  `RetrievalResponse`/`RetrievalResult` the rest of the app already expects.
- `rag/ingestion/admin.py` -- rewritten to write through the LangChain vector
  store (`add_texts`/`delete`) instead of raw `index()`/`delete()` calls. Field
  schema changed: documents now live under LangChain's own conventions
  (`text`, `vector_field`, `metadata.{document_name,section,version,...}`)
  instead of the old top-level `document`/`content`/`embedding` fields, so
  **the old and new schemas cannot coexist in the same index** -- exact-match
  queries/aggregations against the new schema use
  `metadata.document_name.keyword`.
- `rag/ingestion/reembed_documents_cli.py` (new) -- one-time migration script:
  deletes the whole index and re-creates it fresh via LangChain, then
  re-embeds and re-indexes all 15 synthetic documents with real Azure
  embeddings. **Done** -- all 15 documents re-indexed and live-verified via
  `/query` (`similarity_search_with_score` correctly surfaces the
  "Anticoagulation / Antiplatelet Therapy Protocol" document for an
  anticoagulation question, score ~0.42). Three real issues were found and
  fixed while running this the first time, all still in effect:
  1. A default 10s read timeout was too tight for a bulk write of several
     real 1536-dim embeddings right after index (re)creation --
     `rag/langchain_vectorstore.py` now passes `timeout=30`.
  2. A freshly (re)created index's mapping needs a moment to settle;
     `reembed_documents_cli.py` waits 10s after deleting the old index and
     retries a document's upsert on `BulkIndexError`.
  3. **A real bug, not just a migration hiccup**: `RAGDocumentAdminService.delete_document()`
     crashed with `NotFoundError` if the index didn't exist yet at all (a
     brand-new knowledge base, or right after `recreate_index()`) -- fixed to
     treat "index doesn't exist" as "nothing to delete" (returns 0), so
     `upsert_document`/`upsert_sections` (which delete-before-insert) work
     correctly against an empty index, not just an existing one.
  Operational note: if you delete/recreate the index while a backend process
  is already running against it (as happened once during this migration), that
  process's OpenSearch connection can keep returning stale/empty results even
  after the reindex completes -- restart the backend after running this script.
- `backend/agent/graph.py` -- `LangGraphCardiologistAgent`, a `StateGraph`
  version of the old `CardiologistAgent`/`InstrumentedCardiologistAgent`: same
  deterministic regex-based tool routing (not LLM-driven -- kept intentionally
  predictable for a clinical safety tool), same `steps` trace, plus a
  guardrail-gated synthesis node. Drop-in replacement -- same `review()`
  signature and `AgentResponse` return type, so `backend/main.py` only changed
  how the agent is constructed.
- `backend/agent/prompts.py` -- the consolidated system prompt (previously
  there wasn't a real one: `AGENT_PROMPT` in `cardiology_agent.py` was defined
  but never actually sent to the LLM).
- `backend/agent/guardrails.py` -- post-synthesis checks (prescriptive/
  diagnostic language, prompt-injection leaks, fabricated drug names not in
  evidence); a violation discards the LLM answer and falls back to the
  deterministic evidence summary.
- **Known gap**: `InstrumentedCardiologistAgent`'s per-tool-call Langfuse spans
  were not ported to the LangGraph agent -- the outer `trace_query`/
  `trace_agent_invocation` spans in `backend/main.py` still work, but
  fine-grained per-tool/per-LLM-call tracing is gone until someone adds it back
  as LangGraph node instrumentation (or switches to LangSmith, which LangGraph
  supports natively).
- Old code (`rag/retrieval/cardiology_rag.py`, `rag/ingestion/index_dummy_documents_cli.py`,
  `backend/agent/cardiology_agent.py`'s `CardiologistAgent`,
  `backend/observability/instrumented_agent.py`) is **kept in the repo, unused
  by `backend/main.py`**, as an easy rollback until the re-embed + live
  verification above is confirmed. Safe to delete once that's done.
