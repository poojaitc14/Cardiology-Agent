# Langfuse Observability Guide

This document explains how to set up and use Langfuse observability for the Cardiology Clinical Decision Support Agent.

## Overview

Langfuse observability provides comprehensive tracing and monitoring of:
- User queries and requests
- Agent invocation and decision-making
- Individual tool calls (patient database, OpenFDA, RAG)
- Latency and performance metrics
- Errors and exceptions
- Model usage and costs

## Architecture

The tracing flow for a typical query:

```
User Query (POST /query)
  ↓
[Trace Start]
  ├─ Agent Invocation
  │  ├─ Tool: patient_database_tool
  │  │  ├─ Input: {patient_id, scope}
  │  │  ├─ Output: {records, found}
  │  │  └─ Latency: XXms
  │  ├─ Tool: openfda_drug_tool
  │  │  ├─ Input: {drug_name}
  │  │  ├─ Output: {label, found}
  │  │  └─ Latency: XXms
  │  └─ Tool: cardiology_rag_tool
  │     ├─ Input: {query, limit}
  │     ├─ Output: {results}
  │     └─ Latency: XXms
  └─ Response with trace_id
```

## Setup

### 1. Get Langfuse API Keys

1. Go to https://cloud.langfuse.com
2. Sign up or log in
3. Navigate to Settings → API Keys
4. Create a new API key pair:
   - Copy the **Public Key** (starts with `pk_`)
   - Copy the **Secret Key** (starts with `sk_`)

### 2. Configure Environment Variables

Copy `.env.example` to `.env`:

```bash
cp .env.example .env
```

Update the `.env` file with your Langfuse credentials:

```bash
# Enable Langfuse observability
LANGFUSE_ENABLED=true

# Your Langfuse API keys (from cloud.langfuse.com)
LANGFUSE_PUBLIC_KEY=pk_your_public_key_here
LANGFUSE_SECRET_KEY=sk_your_secret_key_here

# (Optional) Langfuse host - use this for self-hosted Langfuse
LANGFUSE_HOST=https://cloud.langfuse.com
```

### 3. Install Dependencies

```bash
pip install -r requirements.txt
```

The `langfuse` package is automatically included in `requirements.txt`.

### 4. Run the Application

```bash
uvicorn backend.main:app --reload
```

The application will automatically initialize Langfuse if credentials are configured.

## Usage

### API Response

Every query response includes a `trace_id` field that links to the Langfuse trace:

```json
{
  "answer": "Decision support only...",
  "sources": [
    {"source": "DynamoDB", "detail": "Patient P1005"},
    {"source": "OpenFDA", "detail": "Warfarin"}
  ],
  "tools_used": ["patient_database_tool", "openfda_drug_tool"],
  "errors": [],
  "trace_id": "550e8400-e29b-41d4-a716-446655440000"
}
```

### View Traces in Langfuse

1. Open https://cloud.langfuse.com
2. Navigate to your project
3. Look for the trace by ID or search by:
   - Patient ID
   - Question content
   - Tool name
   - Timestamp

### Trace Details

Each trace contains:

- **Inputs**: Patient ID, question, request parameters
- **Outputs**: Answer, citations, errors
- **Tools Used**: Which tools were invoked
- **Latency**: Total query time and per-tool timing
- **Metadata**: Patient ID, question length, tool names
- **Errors**: Any errors encountered during execution

## Security & Privacy

### Secrets Protection

The observability layer automatically protects sensitive data:

1. **API Keys**: Never logged or exposed
   - Langfuse credentials are loaded from environment variables only
   - Keys are never included in logs or traces

2. **Sensitive Tool Parameters**: Filtered from traces
   - Passwords, tokens, and API keys are excluded
   - Only safe parameters (patient_id, drug_name, query) are captured

3. **Safe Metadata Only**
   - Trace metadata contains only non-sensitive fields
   - Patient data is identified by ID only
   - Questions are truncated to first 100 characters

### Environment Variables

**Never commit real Langfuse credentials to version control:**

```bash
# Good: Use a .env file (not committed)
LANGFUSE_SECRET_KEY=sk_actual_key

# Better: Use environment variables from your deployment platform
# (AWS Secrets Manager, GitHub Secrets, Azure Key Vault, etc.)

# Disable Langfuse if not needed
LANGFUSE_ENABLED=false
```

## Configuration

### Enable/Disable Langfuse

```bash
# Enable observability (default if keys are set)
LANGFUSE_ENABLED=true

# Disable observability
LANGFUSE_ENABLED=false
```

### Custom Langfuse Host

For self-hosted Langfuse:

```bash
LANGFUSE_HOST=https://your-langfuse-instance.com
```

### Log Level

Control logging verbosity:

```bash
# Debug logging (verbose)
LOG_LEVEL=DEBUG

# Info logging (default)
LOG_LEVEL=INFO

# Warning logging
LOG_LEVEL=WARNING

# Error logging only
LOG_LEVEL=ERROR
```

## Monitoring & Analytics

### Latency Analysis

View latency metrics in Langfuse:
- Total query latency
- Per-tool latency breakdown
- Tool-specific performance trends

### Error Tracking

Monitor errors across:
- Patient database access failures
- OpenFDA service timeouts
- RAG retrieval issues
- Request validation errors

### Usage Analytics

Track:
- Most common queries
- Tool usage frequency
- Patient query patterns
- Error rates by tool

## Troubleshooting

### Langfuse Not Capturing Traces

1. **Check credentials**
   ```bash
   echo $LANGFUSE_PUBLIC_KEY
   echo $LANGFUSE_SECRET_KEY
   ```

2. **Check if enabled**
   ```bash
   echo $LANGFUSE_ENABLED
   ```

3. **Verify network connectivity**
   ```bash
   curl https://cloud.langfuse.com/api/health
   ```

4. **Check application logs**
   ```bash
   # Look for messages like "Langfuse observability enabled"
   # or "Failed to create Langfuse trace"
   ```

### Large Trace Size

If traces are too large:
1. Reduce question length limit in tracing code
2. Filter additional metadata fields
3. Enable sampling for high-volume queries

### Missing Trace ID

If `trace_id` is missing from response:
1. Check application logs
2. Verify Langfuse is enabled
3. Look for exceptions in trace initialization

## Best Practices

1. **Local Development**
   - Keep Langfuse enabled for testing
   - Use a separate Langfuse project for local development

2. **Production Deployment**
   - Store credentials in secure secret management (AWS Secrets Manager, etc.)
   - Monitor trace volume and set up cost alerts
   - Review traces regularly for performance issues

3. **Privacy Compliance**
   - Audit traces for sensitive data
   - Set data retention policies in Langfuse
   - Document what data is being traced for privacy audits

4. **Performance**
   - Traces are sent asynchronously to not block requests
   - Network failures don't impact API responses
   - Metadata is optimized to minimize trace size

## Integration Examples

### Python Client

```python
from backend.observability.tracing import get_trace_id

# Get trace ID from response
response = requests.post(
    "http://localhost:8000/query",
    json={
        "patient_id": "P1005",
        "question": "Review patient status"
    }
)

trace_id = response.json()["trace_id"]
print(f"View trace: https://cloud.langfuse.com/traces/{trace_id}")
```

### Frontend Integration

```javascript
// After getting response
const traceId = response.trace_id;
const langfuseUrl = `https://cloud.langfuse.com/traces/${traceId}`;
console.log(`Langfuse trace: ${langfuseUrl}`);
```

## Advanced Configuration

### Custom Trace Metadata

Modify `backend/observability/tracing.py` to add custom metadata:

```python
metadata = {
    "patient_id": patient_id,
    "question_length": len(question),
    "custom_field": "custom_value",  # Add custom fields here
}
```

### Sampling

To reduce trace volume for high-traffic scenarios, implement sampling in `backend/observability/tracing.py`:

```python
import random

if random.random() > 0.1:  # Only trace 10% of requests
    return
```

## Support

- Langfuse Documentation: https://docs.langfuse.com
- Langfuse Dashboard: https://cloud.langfuse.com
- GitHub Issues: Open an issue with "langfuse" or "tracing" label
