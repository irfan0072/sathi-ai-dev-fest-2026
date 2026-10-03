FROM python:3.13-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app

RUN apt-get update && apt-get install -y --no-install-recommends libgomp1 && rm -rf /var/lib/apt/lists/*

COPY backend/pyproject.toml backend/requirements-dev.lock ./
COPY backend/app ./app

RUN pip install --no-cache-dir -c requirements-dev.lock .

COPY backend/migrations /app/migrations
COPY data/config.yaml /app/data/config.yaml
COPY data/artifacts/deployment /app/data/artifacts/deployment

RUN python -c "from uvicorn.main import main; from app.main import app; from app.data.config import load_config; from app.evaluation.artifacts import ArtifactLoader; assert callable(main); load_config(); ArtifactLoader.load_deployment_bundle_json('data/artifacts/deployment')"

EXPOSE 8000

CMD ["python", "-m", "app.bootstrap"]
