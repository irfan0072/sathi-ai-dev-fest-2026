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
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
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


from app.admin.router import router as admin_router  # noqa: E402
from app.analytics.router import router as analytics_router  # noqa: E402
from app.assistant.router import router as assistant_router  # noqa: E402
from app.auth.router import router as auth_router  # noqa: E402
from app.bootstrap import readiness  # noqa: E402
from app.callcenter import worker as call_worker  # noqa: E402
from app.callcenter.router import router as callcenter_router  # noqa: E402
from app.copilot.router import router as copilot_router  # noqa: E402
from app.intelligence.router import router as intelligence_router  # noqa: E402
from app.mandates.router import router as mandates_router  # noqa: E402
from app.notify.router import router as notify_router  # noqa: E402
from app.ops.router import router as ops_router  # noqa: E402
from app.scam.router import router as scam_router  # noqa: E402
from app.settings.router import router as settings_router  # noqa: E402
from app.txn.router import router as txn_router  # noqa: E402
from app.voice.router import router as voice_router  # noqa: E402
from app.workdesk.router import router as workdesk_router  # noqa: E402

app.include_router(auth_router)
app.include_router(mandates_router)
app.include_router(analytics_router)
app.include_router(voice_router)
app.include_router(copilot_router)
app.include_router(intelligence_router)
app.include_router(notify_router)
app.include_router(ops_router)
app.include_router(settings_router)
app.include_router(txn_router)
app.include_router(callcenter_router)
app.include_router(workdesk_router)
app.include_router(admin_router)
app.include_router(assistant_router)
app.include_router(scam_router)


@app.on_event("startup")
async def start_background_worker() -> None:
    """Call retries, ring timeouts and the optional live traffic simulator."""
    call_worker.start()
    if call_worker.worker_enabled():
        from app.live.intelligence import start_refresh

        start_refresh()


@app.on_event("shutdown")
async def stop_background_worker() -> None:
    await call_worker.stop()


@app.get("/health")
def health() -> JSONResponse:
    """Check actual database, signing and curated artifact readiness."""
    diagnostics = readiness()
    return JSONResponse(
        status_code=200 if diagnostics["status"] == "ok" else 503,
        content=diagnostics,
    )
