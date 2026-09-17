"""Thin Claude API client with file-based prompt templates.

Prompts live in prompts/<name>.md and use string.Template placeholders
($variable). We deliberately use string.Template instead of str.format:
the prompt files embed JSON examples full of literal braces, which would
explode with str.format but are inert with $-style placeholders.

The API key is read from the environment (a local .env is loaded via
python-dotenv). No key is ever hardcoded.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from string import Template
from typing import Any

from anthropic import Anthropic
from dotenv import load_dotenv

DEFAULT_MODEL = "claude-sonnet-5"

# prompts/ sits next to the lender_engine package, at the project root.
PROMPTS_DIR = Path(__file__).resolve().parent.parent / "prompts"

# Anthropic server-side web search tool. The API executes searches for us;
# results come back inside the same response.
WEB_SEARCH_TOOL: dict[str, Any] = {
    "type": "web_search_20250305",
    "name": "web_search",
    "max_uses": 8,
}

# A long web-search turn can stop with stop_reason "pause_turn". Resending
# the conversation resumes it. Cap the resumes so we can never loop forever.
MAX_CONTINUATIONS = 5

# One JSON line per prompt call: tokens in and out, web searches. Git-ignored.
USAGE_LOG = Path(os.environ.get("LENDER_ENGINE_USAGE_LOG", "outputs/llm_usage.jsonl"))


class ClaudeClient:
    """Calls the Anthropic Messages API using named prompt templates."""

    def __init__(self, model: str | None = None) -> None:
        load_dotenv()
        api_key = os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            raise RuntimeError(
                "ANTHROPIC_API_KEY is not set. Copy .env.example to .env and "
                "add your key, or export it in your shell."
            )
        self.model = model or os.environ.get("LENDER_ENGINE_MODEL") or DEFAULT_MODEL
        self._client = Anthropic(api_key=api_key)
        # Running totals for the process, printed per call and appended to
        # USAGE_LOG so the cost of a run can be read back after the fact.
        self.usage = {"calls": 0, "input_tokens": 0, "output_tokens": 0,
                      "cache_read_input_tokens": 0, "web_search_requests": 0}

    def complete(
        self,
        prompt_name: str,
        variables: dict[str, str],
        web_search: bool = False,
        max_tokens: int = 4096,
    ) -> str:
        """Render prompts/<prompt_name>.md with `variables` and run it.

        When web_search is True the server-side web search tool is attached
        (max 8 searches). Returns the final text of the response.
        """
        prompt = self._render_prompt(prompt_name, variables)
        messages: list[dict[str, Any]] = [{"role": "user", "content": prompt}]
        kwargs: dict[str, Any] = {}
        if web_search:
            kwargs["tools"] = [WEB_SEARCH_TOOL]

        # Text can arrive across several responses when a web-search turn
        # pauses and resumes, so collect it on every iteration, not just the
        # last, or partial output would be silently dropped.
        texts: list[str] = []
        final_response = None
        usage_events: list[Any] = []
        for _ in range(MAX_CONTINUATIONS + 1):
            response = self._client.messages.create(
                model=self.model,
                max_tokens=max_tokens,
                messages=messages,
                **kwargs,
            )
            usage_events.append(response.usage)
            texts.extend(
                block.text for block in response.content if block.type == "text"
            )
            if response.stop_reason != "pause_turn":
                final_response = response
                break
            # Paused mid web-search turn: echo the partial turn back and
            # the API resumes where it left off.
            messages.append({"role": "assistant", "content": response.content})
        else:
            raise RuntimeError(
                f"Prompt '{prompt_name}' still paused (pause_turn) after "
                f"{MAX_CONTINUATIONS} resume(s); giving up."
            )

        self._record_usage(prompt_name, usage_events)

        if final_response.stop_reason == "max_tokens":
            print(
                f"WARNING: prompt '{prompt_name}' hit max_tokens "
                f"({max_tokens}); output is likely truncated."
            )

        return "".join(texts).strip()

    def _record_usage(self, prompt_name: str, usages: list[Any]) -> None:
        """Sum the usage of one prompt (over its continuations), print and log it."""
        row = {"ts": time.strftime("%Y-%m-%dT%H:%M:%S"), "model": self.model, "prompt": prompt_name,
               "input_tokens": 0, "output_tokens": 0, "cache_read_input_tokens": 0, "web_search_requests": 0}
        for u in usages:
            row["input_tokens"] += getattr(u, "input_tokens", 0) or 0
            row["output_tokens"] += getattr(u, "output_tokens", 0) or 0
            row["cache_read_input_tokens"] += getattr(u, "cache_read_input_tokens", 0) or 0
            stu = getattr(u, "server_tool_use", None)
            row["web_search_requests"] += (getattr(stu, "web_search_requests", 0) or 0) if stu else 0
        self.usage["calls"] += 1
        for key in ("input_tokens", "output_tokens", "cache_read_input_tokens", "web_search_requests"):
            self.usage[key] += row[key]
        print(
            f"  usage[{prompt_name}]: in={row['input_tokens']} out={row['output_tokens']} "
            f"searches={row['web_search_requests']} | run total: in={self.usage['input_tokens']} "
            f"out={self.usage['output_tokens']} searches={self.usage['web_search_requests']}"
        )
        try:
            USAGE_LOG.parent.mkdir(parents=True, exist_ok=True)
            with USAGE_LOG.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(row) + "\n")
        except OSError:
            pass  # usage logging must never break a run

    @staticmethod
    def _render_prompt(prompt_name: str, variables: dict[str, str]) -> str:
        path = PROMPTS_DIR / f"{prompt_name}.md"
        if not path.exists():
            raise FileNotFoundError(f"Prompt template not found: {path}")
        try:
            rendered = Template(path.read_text(encoding="utf-8")).substitute(variables)
        except (KeyError, ValueError) as exc:
            raise RuntimeError(
                f"Prompt '{prompt_name}' failed to render ({exc}); it must use "
                f"string.Template placeholders and $$ for a literal dollar sign; "
                f"got variables: {sorted(variables)}"
            ) from exc
        # Guard against a prompt written with str.format-style {name} braces:
        # string.Template leaves those untouched, so a leftover {var} means the
        # placeholder would never be filled.
        for name in variables:
            if "{" + name + "}" in rendered:
                raise RuntimeError(
                    f"Prompt '{prompt_name}' contains a str.format-style placeholder "
                    f"{{{name}}}, but this engine renders prompts with string.Template. "
                    f"Use ${name} instead (and $$ for a literal dollar sign)."
                )
        return rendered
