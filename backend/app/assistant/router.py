"""Customer assistant and language preference API."""

from __future__ import annotations

from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from app.auth.dependencies import require_roles
from app.auth.models import AuthenticatedPrincipal
from app.mandates.router import get_mandate_service

router = APIRouter(prefix="/api/v1", tags=["assistant"])
Customer = Annotated[AuthenticatedPrincipal, Depends(require_roles("customer_channel"))]

_override: Any = None


def get_assistant():
    """Assistant bound to the current database; an LLM is used only when a key is saved."""
    if _override is not None:
        return _override
    from app.assistant.engine import Assistant
    from app.copilot.investigator import clients_from_env
    from app.settings.credentials import runtime_env
    from app.settings.router import get_settings

    service = get_mandate_service()
    try:
        values = get_settings().values()
        clients = clients_from_env(runtime_env(service.get_connection),
                                   order=values["ai.provider_order"],
                                   gemini_model=values["ai.gemini_model"],
                                   openai_model=values["ai.openai_model"])
    except Exception:
        clients = []
    return Assistant(service.get_connection, clients)


def set_assistant(assistant: Any) -> None:
    global _override
    _override = assistant


class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=1000)


@router.post("/assistant/chat")
def chat(body: ChatRequest, principal: Customer) -> Any:
    reply = get_assistant().chat(principal.subject, body.message)
    return {"reply": reply.text, "language": reply.language, "intent": reply.intent,
            "guard": reply.guard, "provider": reply.provider,
            "action": ({"type": reply.action["type"]} if reply.action else None),
            "suggestions": reply.suggestions}


@router.get("/assistant/history")
def history(principal: Customer) -> Any:
    return {"messages": get_assistant().history(principal.subject)}


class LanguageRequest(BaseModel):
    language: Literal["bn", "en", "banglish"]


@router.get("/me/language")
def my_language(principal: Customer) -> Any:
    from app.lang.detect import LanguagePrefs

    return LanguagePrefs(get_mandate_service().get_connection).describe(principal.subject)


@router.put("/me/language")
def set_language(body: LanguageRequest, principal: Customer) -> Any:
    from app.lang.detect import LanguagePrefs

    prefs = LanguagePrefs(get_mandate_service().get_connection)
    prefs.set(principal.subject, body.language, "explicit")
    return prefs.describe(principal.subject)
