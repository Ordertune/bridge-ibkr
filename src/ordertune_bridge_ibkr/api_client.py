"""HTTP-Client für /api/bridge/v1/*.

Alle 5 Bridge-Endpoints:
  - POST   /handshake
  - PUT    /heartbeat
  - GET    /orders/pending
  - PUT    /orders/{dispatch_id}/ack
  - PUT    /orders/{dispatch_id}/result

Auth-Chain-Header:
  Authorization: Bearer <TOKEN>
  X-Bridge-Fingerprint: <hex>
  X-Bridge-Version: <version>
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Any

import httpx

from . import __version__

log = logging.getLogger(__name__)

DEFAULT_TIMEOUT = 15.0
MAX_RETRIES = 3
RETRY_BACKOFF_S = (0.5, 1.5, 3.0)  # Exponential-ish

# HTTP-Status-Codes die niemals retryable sind (4xx-Client-Fehler außer 429)
_NON_RETRYABLE = {400, 401, 403, 404, 409, 410, 422}


def _request_with_retry(
    method: str,
    client: httpx.Client,
    url: str,
    **kwargs: Any,
) -> httpx.Response:
    """HTTP-Request mit Retry auf 5xx + Network-Errors. 4xx = fail-fast."""
    last_exc: Exception | None = None
    for attempt in range(MAX_RETRIES):
        try:
            r = client.request(method, url, **kwargs)
            if r.status_code in _NON_RETRYABLE:
                r.raise_for_status()
                return r
            if r.status_code >= 500 or r.status_code == 429:
                log.warning(
                    "http %s %s -> %d (attempt %d/%d, retrying)",
                    method, url, r.status_code, attempt + 1, MAX_RETRIES,
                )
                if attempt < MAX_RETRIES - 1:
                    time.sleep(RETRY_BACKOFF_S[attempt])
                    continue
                r.raise_for_status()
            r.raise_for_status()
            return r
        except (httpx.ConnectError, httpx.ReadTimeout, httpx.RemoteProtocolError) as exc:
            last_exc = exc
            log.warning(
                "http %s %s network-error (attempt %d/%d): %s",
                method, url, attempt + 1, MAX_RETRIES, exc,
            )
            if attempt < MAX_RETRIES - 1:
                time.sleep(RETRY_BACKOFF_S[attempt])
                continue
            raise
    if last_exc:
        raise last_exc
    raise RuntimeError("unreachable")


@dataclass
class BridgePendingOrder:
    dispatch_id: str
    order_intent: dict[str, Any]
    expires_at: str | None
    cancel_requested: bool


@dataclass
class BridgePendingResponse:
    server_time: str
    pending: list[BridgePendingOrder]
    cancelling: list[str]  # dispatch_ids


class OrdertuneApiClient:
    def __init__(
        self,
        base_url: str,
        token: str,
        connection_id: str,
        fingerprint: str,
        timeout: float = DEFAULT_TIMEOUT,
    ) -> None:
        self._base = base_url.rstrip("/")
        self._connection_id = connection_id
        self._client = httpx.Client(
            timeout=timeout,
            headers={
                "Authorization": f"Bearer {token}",
                "X-Bridge-Fingerprint": fingerprint,
                "X-Bridge-Version": __version__,
                "User-Agent": f"ordertune-bridge-ibkr/{__version__}",
            },
        )

    def close(self) -> None:
        self._client.close()

    # ── Endpoints ──────────────────────────────────────────────────────────

    def handshake(self, capabilities: dict[str, Any]) -> dict[str, Any]:
        r = _request_with_retry(
            "POST", self._client,
            f"{self._base}/api/bridge/v1/handshake",
            json={
                "connection_id": self._connection_id,
                "capabilities": capabilities,
            },
        )
        return r.json()

    def heartbeat(self, snapshot: dict[str, Any]) -> None:
        _request_with_retry(
            "PUT", self._client,
            f"{self._base}/api/bridge/v1/heartbeat",
            json={"snapshot": snapshot},
        )

    def get_pending(self) -> BridgePendingResponse:
        r = _request_with_retry(
            "GET", self._client,
            f"{self._base}/api/bridge/v1/orders/pending",
        )
        data = r.json()
        return BridgePendingResponse(
            server_time=data.get("serverTime", ""),
            pending=[
                BridgePendingOrder(
                    dispatch_id=row["dispatchId"],
                    order_intent=row["orderIntent"],
                    expires_at=row.get("expiresAt"),
                    cancel_requested=row.get("cancelRequested", False),
                )
                for row in data.get("pending", [])
            ],
            cancelling=[c["dispatchId"] for c in data.get("cancelling", [])],
        )

    def ack_order(self, dispatch_id: str, ib_order_id: int, submitted_at: str) -> None:
        _request_with_retry(
            "PUT", self._client,
            f"{self._base}/api/bridge/v1/orders/{dispatch_id}/ack",
            json={"ib_order_id": ib_order_id, "submitted_at": submitted_at},
        )

    def result_order(
        self,
        dispatch_id: str,
        status: str,  # 'filled' | 'partial' | 'cancelled' | 'rejected'
        filled_qty: float | None = None,
        avg_fill_price: float | None = None,
        commission: float | None = None,
        filled_at: str | None = None,
        reason: str | None = None,
    ) -> None:
        body: dict[str, Any] = {"status": status}
        if filled_qty is not None:
            body["filled_qty"] = filled_qty
        if avg_fill_price is not None:
            body["avg_fill_price"] = avg_fill_price
        if commission is not None:
            body["commission"] = commission
        if filled_at is not None:
            body["filled_at"] = filled_at
        if reason is not None:
            body["reason"] = reason
        _request_with_retry(
            "PUT", self._client,
            f"{self._base}/api/bridge/v1/orders/{dispatch_id}/result",
            json=body,
        )
