"""HMH AI — real AI chat client (OpenAI-compatible) + intent detection.

Uses only the Python standard library (urllib), so no new Android
build dependency is needed. Works with any OpenAI-compatible API:
Google Gemini (default), Groq, OpenAI, DeepSeek, OpenRouter, etc.
"""

import json
import re
import urllib.error
import urllib.request

DEFAULT_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/openai/"
DEFAULT_MODEL = "gemini-2.5-flash"

SYSTEM_PROMPT = (
    "You are HMH AI, the AI assistant built into the MFS HMH "
    "(My Face Studio) Android app. The app has these features: "
    "Face Scan, Face Enhance, Face Blend, Face Swap, and this chat. "
    "Reply in the same language the user writes in (Burmese or English). "
    "Be concise, friendly and helpful. If the user asks to perform one of "
    "the app features, tell them to tap the corresponding button in the "
    "main menu (or use the quick action button below)."
)

ACTION_KEYWORDS = {
    "scan": ["scan", "scanning", "စကင်း", "စကင်", "မျက်နှာစစ်"],
    "enhance": ["enhance", "enhancing", "မြှင့်", "အရည်အသွေး"],
    "blend": ["blend", "blending", "merge", "ပေါင်း", "ရော"],
    "swap": ["swap", "swapping", "ဖလှယ်", "လဲလှယ်"],
}


class AIClient:
    """Minimal OpenAI-compatible chat client."""

    def __init__(self, base_url, api_key, model):
        self.base_url = (base_url or DEFAULT_BASE_URL).strip().rstrip("/")
        self.api_key = (api_key or "").strip()
        self.model = model or DEFAULT_MODEL

    @property
    def configured(self):
        return bool(self.api_key)

    def chat(self, messages):
        """Send the full message history; return the assistant reply.

        Raises RuntimeError with a user-friendly message on any failure.
        """
        if not self.api_key:
            raise RuntimeError(
                "API key မထည့်ရသေးပါ။ Settings မှာ ထည့်ပေးပါ။"
            )

        url = self.base_url
        if not url.endswith("/chat/completions"):
            url = url + "/chat/completions"

        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": 0.7,
        }

        request = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "Authorization": "Bearer " + self.api_key,
            },
            method="POST",
        )

        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                data = json.loads(
                    response.read().decode("utf-8", errors="replace")
                )
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", errors="replace")
            raise RuntimeError(
                "AI server error (%s): %s" % (e.code, body[:300])
            )
        except urllib.error.URLError as e:
            raise RuntimeError(
                "Network error — internet စစ်ကြည့်ပါ: %s" % e.reason
            )
        except Exception as e:
            raise RuntimeError("AI request failed: %s" % e)

        try:
            return data["choices"][0]["message"]["content"].strip()
        except (KeyError, IndexError, TypeError):
            raise RuntimeError(
                "AI response ဖတ်လို့မရပါ: %s" % str(data)[:200]
            )


def detect_action(text):
    """Detect which app feature the user's message asks for.

    Returns the action key ("scan"/"enhance"/"blend"/"swap") or None.
    English keywords use word boundaries; Burmese keywords use substring.
    """
    lowered = text.lower()

    for action, keywords in ACTION_KEYWORDS.items():
        for keyword in keywords:
            if keyword.isascii():
                if re.search(r"\b" + re.escape(keyword) + r"\b", lowered):
                    return action
            else:
                if keyword in lowered:
                    return action

    return None
