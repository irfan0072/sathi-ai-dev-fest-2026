"""FastAPI application entry point for Sathi backend."""

import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI(
    title="Sathi Backend",
    version="0.1.0",
)

# Restrict CORS origins; read from environment or default to local console
raw_origins = os.getenv("CORS_ORIGINS", "http://localhost:13000,http://127.0.0.1:13000")
allowed_origins = [orig.strip() for orig in raw_origins.split(",") if orig.strip()]

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["*"],
)

from app.mandates.router import router as mandates_router  # noqa: E402

app.include_router(mandates_router)


@app.get("/health")
def health() -> dict[str, str]:
    """Health check endpoint returning generic status."""
    return {"status": "ok"}
