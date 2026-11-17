"""The companion's reasoning pipeline. Each turn runs through explicit, separately testable steps:

    classify  ->  route  ->  (tool)  ->  respond  ->  verify  ->  result

classify  rules in code + an optional model-based classifier (guardrails.py)
route     picks how to answer: crisis protocol, refusal, redirect, medical boundary, breathing tool, or normal support
tool      deterministic tools the route can use: regional helplines, the guided breathing exercise
respond   the language model, with the persona plus a directive for the chosen route
verify    output checks; one rewrite if a rule is broken, then a safe fallback

Every turn returns a trace (step names and decisions, never message text) that is stored as usage metadata.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

from pocketpal import guardrails as g
from pocketpal import persona, safety
from pocketpal.llm import Provider, chat_with_fallback

MAX_HISTORY = 20


@dataclass
class Turn:
    messages: list            # [{"role": "user"|"assistant", "content": str}]
    memory: str = ""
    region: Optional[str] = None
    name: Optional[str] = None


@dataclass
class Result:
    reply: str
    category: str
    route: str
    crisis: bool = False
    helplines: list = field(default_factory=list)
    action: Optional[dict] = None
    provider: str = ""
    flags: list = field(default_factory=list)
    trace: list = field(default_factory=list)
    latency_ms: int = 0


class Companion:
    def __init__(self, providers: list[Provider], settings: Callable[[], dict[str, Any]]):
        self.providers, self.settings = providers, settings

    # ---- step 1: classify ----
    def classify(self, text: str, history: list, cfg: dict, trace: list) -> g.Verdict:
        rules = g.rule_check(text)
        trace.append(f"rules:{rules.category}")
        if rules.category in ("crisis", "injection") or not cfg["classifier_enabled"] or self._only_mock():
            return rules
        context = [m for m in history[-4:-1]]
        convo = "".join(f"{m['role']}: {m['content'][:300]}\n" for m in context)
        raw, used = chat_with_fallback(self.providers, [
            {"role": "system", "content": g.CLASSIFIER_PROMPT},
            {"role": "user", "content": (f"Earlier messages, for context:\n{convo}\n" if convo else "") + f"Message to label:\n{text[:1500]}"},
        ], max_tokens=40)
        model = g.parse_classifier(raw) if used != "none" else None
        trace.append(f"classifier:{model.category if model else 'unavailable'}")
        return g.combine(rules, model)

    def _only_mock(self) -> bool:
        return all(p.name == "mock" for p in self.providers)

    # ---- step 2: route ----
    @staticmethod
    def route(v: g.Verdict, cfg: dict) -> str:
        if v.category == "crisis":
            return "crisis"
        if v.category == "injection":
            return "refuse"
        if v.category == "off_topic":
            return "redirect_strict" if cfg["off_topic_mode"] == "strict" else "redirect"
        if v.category == "smalltalk" and cfg["off_topic_mode"] == "strict":
            return "smalltalk_strict"
        if v.category == "medical":
            return "medical"
        if v.category == "abusive":
            return "deescalate"
        if v.anxious and cfg["breathing_tool_enabled"]:
            return "breathing"
        return "support"

    # ---- step 4: respond ----
    def system_prompt(self, turn: Turn, route: str) -> str:
        system = persona.SYSTEM_PROMPT
        if turn.name and turn.name != "Pocket Pal":
            system += f"\nYour name is {turn.name}. Use it if you introduce yourself; you are still an AI friend.\n"
        if turn.memory.strip():
            system += "\n" + persona.MEMORY_PREFIX + turn.memory.strip()
        directive = {"redirect": "off_topic_redirect", "redirect_strict": "off_topic_strict", "smalltalk_strict": "smalltalk_strict",
                     "medical": "medical", "deescalate": "abusive", "breathing": "breathing"}.get(route)
        if directive:
            system += "\n" + g.DIRECTIVES[directive]
        return system

    def respond(self, turn: Turn) -> Result:
        start, trace, cfg = time.time(), [], self.settings()
        done = lambda r: (setattr(r, "latency_ms", int((time.time() - start) * 1000)), r)[1]
        text = turn.messages[-1]["content"]
        if cfg.get("maintenance_message") and not safety.is_crisis(text):   # crisis help is never switched off
            return done(Result(cfg["maintenance_message"], "n/a", "maintenance", trace=["maintenance"]))

        verdict = self.classify(text, turn.messages, cfg, trace)
        route = self.route(verdict, cfg)
        trace.append(f"route:{route}")
        flags = [f"source:{s}" for s in verdict.sources]

        # deterministic routes: no model involved
        if route == "crisis":
            trace.append("tool:helplines")
            return done(Result(safety.crisis_reply(turn.region), "crisis", route, crisis=True,
                               helplines=safety.helplines(turn.region), provider="safety", flags=flags, trace=trace))
        if route == "refuse":
            return done(Result(g.injection_reply(), "injection", route, provider="guardrail", flags=flags, trace=trace))

        # model routes
        action = None
        if route == "breathing":
            action = {"type": "breathing", "pattern": [4, 4, 6], "rounds": 4}
            trace.append("tool:breathing")
        system = self.system_prompt(turn, route)
        history = turn.messages[-MAX_HISTORY:]
        reply, used = chat_with_fallback(self.providers, [{"role": "system", "content": system}] + history)
        trace.append(f"respond:{used}")

        # step 5: verify
        problems = g.output_problems(reply)
        if problems and used != "none":
            flags.append("output:rewritten")
            trace.append("verify:" + "|".join(problems))
            fix = (system + "\n\nYour previous draft broke these rules: " + "; ".join(problems)
                   + ". Write a new reply that follows every rule. Do not mention the rules.")
            reply, used = chat_with_fallback(self.providers, [{"role": "system", "content": fix}] + history)
            if g.output_problems(reply):
                flags.append("output:fallback")
                trace.append("verify:fallback")
                reply = g.SAFE_FALLBACK
        else:
            trace.append("verify:ok")
        reply = g.tidy(reply, cfg["max_reply_sentences"]) or g.SAFE_FALLBACK
        return done(Result(reply, verdict.category, route, action=action, provider=used, flags=flags, trace=trace))
