"""HTTP client for bot → API communication.

The bot and API run as separate processes/containers with separate memory.
All state-mutating operations (approve, deny, submit alert) must go through
the API's HTTP endpoints to ensure consistency.
"""

import os

import httpx

from core.logging import get_logger

logger = get_logger(__name__)

_DEFAULT_API_URL = "http://localhost:8000"


def _api_url() -> str:
    return os.getenv("API_BASE_URL", _DEFAULT_API_URL).rstrip("/")


async def submit_alert(source: str, fingerprint: str, severity: str, domain: str = "infrastructure") -> dict:
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.post(
            f"{_api_url()}/alerts",
            json={"source": source, "fingerprint": fingerprint, "severity": severity, "domain": domain},
        )
        resp.raise_for_status()
        return resp.json()


async def decide_approval(request_id: str, approved: bool, decided_by: str, reason: str | None = None) -> dict:
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.post(
            f"{_api_url()}/approvals/{request_id}/decide",
            json={"approved": approved, "decided_by": decided_by, "reason": reason},
        )
        resp.raise_for_status()
        return resp.json()


async def get_pending_approvals() -> list[dict]:
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.get(f"{_api_url()}/approvals/pending")
        resp.raise_for_status()
        return resp.json()


async def list_incidents() -> list[dict]:
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.get(f"{_api_url()}/incidents")
        resp.raise_for_status()
        return resp.json()


async def get_incident(incident_id: str) -> dict | None:
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.get(f"{_api_url()}/incidents/{incident_id}")
        if resp.status_code == 404:
            return None
        resp.raise_for_status()
        return resp.json()


async def list_pipeline_runs() -> list[dict]:
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.get(f"{_api_url()}/pipeline")
        resp.raise_for_status()
        return resp.json()


async def get_autonomy() -> dict:
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.get(f"{_api_url()}/autonomy")
        resp.raise_for_status()
        return resp.json()
