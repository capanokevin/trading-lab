from __future__ import annotations

import base64
import json
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit
from uuid import uuid4

import requests
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

DEFAULT_PROD_BASE_URL = "https://revx.revolut.com/api/1.0"
DEFAULT_DEV_BASE_URL = "https://revx.revolut.codes/api/1.0"


class RevolutXApiError(RuntimeError):
    pass


class RevolutXRateLimitError(RevolutXApiError):
    def __init__(self, message: str, retry_after_seconds: float | None = None) -> None:
        super().__init__(message)
        self.retry_after_seconds = retry_after_seconds


@dataclass(slots=True)
class RevolutXConfig:
    base_url: str = DEFAULT_DEV_BASE_URL
    api_key: str | None = None
    private_key_path: Path | None = None
    timeout_seconds: float = 10.0

    @classmethod
    def from_env(cls) -> "RevolutXConfig":
        private_key_path = os.getenv("REVOLUT_X_PRIVATE_KEY_PATH")
        return cls(
            base_url=os.getenv("REVOLUT_X_BASE_URL", DEFAULT_DEV_BASE_URL),
            api_key=os.getenv("REVOLUT_X_API_KEY") or None,
            private_key_path=Path(private_key_path) if private_key_path else None,
            timeout_seconds=float(os.getenv("REVOLUT_X_TIMEOUT_SECONDS", "10")),
        )


class RevolutXClient:
    def __init__(
        self,
        config: RevolutXConfig,
        session: requests.Session | None = None,
    ) -> None:
        self.config = config
        self.session = session or requests.Session()
        self._private_key: Ed25519PrivateKey | None = None

    def has_auth_configured(self) -> bool:
        return bool(self.config.api_key and self.config.private_key_path)

    @staticmethod
    def normalize_symbol(symbol: str) -> str:
        return symbol.strip().upper().replace("/", "-")

    def get_public_order_book(self, symbol: str) -> dict[str, Any]:
        normalized_symbol = self.normalize_symbol(symbol)
        return self.request("GET", f"/public/order-book/{normalized_symbol}")

    def get_public_last_trades(self) -> dict[str, Any]:
        return self.request("GET", "/public/last-trades")

    def get_pairs(self) -> dict[str, Any]:
        return self.request("GET", "/configuration/pairs", auth_required=True)

    def get_candles(
        self,
        symbol: str,
        interval: int = 5,
        since: int | None = None,
        until: int | None = None,
    ) -> dict[str, Any]:
        normalized_symbol = self.normalize_symbol(symbol)
        params: dict[str, Any] = {"interval": interval}
        if since is not None:
            params["since"] = since
        if until is not None:
            params["until"] = until
        return self.request(
            "GET",
            f"/candles/{normalized_symbol}",
            params=params,
            auth_required=True,
        )

    def place_limit_order(
        self,
        *,
        symbol: str,
        side: str,
        price: str,
        base_size: str | None = None,
        quote_size: str | None = None,
        execution_instructions: list[str] | None = None,
        client_order_id: str | None = None,
    ) -> dict[str, Any]:
        self._validate_size(base_size=base_size, quote_size=quote_size)
        payload: dict[str, Any] = {
            "client_order_id": client_order_id or str(uuid4()),
            "symbol": self.normalize_symbol(symbol),
            "side": side.upper(),
            "order_configuration": {
                "limit": {
                    "price": price,
                    "execution_instructions": execution_instructions or ["allow_taker"],
                }
            },
        }
        if base_size is not None:
            payload["order_configuration"]["limit"]["base_size"] = base_size
        if quote_size is not None:
            payload["order_configuration"]["limit"]["quote_size"] = quote_size
        return self.request("POST", "/orders", json_body=payload, auth_required=True)

    def place_market_order(
        self,
        *,
        symbol: str,
        side: str,
        base_size: str | None = None,
        quote_size: str | None = None,
        client_order_id: str | None = None,
    ) -> dict[str, Any]:
        self._validate_size(base_size=base_size, quote_size=quote_size)
        payload: dict[str, Any] = {
            "client_order_id": client_order_id or str(uuid4()),
            "symbol": self.normalize_symbol(symbol),
            "side": side.upper(),
            "order_configuration": {"market": {}},
        }
        if base_size is not None:
            payload["order_configuration"]["market"]["base_size"] = base_size
        if quote_size is not None:
            payload["order_configuration"]["market"]["quote_size"] = quote_size
        return self.request("POST", "/orders", json_body=payload, auth_required=True)

    def cancel_all_orders(self) -> dict[str, Any]:
        return self.request("DELETE", "/orders", auth_required=True)

    def request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json_body: dict[str, Any] | None = None,
        auth_required: bool = False,
    ) -> dict[str, Any]:
        method = method.upper()
        attempt = 0
        while True:
            body_text = self._serialize_body(json_body)
            url = f"{self.config.base_url.rstrip('/')}{path}"
            headers = {"Accept": "application/json"}
            if body_text:
                headers["Content-Type"] = "application/json"

            prepared = self.session.prepare_request(
                requests.Request(
                    method=method,
                    url=url,
                    params=params,
                    data=body_text if body_text else None,
                    headers=headers,
                )
            )

            if auth_required:
                prepared.headers.update(self._build_auth_headers(method, prepared.url, body_text))

            response = self.session.send(prepared, timeout=self.config.timeout_seconds)
            try:
                return self._handle_response(response)
            except RevolutXRateLimitError as exc:
                attempt += 1
                if attempt >= 2:
                    raise
                sleep_for = min(max(exc.retry_after_seconds or 0.5, 0.5), 5.0)
                time.sleep(sleep_for)

    def _build_auth_headers(self, method: str, url: str, body_text: str) -> dict[str, str]:
        if not self.config.api_key:
            raise RevolutXApiError("REVOLUT_X_API_KEY is missing.")
        if not self.config.private_key_path:
            raise RevolutXApiError("REVOLUT_X_PRIVATE_KEY_PATH is missing.")

        timestamp = str(int(time.time() * 1000))
        parsed = urlsplit(url)
        message = f"{timestamp}{method.upper()}{parsed.path}{parsed.query}{body_text}"
        signature = self._sign_message(message)

        return {
            "X-Revx-API-Key": self.config.api_key,
            "X-Revx-Timestamp": timestamp,
            "X-Revx-Signature": signature,
        }

    def _sign_message(self, message: str) -> str:
        private_key = self._load_private_key()
        signature = private_key.sign(message.encode("utf-8"))
        return base64.b64encode(signature).decode("ascii")

    def _load_private_key(self) -> Ed25519PrivateKey:
        if self._private_key is not None:
            return self._private_key

        if not self.config.private_key_path:
            raise RevolutXApiError("Private key path is not configured.")

        pem_data = self.config.private_key_path.read_bytes()
        private_key = serialization.load_pem_private_key(pem_data, password=None)
        if not isinstance(private_key, Ed25519PrivateKey):
            raise RevolutXApiError("The loaded private key is not an Ed25519 key.")

        self._private_key = private_key
        return private_key

    @staticmethod
    def _serialize_body(json_body: dict[str, Any] | None) -> str:
        if not json_body:
            return ""
        return json.dumps(json_body, separators=(",", ":"), ensure_ascii=True)

    @staticmethod
    def _validate_size(*, base_size: str | None, quote_size: str | None) -> None:
        if (base_size is None) == (quote_size is None):
            raise ValueError("Provide exactly one of base_size or quote_size.")

    @staticmethod
    def _handle_response(response: requests.Response) -> dict[str, Any]:
        try:
            payload = response.json()
        except ValueError:
            payload = None

        if response.ok and payload is not None:
            return payload

        retry_after = response.headers.get("Retry-After")
        retry_after_seconds = RevolutXClient._parse_retry_after_seconds(retry_after)
        if payload is not None:
            details = json.dumps(payload, ensure_ascii=True)
        else:
            details = response.text[:300] if response.text else "no response body"
        if retry_after:
            details = f"{details} | Retry-After={retry_after}"

        message = f"Revolut X error HTTP {response.status_code}: {details}"

        if response.status_code == 429:
            raise RevolutXRateLimitError(
                message,
                retry_after_seconds=retry_after_seconds,
            )

        raise RevolutXApiError(message)

    @staticmethod
    def _parse_retry_after_seconds(raw_value: str | None) -> float | None:
        if not raw_value:
            return None

        candidate = raw_value.strip().lower()
        try:
            if candidate.endswith("ms"):
                return max(float(candidate[:-2].strip()) / 1000.0, 0.0)
            if candidate.endswith("s"):
                return max(float(candidate[:-1].strip()), 0.0)

            numeric = float(candidate)
            if numeric > 10:
                return max(numeric / 1000.0, 0.0)
            return max(numeric, 0.0)
        except ValueError:
            return None
