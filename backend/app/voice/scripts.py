"""What the confirmation call says, in Bangla, English and Banglish.

Design rules for every script:
- Polite, short sentences; say who is calling and why before asking anything.
- Never say the amount, the agent's name, the balance or any account detail: the customer
  states the amount themselves, so nobody standing nearby learns anything.
- Never ask for a PIN, OTP or password, and say so.
- Same closing sentence for every outcome (confirmed, refused, mismatch, secret help), so a
  bystander cannot tell what the customer answered.
- Silence is not an answer: the question is repeated once, then the call ends politely and
  is retried later. Key 9 reaches a person; key 8 switches language.

Banglish customers write Bangla in Latin letters but speak Bangla, so their voice script is
colloquial spoken Bangla with the English loanwords they use every day.
"""

from __future__ import annotations

from typing import Any

VOICES = {
    "bn": ("bn-IN", "Google.bn-IN-Standard-A"),
    "banglish": ("bn-IN", "Google.bn-IN-Standard-A"),
    "en": ("en-IN", "Google.en-IN-Standard-A"),
}
SPEECH_LANGUAGE = {"bn": "bn-BD", "banglish": "bn-BD", "en": "en-IN"}
NEXT_LANGUAGE = {"bn": "en", "banglish": "en", "en": "bn"}

SCRIPTS: dict[str, dict[str, str]] = {
    "bn": {
        "check_prompt": (
            "আসসালামু আলাইকুম। আমি সাথী, ইউপে-এর নিরাপত্তা সহকারী। "
            "আপনার একাউন্ট থেকে এইমাত্র একটি ক্যাশ-আউট হয়েছে, তাই আমরা নিশ্চিত হতে ফোন করেছি। "
            "আপনি হাতে কত টাকা পেয়েছেন, তা কীপ্যাডে লিখে হ্যাশ চাপুন, অথবা বলুন। "
            "আপনি এই ক্যাশ-আউট না করে থাকলে শুধু হ্যাশ চাপুন। "
            "কারো সাথে কথা বলতে ৯ চাপুন। ইংরেজির জন্য ৮ চাপুন। "
            "আমরা কখনো আপনার পিন বা ওটিপি জানতে চাই না।"
        ),
        "mandate_prompt": (
            "আসসালামু আলাইকুম। আমি সাথী, ইউপে-এর নিরাপত্তা সহকারী। "
            "একজন এজেন্ট আপনার একাউন্ট থেকে টাকা তোলার অনুরোধ করেছেন। "
            "আপনি কত টাকা তুলতে চান, তা কীপ্যাডে লিখে হ্যাশ চাপুন। "
            "আপনি অনুরোধ না করে থাকলে শুধু হ্যাশ চাপুন। "
            "কখনো কাউকে আপনার পিন বলবেন না।"
        ),
        "retry": "দুঃখিত, পরিমাণটি মেলেনি। আরেকবার, হাতে কত টাকা পেয়েছেন লিখে হ্যাশ চাপুন।",
        "mandate_retry": "পরিমাণ মেলেনি। আবার টাকার পরিমাণ লিখে হ্যাশ চাপুন।",
        "unclear": "দুঃখিত, আপনার উত্তর ঠিক বুঝতে পারিনি। টাকার পরিমাণটি কীপ্যাডে লিখে হ্যাশ চাপুন।",
        "no_input": "আমি কোনো উত্তর পাইনি। কোনো তাড়া নেই। হাতে কত টাকা পেয়েছেন, লিখে হ্যাশ চাপুন।",
        "goodbye_no_input": "ঠিক আছে, আমরা একটু পরে আবার ফোন করব। ধন্যবাদ।",
        "handoff": "অবশ্যই। আমাদের একজন সুপারভাইজার শিগগিরই আপনাকে এই নম্বরে ফোন করবেন। ধন্যবাদ।",
        "close": "ধন্যবাদ। আপনার উত্তর রেকর্ড করা হয়েছে। আল্লাহ হাফেজ।",
    },
    "banglish": {
        "check_prompt": (
            "আসসালামু আলাইকুম, আমি সাথী, ইউপে থেকে বলছি। "
            "আপনার একাউন্ট থেকে একটু আগে একটা ক্যাশ-আউট হয়েছে, তাই কনফার্ম করার জন্য কল করলাম। "
            "হাতে কত টাকা পেয়েছেন, সেটা কীপ্যাডে টাইপ করে হ্যাশ চাপুন, বা মুখে বলুন। "
            "ক্যাশ-আউটটা আপনি না করে থাকলে শুধু হ্যাশ চাপুন। "
            "কারো সাথে কথা বলতে চাইলে নাইন চাপুন। ইংলিশের জন্য এইট চাপুন। "
            "আমরা কখনো আপনার পিন বা ওটিপি চাইব না।"
        ),
        "mandate_prompt": (
            "আসসালামু আলাইকুম, আমি সাথী, ইউপে থেকে বলছি। "
            "একজন এজেন্ট আপনার একাউন্ট থেকে টাকা তোলার রিকোয়েস্ট করেছেন। "
            "কত টাকা তুলতে চান, টাইপ করে হ্যাশ চাপুন। রিকোয়েস্ট না করে থাকলে শুধু হ্যাশ চাপুন। "
            "কাউকে কখনো পিন বলবেন না।"
        ),
        "retry": "সরি, অ্যামাউন্টটা মেলেনি। আরেকবার টাইপ করে হ্যাশ চাপুন।",
        "mandate_retry": "অ্যামাউন্ট মেলেনি। আবার টাইপ করে হ্যাশ চাপুন।",
        "unclear": "সরি, ঠিক বুঝতে পারিনি। অ্যামাউন্টটা কীপ্যাডে টাইপ করে হ্যাশ চাপুন।",
        "no_input": "কোনো উত্তর পাইনি, সমস্যা নেই। হাতে কত টাকা পেয়েছেন, টাইপ করে হ্যাশ চাপুন।",
        "goodbye_no_input": "ঠিক আছে, একটু পরে আবার কল করব। থ্যাংক ইউ।",
        "handoff": "অবশ্যই। আমাদের একজন সুপারভাইজার শিগগিরই এই নম্বরে আপনাকে কল করবেন। থ্যাংক ইউ।",
        "close": "থ্যাংক ইউ। আপনার উত্তর রেকর্ড হয়ে গেছে। আল্লাহ হাফেজ।",
    },
    "en": {
        "check_prompt": (
            "Hello, this is Sathi, the safety assistant from upay. "
            "A cash-out was just made from your account, so we are calling to confirm it. "
            "Please type the amount of cash you received and press hash, or say it. "
            "If you did not make this cash-out, just press hash. "
            "To talk to a person, press 9. For Bangla, press 8. "
            "We will never ask for your PIN or OTP."
        ),
        "mandate_prompt": (
            "Hello, this is Sathi, the safety assistant from upay. "
            "An agent has asked to withdraw money from your account. "
            "Type the amount you want to withdraw and press hash. "
            "If you did not ask for this, just press hash. Never tell anyone your PIN."
        ),
        "retry": "Sorry, that amount did not match. Please type the cash you received again "
                 "and press hash.",
        "mandate_retry": "The amount did not match. Please type it again and press hash.",
        "unclear": "Sorry, I did not understand. Please type the amount on the keypad and "
                   "press hash.",
        "no_input": "I did not hear an answer. Take your time. Type the cash you received and "
                    "press hash.",
        "goodbye_no_input": "No problem, we will call you again a little later. Thank you.",
        "handoff": "Of course. A supervisor will call you on this number shortly. Thank you.",
        "close": "Thank you. Your answer has been recorded. Goodbye.",
    },
}


def normalize(language: Any) -> str:
    return language if language in SCRIPTS else "bn"


def line(language: Any, key: str) -> str:
    return SCRIPTS[normalize(language)][key]


def prompt_key(call: dict[str, Any]) -> str:
    return "check_prompt" if call.get("check_id") else "mandate_prompt"
