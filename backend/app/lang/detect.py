"""Detect Bangla, English or Banglish (Bangla written in Latin letters).

Rules, not a model: Bengali script means Bangla; Latin text is Banglish when enough of its
words are common romanized Bangla words, otherwise English. Customers are answered in the
language they use, and the choice is remembered for the next confirmation call.
"""

from __future__ import annotations

import re
from typing import Any, Callable

LANGUAGES = ("bn", "en", "banglish")
LANGUAGE_NAMES = {"bn": "বাংলা", "en": "English", "banglish": "Banglish"}

BENGALI = re.compile(r"[ঀ-৿]")
LATIN_WORD = re.compile(r"[a-z]+")

# Common romanized Bangla words (several spellings each). English stop words that look
# similar (to, the, is) are deliberately absent.
BANGLISH_WORDS = {
    "ami", "amar", "amake", "apni", "apnar", "apnake", "tumi", "tomar", "ke", "ki",
    "keno", "kemon", "kothay", "kobe", "koto", "kotto", "taka", "tk", "takar", "tako",
    "nai", "nei", "na", "hae", "ha", "hya", "haan", "ji", "jee", "acha", "accha", "achha",
    "thik", "thikache", "ache", "achhe", "chilo", "hobe", "hoy", "hoyeche", "hoise", "hoyse",
    "korbo", "korte", "korechi", "korsi", "korini", "korinai", "kori", "koren", "korun",
    "dao", "den", "diben", "dite", "dilam", "disi", "dichi", "pai", "paini", "paisi",
    "peyechi", "pelam", "bolo", "bolen", "bolun", "bujhi", "bujhlam", "bujhte", "parchi",
    "parbo", "lagbe", "lage", "lagche", "ekhon", "aj", "aaj", "kal", "gotokal", "por",
    "age", "agent", "bhai", "apu", "vai", "vaiya", "bhaiya", "dhonnobad", "dhonyobad",
    "assalamu", "salam", "alaikum", "kivabe", "kibhabe", "ekta", "ekti", "onek", "kom",
    "beshi", "besi", "hajar", "hazar", "sho", "shoto", "lakh", "ek", "dui", "tin", "teen",
    "char", "pach", "panch", "choy", "chhoy", "sat", "saat", "aat", "noy", "dosh", "kono",
    "kichu", "shob", "sob", "jonno", "theke", "diye", "kintu", "tobe", "naki", "ar", "abar",
    "help", "sahajjo", "shahajjo", "problem", "somossa", "shomossha", "balance", "tola",
    "tulte", "tulechi", "tullam", "cashout", "pathiye", "pathalam", "kar", "kader", "jodi",
}
ENGLISH_HINTS = {"the", "is", "are", "what", "my", "how", "please", "want", "did", "not",
                 "money", "received", "check", "account", "can", "you", "i", "me", "this",
                 "that", "was", "have", "much", "when", "where", "why", "who"}


def detect_language(text: str | None, default: str = "bn") -> str:
    text = (text or "").strip()
    if not text:
        return default
    bengali = len(BENGALI.findall(text))
    latin_letters = len(re.findall(r"[A-Za-z]", text))
    if bengali and bengali >= latin_letters * 0.5:
        return "bn"
    words = LATIN_WORD.findall(text.lower())
    if not words:
        return "bn" if bengali else default
    bangla = sum(1 for w in words if w in BANGLISH_WORDS)
    english = sum(1 for w in words if w in ENGLISH_HINTS)
    if bangla >= max(1, english) and bangla / len(words) >= 0.25:
        return "banglish"
    return "en"


class LanguagePrefs:
    """Per-customer language preference learned from behaviour (chat, speech, explicit)."""

    def __init__(self, get_connection: Callable) -> None:
        self._conn = get_connection

    def get(self, user_id: str, default: str = "bn") -> str:
        try:
            with self._conn() as conn, conn.cursor() as cur:
                cur.execute("SELECT language FROM customer_prefs WHERE user_id = %s;",
                            (user_id,))
                row = cur.fetchone()
        except Exception:
            return default
        return row[0] if row and row[0] in LANGUAGES else default

    def describe(self, user_id: str) -> dict[str, Any]:
        with self._conn() as conn, conn.cursor() as cur:
            cur.execute("SELECT language, source, updated_at FROM customer_prefs "
                        "WHERE user_id = %s;", (user_id,))
            row = cur.fetchone()
        if not row:
            return {"language": "bn", "source": "default", "updated_at": None}
        return {"language": row[0], "source": row[1], "updated_at": row[2].isoformat()}

    def set(self, user_id: str, language: str, source: str) -> None:
        """`explicit` choices always win; learned ones never override an explicit choice."""
        if language not in LANGUAGES:
            raise ValueError("Unsupported language")
        with self._conn() as conn, conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO customer_prefs (user_id, language, source) VALUES (%s, %s, %s)
                ON CONFLICT (user_id) DO UPDATE SET language = EXCLUDED.language,
                    source = EXCLUDED.source, updated_at = now()
                WHERE customer_prefs.source <> 'explicit' OR EXCLUDED.source = 'explicit';
                """,
                (user_id, language, source))
            conn.commit()

    def learn(self, user_id: str, text: str | None, source: str) -> str | None:
        """Remember the language of free text the customer wrote or said."""
        if not text or len(text.strip()) < 2:
            return None
        language = detect_language(text)
        try:
            self.set(user_id, language, source)
        except Exception:
            return None
        return language
