from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import requests

from trading_bot.blockchain import get_chain_profile

HYPERLIQUID_INFO_URL = "https://api.hyperliquid.xyz/info"


class WalletSyncError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class WalletSyncResult:
    status: str
    snapshot: dict[str, Any]


def _as_float(value: Any) -> float:
    try:
        return float(value or 0.0)
    except (TypeError, ValueError):
        return 0.0


def _hex_to_int(value: Any) -> int:
    if isinstance(value, str) and value.startswith("0x"):
        return int(value, 16)
    if value in (None, ""):
        return 0
    return int(value)


def describe_sync_capability(account: dict[str, Any]) -> dict[str, str]:
    wallet_key = str(account.get("wallet_key") or "")
    venue_key = str(account.get("venue_key") or "")
    chain_is_evm = bool(account.get("chain_is_evm"))
    if wallet_key == "METAMASK_EXTENSION" and chain_is_evm:
        return {
            "key": "browser_wallet",
            "label": "Browser wallet",
            "note": "Questo wallet puo essere sincronizzato direttamente dal browser tramite MetaMask.",
        }
    if venue_key == "HYPERLIQUID":
        return {
            "key": "venue_public",
            "label": "Venue public sync",
            "note": "Questo wallet puo essere letto via endpoint pubblici Hyperliquid per watch e shadow.",
        }
    return {
        "key": "manual_only",
        "label": "Manuale",
        "note": "Per questo wallet la alpha non ha ancora una sync automatica completa.",
    }


def build_metamask_snapshot(
    account: dict[str, Any],
    browser_snapshot: dict[str, Any],
) -> WalletSyncResult:
    chain = get_chain_profile(str(account.get("chain_key")))
    if not chain.is_evm or chain.chain_id is None:
        raise WalletSyncError("La snapshot browser di MetaMask e supportata solo su chain EVM.")

    address = str(account.get("address") or "").lower()
    snapshot_address = str(browser_snapshot.get("address") or "").lower()
    if snapshot_address and snapshot_address != address:
        raise WalletSyncError("La snapshot browser non corrisponde all'address registrato.")

    chain_id_hex = str(browser_snapshot.get("chain_id_hex") or "").lower()
    expected_chain_hex = hex(chain.chain_id).lower()
    if chain_id_hex and chain_id_hex != expected_chain_hex:
        raise WalletSyncError(
            f"MetaMask e collegato alla chain sbagliata. Attesa {chain.label}, ricevuta {chain_id_hex}."
        )

    balance_wei = _hex_to_int(browser_snapshot.get("balance_hex"))
    tx_count = _hex_to_int(browser_snapshot.get("tx_count_hex"))
    block_number = _hex_to_int(browser_snapshot.get("block_number_hex"))
    native_balance = balance_wei / (10**18)
    payload = {
        "snapshot_kind": "metamask_browser",
        "headline": f"{chain.label} via MetaMask",
        "summary": f"{native_balance:.4f} {chain.gas_token} | tx {tx_count} | block {block_number}",
        "address": account.get("address"),
        "chain_key": chain.key,
        "chain_label": chain.label,
        "currency": chain.gas_token,
        "native_balance": native_balance,
        "tx_count": tx_count,
        "block_number": block_number,
        "provider": browser_snapshot.get("provider") or "MetaMask",
    }
    return WalletSyncResult(status="SYNCED", snapshot=payload)


def _hyperliquid_post(payload: dict[str, Any]) -> dict[str, Any]:
    response = requests.post(HYPERLIQUID_INFO_URL, json=payload, timeout=15)
    response.raise_for_status()
    data = response.json()
    if not isinstance(data, dict):
        raise WalletSyncError("Risposta Hyperliquid non valida.")
    return data


def sync_hyperliquid_wallet(address: str) -> WalletSyncResult:
    perp_state = _hyperliquid_post({"type": "clearinghouseState", "user": address})
    spot_state = _hyperliquid_post({"type": "spotClearinghouseState", "user": address})

    cross_margin = perp_state.get("crossMarginSummary") or perp_state.get("marginSummary") or {}
    account_value = _as_float(cross_margin.get("accountValue"))
    withdrawable = _as_float(perp_state.get("withdrawable"))
    total_ntl_pos = _as_float(cross_margin.get("totalNtlPos"))
    asset_positions = perp_state.get("assetPositions") or []
    spot_balances = spot_state.get("balances") or []

    payload = {
        "snapshot_kind": "hyperliquid_info",
        "headline": "Hyperliquid account state",
        "summary": (
            f"Account value {account_value:.2f} USDC | "
            f"withdrawable {withdrawable:.2f} | perp {len(asset_positions)} | spot {len(spot_balances)}"
        ),
        "address": address,
        "chain_key": "HYPERLIQUID",
        "chain_label": "Hyperliquid",
        "currency": "USDC",
        "account_value": account_value,
        "withdrawable": withdrawable,
        "total_notional_position": total_ntl_pos,
        "perp_positions": len(asset_positions),
        "spot_balances_count": len(spot_balances),
        "spot_balances": spot_balances[:8],
        "timestamp_ms": perp_state.get("time"),
    }
    return WalletSyncResult(status="SYNCED", snapshot=payload)


def sync_registered_wallet(account: dict[str, Any]) -> WalletSyncResult:
    capability = describe_sync_capability(account)
    if capability["key"] == "venue_public" and str(account.get("venue_key")) == "HYPERLIQUID":
        return sync_hyperliquid_wallet(str(account.get("address") or ""))
    if capability["key"] == "browser_wallet":
        raise WalletSyncError(
            "Questo wallet richiede una snapshot browser MetaMask dal client, non una sync backend pura."
        )
    raise WalletSyncError(
        "Per questo wallet la alpha non ha ancora una sync automatica: per ora resta configurato in watch/manual mode."
    )
