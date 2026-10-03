"""Minimal TwiML builders. All dynamic text is XML-escaped.

Script text lives in app/voice/scripts.py (Bangla, English, Banglish). The module-level
constants below are the Bangla defaults, kept for callers that do not pass a language.
"""

from __future__ import annotations

from xml.sax.saxutils import escape, quoteattr

from app.voice import scripts

LANGUAGE, VOICE = scripts.VOICES["bn"]

# Every outcome ends with the same closing sentence, so a bystander cannot tell a
# confirmed request, a mismatch, a refusal or a silent duress signal apart.
NEUTRAL_CLOSE = scripts.line("bn", "close")
PROMPT = scripts.line("bn", "mandate_prompt")
RETRY = scripts.line("bn", "mandate_retry")
CHECK_PROMPT = scripts.line("bn", "check_prompt")
CHECK_RETRY = scripts.line("bn", "retry")
CHECK_UNCLEAR = scripts.line("bn", "unclear")
NO_INPUT = scripts.line("bn", "goodbye_no_input")


def _say(text: str, language: str = "bn") -> str:
    lang, voice = scripts.VOICES[scripts.normalize(language)]
    return f"<Say language={quoteattr(lang)} voice={quoteattr(voice)}>{escape(text)}</Say>"


def gather(action_url: str, text: str, speech: bool = False, language: str = "bn") -> str:
    # Post-cash-out checks also accept a spoken amount; the transcript and its confidence
    # are interpreted server-side and anything uncertain goes to a human supervisor.
    lang = scripts.normalize(language)
    mode = (f'input="dtmf speech" language="{scripts.SPEECH_LANGUAGE[lang]}" '
            'speechTimeout="auto"' if speech else 'input="dtmf"')
    return (
        '<?xml version="1.0" encoding="UTF-8"?><Response>'
        f'<Gather {mode} finishOnKey="#" timeout="12" numDigits="8" '
        f'actionOnEmptyResult="true" method="POST" action={quoteattr(action_url)}>'
        f"{_say(text, lang)}</Gather>{_say(scripts.line(lang, 'goodbye_no_input'), lang)}"
        "<Hangup/></Response>"
    )


def close(language: str = "bn", text: str | None = None) -> str:
    lang = scripts.normalize(language)
    return (
        '<?xml version="1.0" encoding="UTF-8"?><Response>'
        f"{_say(text or scripts.line(lang, 'close'), lang)}<Hangup/></Response>"
    )
