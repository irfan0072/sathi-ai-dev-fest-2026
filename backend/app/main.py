"""FastAPI application entry point for Sathi backend."""

from __future__ import annotations

import os
from typing import Any

from fastapi import FastAPI, HTTPException, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

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


@app.exception_handler(StarletteHTTPException)
async def starlette_http_exception_handler(
    request: Request, exc: StarletteHTTPException
) -> JSONResponse:
    """Preserve top-level error contract envelope if detail is formatted as error object."""
    if isinstance(exc.detail, dict) and "error" in exc.detail:
        return JSONResponse(status_code=exc.status_code, content=exc.detail)
    return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException) -> JSONResponse:
    """Preserve top-level error contract envelope if detail is formatted as error object."""
    if isinstance(exc.detail, dict) and "error" in exc.detail:
        return JSONResponse(status_code=exc.status_code, content=exc.detail)
    return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})


def _sanitize_validation_errors(raw_errors: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return structural diagnostics without request input or exception context."""
    return [
        {
            "loc": list(err.get("loc", ())),
            "msg": "Invalid field value."
            if err.get("type") == "value_error"
            else str(err.get("msg", "Invalid field value.")),
            "type": str(err.get("type", "")),
        }
        for err in raw_errors
    ]


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    """Return safe top-level error envelope and sanitized detail for 422 validation failures."""
    clean_errors = _sanitize_validation_errors(exc.errors())
    first_msg = clean_errors[0]["msg"] if clean_errors else "Validation error"
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content={
            "error": {
                "code": "VALIDATION_ERROR",
                "message": first_msg,
                "details": clean_errors,
            },
            "detail": clean_errors,
        },
    )


from app.analytics.router import router as analytics_router  # noqa: E402
from app.auth.jwt import is_jwt_secret_configured  # noqa: E402
from app.auth.router import router as auth_router  # noqa: E402
from app.mandates.router import router as mandates_router  # noqa: E402

app.include_router(auth_router)
app.include_router(mandates_router)
app.include_router(analytics_router)


@app.get("/health")
def health() -> dict[str, Any]:
    """Health check endpoint returning diagnostic status fail-closed without credentials."""
    db_configured = bool(os.getenv("DATABASE_URL") or os.getenv("SATHI_TEST_DATABASE_URL"))
    signing_configured = is_jwt_secret_configured()
    overall_status = "ok" if (db_configured and signing_configured) else "degraded"

    return {
        "status": overall_status,
        "database": "configured" if db_configured else "unconfigured",
        "auth_signing": "configured" if signing_configured else "unconfigured",
    }
