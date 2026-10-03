"""Minimal TwiML builders. All dynamic text is XML-escaped."""

from __future__ import annotations

from xml.sax.saxutils import escape, quoteattr

LANGUAGE = "bn-IN"
VOICE = "Google.bn-IN-Standard-A"

# Every outcome ends with the same closing sentence, so a bystander cannot tell a
# confirmed request, a mismatch, a refusal or a silent duress signal apart.
NEUTRAL_CLOSE = "ধন্যবাদ। আপনার উত্তর রেকর্ড করা হয়েছে। আল্লাহ হাফেজ।"

PROMPT = (
    "আসসালামু আলাইকুম। এটি সাথী নিরাপত্তা কল। "
    "একজন এজেন্ট আপনার একাউন্ট থেকে টাকা তোলার অনুরোধ করেছেন। "
    "আপনি কত টাকা তুলতে চান, তা কীপ্যাডে লিখে হ্যাশ চাপুন। "
    "আপনি অনুরোধ না করে থাকলে শুধু হ্যাশ চাপুন। "
    "কখনো কাউকে আপনার পিন বলবেন না।"
)
RETRY = "পরিমাণ মেলেনি। আবার টাকার পরিমাণ লিখে হ্যাশ চাপুন।"
NO_INPUT = "কোনো উত্তর পাওয়া যায়নি।"


def _say(text: str) -> str:
    return f"<Say language={quoteattr(LANGUAGE)} voice={quoteattr(VOICE)}>{escape(text)}</Say>"


def gather(action_url: str, text: str) -> str:
    return (
        '<?xml version="1.0" encoding="UTF-8"?><Response>'
        f'<Gather input="dtmf" finishOnKey="#" timeout="12" numDigits="8" '
        f'actionOnEmptyResult="true" method="POST" action={quoteattr(action_url)}>'
        f"{_say(text)}</Gather>{_say(NO_INPUT)}<Hangup/></Response>"
    )


def close() -> str:
    return (
        '<?xml version="1.0" encoding="UTF-8"?><Response>'
        f"{_say(NEUTRAL_CLOSE)}<Hangup/></Response>"
    )
