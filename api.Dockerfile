FROM python:3.11-slim

WORKDIR /app

COPY requirements-api.txt .
RUN pip install --no-cache-dir -r requirements-api.txt

COPY manga_tracker/api ./manga_tracker/api
COPY manga_tracker/__init__.py ./manga_tracker/__init__.py

CMD ["uvicorn", "manga_tracker.api.main:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]
