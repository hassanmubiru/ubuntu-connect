# Ubuntu Connect — Backend

FastAPI service for the Ubuntu Connect trust platform.

## Stack

- FastAPI + Pydantic v2 (typed request/response schemas, auto OpenAPI)
- SQLAlchemy 2.x on PostgreSQL (via `psycopg`)
- JWT auth (`python-jose`)
- Testing: `pytest` + `hypothesis` (property-based tests, min 100 examples)

## Layout

```
backend/
├── app/
│   ├── main.py          # application factory: create_app()
│   ├── routers/         # thin HTTP/SSE/USSD handlers
│   ├── services/        # business logic (no direct data-store queries)
│   ├── repositories/    # all SQLAlchemy queries
│   ├── ai/
│   │   ├── fallback/    # deterministic rule-based classifiers
│   │   └── prompts/     # prompt modules, independent of calling logic
│   ├── integrations/    # SMS gateway, USSD, OpenAI clients
│   ├── models/          # SQLAlchemy ORM entities
│   └── schemas/         # Pydantic request/response schemas
├── tests/               # unit + property-based tests
├── conftest.py          # Hypothesis profiles (min 100 examples)
├── pytest.ini
├── pyproject.toml
└── requirements.txt
```

## Development

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload
pytest
```
