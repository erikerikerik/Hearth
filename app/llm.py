"""Replaceable local language-model boundary: one OpenAI-compatible endpoint on loopback.

Local-only by construction: any non-loopback base URL is rejected, so no configuration
mistake can send text off the machine (CLAUDE.md: no cloud fallback).
"""
import ipaddress
import json
import time
import urllib.request
from typing import Dict, Iterator, List, Tuple
from urllib.parse import urlparse


def assert_loopback(base_url: str) -> str:
    host = urlparse(base_url).hostname or ""
    try:
        ok = ipaddress.ip_address(host).is_loopback
    except ValueError:
        ok = host == "localhost"
    if not ok:
        raise ValueError("LLM endpoint must be loopback (127.0.0.1/::1/localhost); got %r" % host)
    return base_url.rstrip("/")


def stream_events(base_url: str, model: str, messages: List[Dict[str, str]], max_tokens: int = 200,
                  temperature: float = 0.7, timeout: float = 120, thinking: bool = False) -> Iterator[Tuple[str, str]]:
    """Yield ("content"|"reasoning", text). Reasoning is never spoken; callers decide what to do with it."""
    url = assert_loopback(base_url) + "/chat/completions"
    body = json.dumps({"model": model, "messages": messages, "max_tokens": max_tokens,
                       "temperature": temperature, "stream": True,
                       "chat_template_kwargs": {"enable_thinking": bool(thinking)}}).encode()
    request = urllib.request.Request(url, body, {"Content-Type": "application/json"})
    # Never use proxy settings for a loopback call.
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(request, timeout=timeout) as response:
        for raw in response:
            line = raw.decode("utf-8", "replace").strip()
            if not line.startswith("data:"):
                continue
            payload = line[5:].strip()
            if payload == "[DONE]":
                return
            try:
                delta = json.loads(payload)["choices"][0].get("delta", {})
            except (ValueError, KeyError, IndexError):
                continue
            for key, kind in (("content", "content"), ("reasoning_content", "reasoning"), ("reasoning", "reasoning")):
                if delta.get(key):
                    yield kind, delta[key]


def stream_chat(*args, **kwargs) -> Iterator[str]:
    """Spoken text only."""
    for kind, text in stream_events(*args, **kwargs):
        if kind == "content":
            yield text
