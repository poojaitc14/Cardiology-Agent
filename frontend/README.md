# Streamlit frontend

Start the API, then the frontend:

```powershell
.\.venv\Scripts\Activate.ps1
uvicorn app.main:app --reload
streamlit run frontend/streamlit_app.py
```

Set `DYNAMODB_TABLE_NAME` and AWS credentials (or an ECS task role) before the Administration tab can save. In ECS, set `API_BASE_URL` to the internal FastAPI service, not `localhost`.
