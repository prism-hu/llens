from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import Any

import httpx


@dataclass
class GenerationResult:
    reasoning_content: str = ""
    content: str = ""
    prompt_tokens: int = 0
    completion_tokens: int = 0
    reasoning_tokens: int = 0
    ttft_ms: float | None = None
    ttat_ms: float | None = None
    total_time_ms: float | None = None
    finish_reason: str | None = None

    @property
    def answer_tokens(self) -> int:
        return max(self.completion_tokens - self.reasoning_tokens, 0)


def generate(
    base_url: str,
    model: str,
    messages: list[dict[str, Any]],
    *,
    temperature: float = 0.0,
    top_p: float = 1.0,
    max_tokens: int = 32768,
    extra_body: dict[str, Any] | None = None,
    timeout: float = 600.0,
) -> GenerationResult:
    """Stream a chat completion and capture TTFT/TTAT/think token counts.

    TTFT = time to the first token (reasoning or answer, whichever comes first).
    TTAT = time to the first answer-content token (post `</think>`).
    For models without thinking, TTAT == TTFT.
    """
    body: dict[str, Any] = {
        "model": model,
        "messages": messages,
        "stream": True,
        "stream_options": {"include_usage": True},
        "temperature": temperature,
        "top_p": top_p,
        "max_tokens": max_tokens,
    }
    if extra_body:
        body.update(extra_body)

    result = GenerationResult()
    t0 = time.perf_counter()

    with httpx.stream(
        "POST",
        f"{base_url.rstrip('/')}/v1/chat/completions",
        json=body,
        timeout=timeout,
    ) as response:
        response.raise_for_status()
        for line in response.iter_lines():
            if not line or not line.startswith("data: "):
                continue
            payload = line[len("data: ") :]
            if payload == "[DONE]":
                break

            chunk = json.loads(payload)

            usage = chunk.get("usage")
            if usage:
                result.prompt_tokens = usage.get("prompt_tokens", 0) or 0
                result.completion_tokens = usage.get("completion_tokens", 0) or 0
                # SGLang exposes reasoning_tokens at usage top-level; OpenAI spec
                # nests it under completion_tokens_details. Accept either.
                rt = usage.get("reasoning_tokens")
                if rt is None:
                    rt = (usage.get("completion_tokens_details") or {}).get("reasoning_tokens")
                result.reasoning_tokens = rt or 0

            choices = chunk.get("choices") or []
            if not choices:
                continue
            choice = choices[0]
            delta = choice.get("delta") or {}
            now_ms = (time.perf_counter() - t0) * 1000

            rc = delta.get("reasoning_content")
            if rc:
                if result.ttft_ms is None:
                    result.ttft_ms = now_ms
                result.reasoning_content += rc

            c = delta.get("content")
            if c:
                if result.ttft_ms is None:
                    result.ttft_ms = now_ms
                if result.ttat_ms is None:
                    result.ttat_ms = now_ms
                result.content += c

            if choice.get("finish_reason"):
                result.finish_reason = choice["finish_reason"]

    result.total_time_ms = (time.perf_counter() - t0) * 1000
    return result


def _main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="Smoke test for streaming client.")
    parser.add_argument("--base-url", default="http://localhost:8000")
    parser.add_argument("--model", default="glm-5.1")
    parser.add_argument("--prompt", default="日本の首都はどこですか。一文で答えて。")
    parser.add_argument("--no-think", action="store_true")
    parser.add_argument("--max-tokens", type=int, default=2048)
    args = parser.parse_args()

    extra: dict[str, Any] = {}
    if args.no_think:
        extra["chat_template_kwargs"] = {"enable_thinking": False}

    r = generate(
        args.base_url,
        args.model,
        [{"role": "user", "content": args.prompt}],
        max_tokens=args.max_tokens,
        extra_body=extra,
    )

    def fmt(x: float | None) -> str:
        return f"{x:.0f}ms" if x is not None else "-"

    print(f"TTFT          : {fmt(r.ttft_ms)}")
    print(f"TTAT          : {fmt(r.ttat_ms)}")
    print(f"total         : {fmt(r.total_time_ms)}")
    print(f"prompt_tokens : {r.prompt_tokens}")
    print(f"reasoning_tok : {r.reasoning_tokens}")
    print(f"answer_tok    : {r.answer_tokens}")
    print(f"finish        : {r.finish_reason}")
    if r.reasoning_content:
        head = r.reasoning_content[:300].replace("\n", " ")
        print(f"\n--- reasoning (head) ---\n{head}{'...' if len(r.reasoning_content) > 300 else ''}")
    print(f"\n--- answer ---\n{r.content}")


if __name__ == "__main__":
    _main()
