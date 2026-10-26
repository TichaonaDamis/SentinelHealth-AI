"""LLM providers for the epidemiology copilot (Claude primary, OpenAI secondary, offline fallback)."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass

from app.core.config import get_settings

log = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are SentinelHealth Copilot, an assistant for public-health epidemiologists.

Rules:
- Ground every statement in the SURVEILLANCE FACTS and SOURCES provided. If they do not contain the answer, say so.
- Cite sources inline as [S1], [S2] and facts as [F1], [F2]. Never invent numbers, case counts or citations.
- Distinguish signals (statistical anomalies) from confirmed outbreaks; state uncertainty and data limitations.
- Recommend proportionate public-health actions using standard practice (case investigation, lab confirmation,
  risk communication), but defer final decisions to the responsible health officer.
- Never output personal identifiers or individual-level patient details.
- Be concise and structured: short paragraphs or bullet points, suitable for a situation report."""

_PHI_PATTERNS = [
    (re.compile(r"\b\d{3}-\d{2}-\d{4}\b"), "[REDACTED-SSN]"),
    (re.compile(r"\b(?:MRN|mrn)[:#\s]*\w{5,}\b"), "[REDACTED-MRN]"),
    (re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+"), "[REDACTED-EMAIL]"),
    (re.compile(r"\(?\b\d{3}\)?[-.\s]\d{3}[-.\s]\d{4}\b"), "[REDACTED-PHONE]"),
]


def scrub_phi(text: str) -> str:
    """Defence in depth: the copilot never receives PHI, but outputs are scrubbed anyway."""
    for pattern, repl in _PHI_PATTERNS:
        text = pattern.sub(repl, text)
    return text


@dataclass
class LLMResult:
    text: str
    provider: str
    model: str | None


class LLMProvider:
    name = "base"

    async def complete(self, system: str, prompt: str) -> LLMResult:  # pragma: no cover - interface
        raise NotImplementedError


class AnthropicProvider(LLMProvider):
    name = "anthropic"

    def __init__(self, api_key: str, model: str, max_tokens: int):
        from anthropic import AsyncAnthropic

        self.client = AsyncAnthropic(api_key=api_key)
        self.model, self.max_tokens = model, max_tokens

    async def complete(self, system: str, prompt: str) -> LLMResult:
        resp = await self.client.messages.create(
            model=self.model, max_tokens=self.max_tokens, system=system,
            messages=[{"role": "user", "content": prompt}],
        )
        text = "".join(block.text for block in resp.content if block.type == "text")
        return LLMResult(text, self.name, self.model)


class OpenAIProvider(LLMProvider):
    name = "openai"

    def __init__(self, api_key: str, model: str, max_tokens: int):
        from openai import AsyncOpenAI

        self.client = AsyncOpenAI(api_key=api_key)
        self.model, self.max_tokens = model, max_tokens

    async def complete(self, system: str, prompt: str) -> LLMResult:
        resp = await self.client.chat.completions.create(
            model=self.model, max_completion_tokens=self.max_tokens,
            messages=[{"role": "system", "content": system}, {"role": "user", "content": prompt}],
        )
        return LLMResult(resp.choices[0].message.content or "", self.name, self.model)


class OfflineProvider(LLMProvider):
    """Deterministic, template-based answer built only from the supplied facts and sources.

    Keeps the copilot useful (and testable) without network access to an LLM.
    """

    name = "offline"

    async def complete(self, system: str, prompt: str) -> LLMResult:
        facts = re.findall(r"^\[(F\d+)\] (.+)$", prompt, flags=re.M)
        sources = re.findall(r"^\[(S\d+)\] (.+?)\n(.+?)(?=\n\[S\d+\]|\n\nQUESTION|\Z)", prompt, flags=re.M | re.S)
        task = re.search(r"QUESTION:\n(.+)", prompt, flags=re.S)
        lines = ["**Summary (offline mode — generated from structured data without an LLM)**", ""]
        if task:
            lines.append(f"_Request:_ {task.group(1).strip().splitlines()[0]}")
            lines.append("")
        if facts:
            lines.append("**Current surveillance picture**")
            lines += [f"- {text} [{ref}]" for ref, text in facts[:8]]
            lines.append("")
        if sources:
            lines.append("**Relevant guidance**")
            for ref, title, body in sources[:3]:
                snippet = " ".join(body.split()[:45])
                lines.append(f"- {title.strip()}: {snippet}… [{ref}]")
            lines.append("")
        lines.append("_Configure SENTINEL_ANTHROPIC_API_KEY or SENTINEL_OPENAI_API_KEY for narrative analysis._")
        return LLMResult("\n".join(lines), self.name, None)


class FallbackChain(LLMProvider):
    """Try providers in order; fall back on errors (outage, rate limit, timeout)."""

    def __init__(self, providers: list[LLMProvider]):
        self.providers = providers
        self.name = "+".join(p.name for p in providers)

    async def complete(self, system: str, prompt: str) -> LLMResult:
        last_exc: Exception | None = None
        for p in self.providers:
            try:
                return await p.complete(system, prompt)
            except Exception as exc:
                log.warning("LLM provider %s failed: %s", p.name, type(exc).__name__)
                last_exc = exc
        raise RuntimeError("all LLM providers failed") from last_exc


def get_llm() -> LLMProvider:
    s = get_settings()
    chain: list[LLMProvider] = []
    candidates = {
        "anthropic": lambda: AnthropicProvider(s.anthropic_api_key, s.anthropic_model, s.llm_max_tokens)
        if s.anthropic_api_key else None,
        "openai": lambda: OpenAIProvider(s.openai_api_key, s.openai_model, s.llm_max_tokens)
        if s.openai_api_key else None,
    }
    order = [s.copilot_provider] + [k for k in candidates if k != s.copilot_provider]
    for name in order:
        factory = candidates.get(name)
        provider = factory() if factory else None
        if provider:
            chain.append(provider)
    chain.append(OfflineProvider())
    return FallbackChain(chain)
