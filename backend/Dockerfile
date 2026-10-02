FROM python:3.13-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app

COPY backend/pyproject.toml backend/requirements-dev.lock ./
COPY backend/app ./app

RUN pip install --no-cache-dir -c requirements-dev.lock .

COPY data/config.yaml /app/data/config.yaml

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
