"""Shared by every step: load .env, create the Claude client, pick the model. Read this first (10 lines of logic)."""

import os
from pathlib import Path

import anthropic


def load_env() -> None:
    """Read KEY=VALUE lines from .env (current folder or the module folder). Shell variables always win."""
    for path in (Path.cwd() / ".env", Path(__file__).resolve().parent.parent / ".env"):
        if path.is_file():
            for line in path.read_text(encoding="utf-8-sig").splitlines():
                key, sep, value = line.partition("=")
                if sep and not key.strip().startswith("#"):
                    os.environ.setdefault(key.strip(), value.split(" #")[0].strip())
            return


load_env()
MODEL = os.getenv("AGENT_MODEL", "claude-haiku-5-5")  # cheap + fast; set AGENT_MODEL=claude-sonnet-5-5 for smarter


def client() -> anthropic.Anthropic:
    if not os.getenv("ANTHROPIC_API_KEY"):
        raise SystemExit("ANTHROPIC_API_KEY is not set: put it in .env or run  $env:ANTHROPIC_API_KEY = 'sk-ant-...'")
    return anthropic.Anthropic(max_retries=2, timeout=30)


def text_of(resp) -> str:
    """Join the text blocks of a response (a reply can also contain thinking or tool_use blocks)."""
    return "".join(b.text for b in resp.content if b.type == "text")
