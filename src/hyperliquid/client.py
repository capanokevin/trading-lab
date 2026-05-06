from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

import requests

DEFAULT_INFO_URL = "https://api.hyperliquid.xyz/info"


class HyperliquidApiError(RuntimeError):
    pass


class HyperliquidRateLimitError(HyperliquidApiError):
    def __init__(self, message: str, retry_after_seconds: float | None = None) -> None:
        super().__init__(message)
        self.retry_after_seconds = retry_after_seconds


@dataclass(slots=True)
class HyperliquidConfig:
    info_url: str = DEFAULT_INFO_URL
    timeout_seconds: float = 15.0

    @classmethod
    def from_env(cls) -> "HyperliquidConfig":
        return cls(
            info_url=os.getenv("HYPERLIQUID_INFO_URL", DEFAULT_INFO_URL),
            timeout_seconds=float(os.getenv("HYPERLIQUID_TIMEOUT_SECONDS", "15")),
        )


class HyperliquidClient:
    def __init__(
        self,
        config: HyperliquidConfig,
        session: requests.Session | None = None,
    ) -> None:
        self.config = config
        self.session = session or requests.Session()

    def has_auth_configured(self) -> bool:
        return False

    def supports_public_candles(self) -> bool:
        return True

    @staticmethod
    def normalize_symbol(symbol: str) -> str:
        raw = symbol.strip().upper().replace("/", "-")
        if "-" in raw:
            return raw.split("-", 1)[0]
        return raw

    def get_public_order_book(self, symbol: str) -> dict[str, Any]:
        coin = self.normalize_symbol(symbol)
        payload = self._post({"type": "l2Book", "coin": coin})
        levels = payload.get("levels") or [[], []]
        bids = levels[0] if len(levels) > 0 else []
        asks = levels[1] if len(levels) > 1 else []
        source_ts = self._iso_from_ms(payload.get("time"))
        return {
            "provider": "HYPERLIQUID",
            "symbol": f"{coin}-USD",
            "data": {
                "bids": [
                    {
                        "p": level["px"],
                        "q": level["sz"],
                        "n": level.get("n"),
                        "pdt": source_ts,
                    }
                    for level in bids
                ],
                "asks": [
                    {
                        "p": level["px"],
                        "q": level["sz"],
                        "n": level.get("n"),
                        "pdt": source_ts,
                    }
                    for level in asks
                ],
            },
        }

    def get_public_last_trades(self, symbol: str) -> dict[str, Any]:
        coin = self.normalize_symbol(symbol)
        trades = self._post({"type": "recentTrades", "coin": coin})
        if not isinstance(trades, list):
            raise HyperliquidApiError("Risposta recentTrades non valida.")
        return {
            "provider": "HYPERLIQUID",
            "symbol": f"{coin}-USD",
            "data": [
                {
                    "aid": coin,
                    "pc": "USD",
                    "tid": f"{coin}-{trade['tid']}",
                    "tdt": self._iso_from_ms(trade.get("time")),
                    "p": trade["px"],
                    "q": trade["sz"],
                    "side": trade.get("side"),
                    "hash": trade.get("hash"),
                }
                for trade in trades
            ],
        }

    def get_candles(
        self,
        symbol: str,
        interval: int = 5,
        since: int | None = None,
        until: int | None = None,
    ) -> dict[str, Any]:
        coin = self.normalize_symbol(symbol)
        interval_label = self._map_interval(interval)
        end_time = int(until if until is not None else datetime.now(tz=timezone.utc).timestamp() * 1000)
        if since is None:
            since = end_time - self._default_window_ms(interval_label)
        candles = self._post(
            {
                "type": "candleSnapshot",
                "req": {
                    "coin": coin,
                    "interval": interval_label,
                    "startTime": int(since),
                    "endTime": end_time,
                },
            }
        )
        if not isinstance(candles, list):
            raise HyperliquidApiError("Risposta candleSnapshot non valida.")
        return {
            "provider": "HYPERLIQUID",
            "symbol": f"{coin}-USD",
            "data": [
                {
                    "start": candle["t"],
                    "open": candle["o"],
                    "high": candle["h"],
                    "low": candle["l"],
                    "close": candle["c"],
                    "volume": candle["v"],
                    "trade_count": candle.get("n"),
                }
                for candle in candles
            ],
        }

    def _post(self, payload: dict[str, Any]) -> Any:
        response = self.session.post(
            self.config.info_url,
            json=payload,
            timeout=self.config.timeout_seconds,
            headers={"Accept": "application/json"},
        )
        if response.status_code == 429:
            retry_after = self._parse_retry_after_seconds(response.headers.get("Retry-After"))
            raise HyperliquidRateLimitError(
                "Hyperliquid rate limit raggiunto.",
                retry_after_seconds=retry_after,
            )
        try:
            response.raise_for_status()
        except requests.HTTPError as exc:
            text = response.text[:300] if response.text else "no response body"
            raise HyperliquidApiError(
                f"Hyperliquid error HTTP {response.status_code}: {text}"
            ) from exc
        try:
            return response.json()
        except ValueError as exc:
            raise HyperliquidApiError("Risposta Hyperliquid non valida.") from exc

    @staticmethod
    def _iso_from_ms(value: Any) -> str:
        try:
            timestamp = int(value) / 1000.0
        except (TypeError, ValueError):
            timestamp = datetime.now(tz=timezone.utc).timestamp()
        return datetime.fromtimestamp(timestamp, tz=timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")

    @staticmethod
    def _map_interval(interval: int) -> str:
        mapping = {
            1: "1m",
            3: "3m",
            5: "5m",
            15: "15m",
            30: "30m",
            60: "1h",
            240: "4h",
            1440: "1d",
        }
        return mapping.get(interval, f"{interval}m")

    @staticmethod
    def _default_window_ms(interval_label: str) -> int:
        interval_to_ms = {
            "1m": 60_000,
            "3m": 180_000,
            "5m": 300_000,
            "15m": 900_000,
            "30m": 1_800_000,
            "1h": 3_600_000,
            "4h": 14_400_000,
            "1d": 86_400_000,
        }
        candle_ms = interval_to_ms.get(interval_label, 300_000)
        return candle_ms * 120

    @staticmethod
    def _parse_retry_after_seconds(raw_value: str | None) -> float | None:
        if not raw_value:
            return None
        try:
            return float(raw_value)
        except ValueError:
            return None
