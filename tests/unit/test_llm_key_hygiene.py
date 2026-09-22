"""API keys must be normalized, and provider errors must never carry them."""

import pytest

from core.llm.errors import sanitize_llm_error
from core.llm.openai import OpenAIProvider


def test_provider_strips_whitespace_from_key():
    """A trailing newline/space in Secrets Manager broke RCA with 'Connection error.'"""
    p = OpenAIProvider(api_key="sk-proj-EXAMPLEEXAMPLEEXAMPLE  \n")
    assert p._client.api_key == "sk-proj-EXAMPLEEXAMPLEEXAMPLE"


def test_provider_rejects_blank_key():
    with pytest.raises(ValueError):
        OpenAIProvider(api_key="   ")


def test_sanitize_removes_bearer_token():
    err = Exception("Illegal header value b'Bearer sk-proj-SECRETSECRETSECRETSECRET  '")
    out = sanitize_llm_error(err)
    assert "sk-proj-SECRETSECRETSECRETSECRET" not in out
    assert "REDACTED" in out


def test_sanitize_removes_bare_key_like_token():
    out = sanitize_llm_error(Exception("failed for key sk-ant-api03-ABCDEFGHIJKLMNOPQRSTUV"))
    assert "ABCDEFGHIJKLMNOPQRSTUV" not in out


def test_sanitize_keeps_useful_text():
    out = sanitize_llm_error(Exception("HTTP 429 rate limit exceeded"))
    assert "429" in out and "rate limit" in out
