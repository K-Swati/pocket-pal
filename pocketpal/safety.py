"""Crisis detection runs in code before the model, so it cannot be talked out of or skipped."""

from __future__ import annotations

import re

_CRISIS = re.compile(
    r"""\b(
        kill(ing)?\s+my\s*self | end(ing)?\s+(my|it)\s+(life|all) | end\s+it\s+all | take\s+my\s+(own\s+)?life |
        suicid\w* | want(ed)?\s+to\s+die | wanna\s+die | wish\s+i\s+(was|were)\s+dead | better\s+off\s+dead |
        don'?t\s+want\s+to\s+(live|be\s+alive|exist) | no\s+(reason|point)\s+(to|in)\s+(live|living|going\s+on) |
        hurt(ing)?\s+my\s*self | harm(ing)?\s+my\s*self | self[\s-]?harm\w* | cut(ting)?\s+my\s*self |
        overdos\w* | not\s+be\s+(here|around)\s+any\s*more
    )\b""",
    re.IGNORECASE | re.VERBOSE,
)

HELPLINES: dict[str, list[dict[str, str]]] = {
    "US": [{"name": "988 Suicide & Crisis Lifeline", "contact": "Call or text 988"}],
    "CA": [{"name": "9-8-8 Suicide Crisis Helpline", "contact": "Call or text 988"}],
    "GB": [{"name": "Samaritans", "contact": "Call 116 123"}, {"name": "Shout", "contact": "Text SHOUT to 85258"}],
    "IE": [{"name": "Samaritans", "contact": "Call 116 123"}],
    "IN": [{"name": "Tele-MANAS", "contact": "Call 14416 or 1-800-891-4416"}],
    "AU": [{"name": "Lifeline", "contact": "Call 13 11 14"}],
    "NZ": [{"name": "Need to talk?", "contact": "Call or text 1737"}],
}
FALLBACK = [{"name": "Find a helpline near you", "contact": "findahelpline.com"}]
EMERGENCY = {"name": "If you are in immediate danger", "contact": "Call your local emergency number"}


def is_crisis(text: str) -> bool:
    return bool(_CRISIS.search(text))


def helplines(region: str | None) -> list[dict[str, str]]:
    return HELPLINES.get((region or "").upper(), FALLBACK) + [EMERGENCY]


def crisis_reply(region: str | None) -> str:
    first = helplines(region)[0]
    return (
        "I'm really glad you told me, and I'm staying right here with you. "
        "What you're feeling matters, and you deserve support from a real person right now. "
        f"Could you reach out to {first['name']}? {first['contact']}. "
        "If you're in immediate danger, please call your local emergency number. "
        "Would you tell me a little about what's happening tonight?"
    )
