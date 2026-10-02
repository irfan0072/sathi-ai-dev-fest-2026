"""FastAPI application entry point for Sathi backend."""

from fastapi import FastAPI

app = FastAPI(
    title="Sathi Backend",
    version="0.1.0",
)


@app.get("/health")
def health() -> dict[str, str]:
    """Health check endpoint returning generic status."""
    return {"status": "ok"}
