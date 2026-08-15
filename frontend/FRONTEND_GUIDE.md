"""Instructions for running the Streamlit frontend."""

# Streamlit Frontend - Getting Started

## Prerequisites

- FastAPI backend running (see README.md)
- Python 3.11+
- Frontend dependencies installed

## Installation

### 1. Install Frontend Dependencies

```bash
# Install streamlit and httpx
pip install streamlit>=1.28.0 httpx>=0.27.0
```

Or use the combined requirements:

```bash
pip install -r requirements.txt
```

## Running the Frontend

### 1. Ensure Backend is Running

First, start the FastAPI backend:

```bash
# Terminal 1: Start FastAPI backend
cd /path/to/project
uvicorn backend.main:app --reload --port 8000
```

### 2. Start Streamlit App

```bash
# Terminal 2: Start Streamlit frontend
cd /path/to/project
streamlit run frontend/streamlit_app.py
```

The app will open automatically in your browser at `http://localhost:8501`

## Configuration

### Environment Variables

Set these before running the frontend:

```bash
# FastAPI backend URL (default: http://localhost:8000)
export FASTAPI_URL=http://localhost:8000

# Request timeout in seconds (default: 30)
export API_TIMEOUT=30

# Streamlit settings (optional)
export STREAMLIT_LOGGER_LEVEL=info
```

### Example with Custom Configuration

```bash
FASTAPI_URL=http://api.example.com:8000 \
API_TIMEOUT=60 \
streamlit run frontend/streamlit_app.py
```

## Features

✅ **Patient Selector** - Enter patient ID to load patient data
✅ **Patient Overview** - Display key patient information  
✅ **Query Input** - Submit clinical questions
✅ **Agent Response** - Display AI-generated decision support
✅ **Tools Used** - Show which tools were invoked
✅ **Sources & Citations** - Display evidence and references
✅ **Error Display** - Clear error messages
✅ **Loading States** - Visual feedback during processing
✅ **Query History** - Track previous queries in sidebar
✅ **API Health Status** - Connection indicator

## Common Issues

### Issue: "Cannot connect to API"

**Solution:**
- Ensure FastAPI backend is running: `uvicorn backend.main:app --reload`
- Check FASTAPI_URL environment variable
- Verify no firewall blocking localhost:8000

```bash
# Test API connectivity
curl http://localhost:8000/health
```

### Issue: "Port 8501 already in use"

**Solution:**
```bash
# Run on different port
streamlit run frontend/streamlit_app.py --server.port 8502
```

### Issue: "Module not found: streamlit"

**Solution:**
```bash
pip install streamlit>=1.28.0
```

## Development

### Project Structure

```
frontend/
├── __init__.py           # Package initialization
├── streamlit_app.py      # Main application
├── config.py             # Configuration
├── api_client.py         # API client
└── ui_components.py      # Reusable UI components
```

### Testing

```bash
# Run frontend tests
pytest tests/unit/test_frontend.py -v
```

## Architecture

The frontend follows a clean architecture:

1. **UI Layer** (`streamlit_app.py`)
   - Page layout and user interactions
   - Session state management

2. **API Layer** (`api_client.py`)
   - HTTP communication with FastAPI
   - Error handling

3. **Components** (`ui_components.py`)
   - Reusable UI components
   - Display logic

4. **Configuration** (`config.py`)
   - Settings and constants
   - Environment variables

## API Integration

The frontend communicates with three FastAPI endpoints:

### 1. Health Check
```
GET /health
```
Response: `{"status": "healthy", "version": "1.0.0"}`

### 2. Query
```
POST /query
Body: {
  "patient_id": "P1005",
  "question": "..."
}
```
Response: `{"answer": "...", "sources": [...], "tools_used": [...], "errors": [...], "trace_id": "..."}`

### 3. Patient Profile
```
GET /patient/{patient_id}
```
Response: `{"patient_id": "...", "data": {...}, "source": "..."}`

## Performance Tips

- Keep FastAPI backend on same machine or low-latency network
- Increase `API_TIMEOUT` for slow connections
- Use browser cache for better performance
- Monitor Langfuse traces for slow queries

## Deployment

### Docker

Create `Dockerfile` for frontend:

```dockerfile
FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY frontend/ frontend/

ENV FASTAPI_URL=http://backend:8000

CMD ["streamlit", "run", "frontend/streamlit_app.py"]
```

### Docker Compose

```yaml
version: '3.8'

services:
  backend:
    build:
      context: .
      dockerfile: backend.Dockerfile
    ports:
      - "8000:8000"
    environment:
      AWS_REGION: eu-west-2
      DYNAMODB_PATIENT_TABLE: PatientClinicalRecords

  frontend:
    build:
      context: .
      dockerfile: frontend.Dockerfile
    ports:
      - "8501:8501"
    environment:
      FASTAPI_URL: http://backend:8000
    depends_on:
      - backend
```

## Security Considerations

1. **API Authentication** - Add authentication headers if needed
2. **HTTPS** - Use HTTPS in production
3. **Secrets** - Never commit sensitive data
4. **CORS** - Ensure CORS is properly configured
5. **Rate Limiting** - Implement rate limits on backend

## Next Steps

- [ ] Customize UI styling
- [ ] Add authentication
- [ ] Implement caching
- [ ] Add export functionality
- [ ] Create mobile-responsive version
- [ ] Add dark mode support

## Support

- Streamlit Docs: https://docs.streamlit.io
- FastAPI Docs: https://fastapi.tiangolo.com
- Issues: Open an issue on GitHub
