"""Quick Reference for Langfuse Observability"""

# ============================================================================
# LANGFUSE OBSERVABILITY - QUICK START GUIDE
# ============================================================================

## 1. SETUP (5 minutes)

### a) Get Credentials
- Visit: https://cloud.langfuse.com
- Sign up or log in
- Go to Settings → API Keys
- Copy: Public Key (pk_...) and Secret Key (sk_...)

### b) Configure Environment
```bash
# Copy .env file
cp .env.example .env

# Edit .env with your keys
LANGFUSE_ENABLED=true
LANGFUSE_PUBLIC_KEY=pk_your_key
LANGFUSE_SECRET_KEY=sk_your_key
```

### c) Install & Run
```bash
pip install -r requirements.txt
uvicorn backend.main:app --reload
```

---

## 2. USAGE

### Make a Query
```bash
curl -X POST http://localhost:8000/query \
  -H "Content-Type: application/json" \
  -d '{
    "patient_id": "P1005",
    "question": "Review patient P1005 medications"
  }'
```

### Response Includes Trace ID
```json
{
  "answer": "Decision support only...",
  "sources": [...],
  "tools_used": ["patient_database_tool", "openfda_drug_tool"],
  "errors": [],
  "trace_id": "550e8400-e29b-41d4-a716-446655440000"
}
```

### View in Langfuse
1. Open: https://cloud.langfuse.com
2. Find trace by ID: 550e8400-e29b-41d4-a716-446655440000
3. Explore:
   - Request details
   - Tool invocations
   - Latency breakdown
   - Errors (if any)

---

## 3. TRACE STRUCTURE

```
Query Trace
├─ Agent Review Span
│  ├─ patient_database_tool Call
│  │  ├─ Input: {patient_id, scope}
│  │  ├─ Output: {records, found}
│  │  └─ Latency: 45ms
│  ├─ openfda_drug_tool Call
│  │  ├─ Input: {drug_name}
│  │  ├─ Output: {label, found}
│  │  └─ Latency: 320ms
│  └─ cardiology_rag_tool Call
│     ├─ Input: {query, limit}
│     ├─ Output: {results}
│     └─ Latency: 180ms
└─ Total Latency: 545ms
```

---

## 4. CAPTURED DATA

### Input
- Patient ID
- Question/Query
- Request parameters

### Output
- Answer text
- Citations and sources
- Tools used
- Errors encountered

### Metrics
- Total latency (ms)
- Per-tool latency (ms)
- Tool name
- Success/failure status

### Security
- API keys protected in environment variables
- Sensitive parameters filtered (password, token, key)
- Patient identified by ID only
- Question truncated to 100 chars

---

## 5. CONFIGURATION OPTIONS

```bash
# Enable/disable observability
LANGFUSE_ENABLED=true|false

# API keys (required if enabled)
LANGFUSE_PUBLIC_KEY=pk_...
LANGFUSE_SECRET_KEY=sk_...

# Custom host (for self-hosted)
LANGFUSE_HOST=https://custom.example.com

# Log level
LOG_LEVEL=DEBUG|INFO|WARNING|ERROR
```

---

## 6. TROUBLESHOOTING

### Problem: No traces appearing
```bash
# Check credentials
echo $LANGFUSE_PUBLIC_KEY
echo $LANGFUSE_SECRET_KEY

# Check if enabled
echo $LANGFUSE_ENABLED

# Check logs
LOG_LEVEL=DEBUG uvicorn backend.main:app --reload
```

### Problem: Secrets in logs
✓ All secrets filtered automatically
✓ Only safe parameters captured
✓ Patient IDs masked to ID only

### Problem: Slow queries
- Check per-tool latency in Langfuse dashboard
- Identify slow tool (usually OpenFDA or RAG)
- Optimize that specific tool

---

## 7. DEVELOPMENT VS PRODUCTION

### Development
```bash
LANGFUSE_ENABLED=true
LOG_LEVEL=DEBUG
# Use personal Langfuse project
```

### Production
```bash
LANGFUSE_ENABLED=true
LANGFUSE_PUBLIC_KEY=$(aws secretsmanager get-secret-value ...)
LANGFUSE_SECRET_KEY=$(aws secretsmanager get-secret-value ...)
LOG_LEVEL=WARNING
```

---

## 8. MONITORING CHECKLIST

- [ ] Create Langfuse account: https://cloud.langfuse.com
- [ ] Generate API key pair
- [ ] Add credentials to .env
- [ ] Run: `pip install -r requirements.txt`
- [ ] Start server: `uvicorn backend.main:app --reload`
- [ ] Make test query with trace_id in response
- [ ] View trace in Langfuse dashboard
- [ ] Check latency breakdown by tool
- [ ] Verify no sensitive data in traces

---

## 9. FILES CREATED/MODIFIED

New Files:
- backend/observability/__init__.py
- backend/observability/langfuse_config.py
- backend/observability/tracing.py
- backend/observability/instrumented_agent.py
- tests/unit/test_tracing.py
- LANGFUSE_OBSERVABILITY.md

Modified Files:
- backend/main.py (integrated tracing)
- backend/schemas.py (added trace_id to response)
- requirements.txt (added langfuse)
- pyproject.toml (added langfuse)
- .env.example (added Langfuse config)

---

## 10. API CHANGES

### Query Response (Added)
```json
{
  "answer": "...",
  "sources": [...],
  "tools_used": [...],
  "errors": [...],
  "trace_id": "UUID-v4"  // NEW FIELD
}
```

Link to trace:
```
https://cloud.langfuse.com/traces/{trace_id}
```

---

## 11. COST CONSIDERATIONS

Langfuse free tier includes:
- 100K spans/month
- Basic dashboards
- 7-day retention

Paid tier for higher volume and longer retention.

Reduce costs:
- Sample high-volume queries
- Archive old traces
- Disable for low-importance requests

---

## 12. SUPPORT & DOCS

- Full Documentation: LANGFUSE_OBSERVABILITY.md
- Langfuse Docs: https://docs.langfuse.com
- Dashboard: https://cloud.langfuse.com
- GitHub Issues: Tag with 'langfuse' or 'tracing'

---
