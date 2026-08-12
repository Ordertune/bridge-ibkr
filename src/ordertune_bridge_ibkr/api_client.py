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

WIRE-FORMAT (T1-78)
-------------------
Jeder Request-Body ist camelCase. Das ist der Vertrag mit der Plattform und
gilt auch hier, wo die Sprache snake_case nahelegt — Feldnamen gehören zum
Protokoll, nicht zum Stil der jeweiligen Seite.

Das ist nicht Kosmetik. v0.1.0 schickte `filled_qty`/`avg_fill_price`, die
Plattform erwartete `fillQty`/`fillPrice`, und weil dort jedes Feld optional
war, hat der Server mit 200 geantwortet und Menge wie Preis als NULL
geschrieben. Kein Fehler, keine Warnung, monatelang. Die Serverschemata sind
seit T1-78 `.strict()`; dieselbe Abweichung ist jetzt ein lautes 422.

Deshalb liegt die Übersetzung aus Broker-Objekten in das Drahtformat
ausschliesslich hier an der Grenze (`_wire_position`, `heartbeat`,
`result_order`). `main.py` reicht natürliche Python-Objekte herein. Der
Vertragstest prüft genau diese Grenze gegen die Fixtures unter
tests/contract/.
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

# Antwortkörper, den wir bei einem harten Fehler ins Log heben. Die Plattform
# antwortet mit {code, message}; ohne das sieht der Nutzer nur "422
# Unprocessable Entity" und hat keine Chance, den Grund zu erkennen.
_ERROR_BODY_MAX_CHARS = 400


def _log_error_body(method: str, url: str, r: httpx.Response) -> None:
    """Hebt den Fehlerkörper der Plattform ins Log, bevor wir werfen."""
    try:
        body = r.text[:_ERROR_BODY_MAX_CHARS]
    except Exception:  # pragma: no cover - defensiv
        body = "<nicht lesbar>"
    log.error("http %s %s -> %d: %s", method, url, r.status_code, body)
    if r.status_code == 422:
        log.error(
            "422 bedeutet: dieser Bridge-Build und die Plattform sind sich "
            "über das Nachrichtenformat nicht einig. Das behebt kein Neustart. "
            "Aktualisiere die Bridge auf die neueste Version: "
            "https://github.com/Ordertune/bridge-ibkr/releases/latest"
        )


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
                _log_error_body(method, url, r)
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
                _log_error_body(method, url, r)
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


# ── Broker → Drahtformat ────────────────────────────────────────────────────

# Die Plattform erwartet ein enges Vokabular für den Gateway-Zustand. Der
# IBKR-Client kennt nur verbunden/getrennt.
_GATEWAY_STATUS_WIRE = {
    "connected": "ok",
    "disconnected": "down",
    "reconnecting": "reconnecting",
}


def _wire_timestamp(value: str | None) -> str | None:
    """Zeitstempel in die kanonische Z-Form bringen.

    `datetime.now(timezone.utc).isoformat()` liefert in Python
    "2026-08-12T13:31:04.512000+00:00". Die Plattform validiert gegen die
    Z-Form und weist den Offset ab — jeder Ack und jedes Fill-Ergebnis wäre
    mit 422 abgelehnt worden. Gefunden hat das erst der Vertragstest, weil
    beide Seiten für sich genommen völlig plausibel aussahen.
    """
    if value is None:
        return None
    return value.replace("+00:00", "Z")


def _opt_float(value: Any) -> float | None:
    """None bleibt None — 0.0 wäre eine Behauptung, die wir nicht belegen können."""
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _wire_position(p: dict[str, Any]) -> dict[str, Any]:
    """IBKR-Portfoliozeile → positionSchema der Plattform.

    Bewusst explizit statt einer Schleife über die Schlüssel: das Serverschema
    ist strict, jedes zusätzliche Feld wäre ein 422. `market_price` gehört
    absichtlich nicht dazu — die Plattform rechnet ihren Marktwert selbst.
    """
    return {
        "symbol": p["symbol"],
        "qty": float(p.get("qty") or 0.0),
        "avgEntryPriceUsd": _opt_float(p.get("avg_cost")),
        "marketValueUsd": _opt_float(p.get("market_value")),
        "unrealizedPlUsd": _opt_float(p.get("unrealized_pnl")),
    }


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

    def handshake(self, capabilities: dict[str, Any] | None = None) -> dict[str, Any]:
        """POST /handshake → {bridgeVersion, capabilities?}

        `connection_id` wird NICHT mitgeschickt: der Token löst die Verbindung
        serverseitig auf, ein zweiter Bezeichner im Körper wäre eine Quelle für
        Widersprüche. v0.1.0 schickte ihn und liess `bridgeVersion` weg — genau
        deshalb ist noch nie eine Bridge über den Handshake gekommen.
        """
        body: dict[str, Any] = {"bridgeVersion": __version__}
        if capabilities is not None:
            body["capabilities"] = capabilities
        r = _request_with_retry(
            "POST", self._client,
            f"{self._base}/api/bridge/v1/handshake",
            json=body,
        )
        return r.json()

    def heartbeat(
        self,
        cash_usd: float,
        equity_usd: float,
        positions: list[dict[str, Any]],
        gateway_status: str,
        capabilities: dict[str, Any] | None = None,
        cpu_load: float | None = None,
    ) -> None:
        """PUT /heartbeat → {bridgeVersion, gatewayStatus, accountSnapshot{...}}

        `cpuLoad` ist optional und wird standardmässig NICHT gesendet. Es ist
        Telemetrie von Hardware, die uns nicht gehört, und niemand auf der
        Plattform liest sie.
        """
        snapshot: dict[str, Any] = {
            "cashUsd": float(cash_usd),
            "equityUsd": float(equity_usd),
            "positions": [_wire_position(p) for p in positions],
        }
        if capabilities is not None:
            snapshot["capabilities"] = capabilities

        body: dict[str, Any] = {
            "bridgeVersion": __version__,
            "gatewayStatus": _GATEWAY_STATUS_WIRE.get(gateway_status, gateway_status),
            "accountSnapshot": snapshot,
        }
        if cpu_load is not None:
            body["cpuLoad"] = float(cpu_load)

        _request_with_retry(
            "PUT", self._client,
            f"{self._base}/api/bridge/v1/heartbeat",
            json=body,
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

    def ack_order(
        self,
        dispatch_id: str,
        broker_order_id: int | str | None = None,
        submitted_at: str | None = None,
        picked_at: str | None = None,
    ) -> None:
        """PUT /orders/{id}/ack → {brokerOrderId?, submittedAtClient?, pickedAtClient?}

        Die Broker-Order-Nummer wird bereits hier übergeben, nicht erst mit dem
        Ergebnis. Bricht die Bridge zwischen Platzierung und Ergebnis ab, bleibt
        die Order sonst nicht zuordenbar.
        """
        body: dict[str, Any] = {}
        if broker_order_id is not None:
            body["brokerOrderId"] = str(broker_order_id)
        if submitted_at is not None:
            body["submittedAtClient"] = _wire_timestamp(submitted_at)
        if picked_at is not None:
            body["pickedAtClient"] = _wire_timestamp(picked_at)
        _request_with_retry(
            "PUT", self._client,
            f"{self._base}/api/bridge/v1/orders/{dispatch_id}/ack",
            json=body,
        )

    def result_order(
        self,
        dispatch_id: str,
        status: str,
        fill_qty: float | None = None,
        fill_price: float | None = None,
        commission_usd: float | None = None,
        filled_at: str | None = None,
        reason_code: str | None = None,
        error_message: str | None = None,
        broker_order_id: int | str | None = None,
    ) -> None:
        """PUT /orders/{id}/result → Ausführungsergebnis.

        status: submitting | working | filled | partial | cancelled | rejected | expired
        reason_code: warum NICHT ausgeführt wurde — limit_not_reached, expired,
            cancelled_by_user, insufficient_funds, rejected_by_broker,
            no_market_data, sizing_drift, position_not_held, other.

        `fill_qty` ist das Feld, aus dem die Plattform den Bestand je Strategie
        führt. Ohne diese Zahl weiss niemand, wie viele Stücke einer Strategie
        gehören, und ein späterer Exit verkauft die falsche Menge.
        """
        body: dict[str, Any] = {"status": status}
        if broker_order_id is not None:
            body["brokerOrderId"] = str(broker_order_id)
        if fill_qty is not None:
            body["fillQty"] = float(fill_qty)
        if fill_price is not None:
            body["fillPrice"] = float(fill_price)
        if commission_usd is not None:
            body["commissionUsd"] = float(commission_usd)
        if filled_at is not None:
            body["filledAtClient"] = _wire_timestamp(filled_at)
        if reason_code is not None:
            body["reasonCode"] = reason_code
        if error_message is not None:
            body["errorMessage"] = error_message[:500]
        _request_with_retry(
            "PUT", self._client,
            f"{self._base}/api/bridge/v1/orders/{dispatch_id}/result",
            json=body,
        )
