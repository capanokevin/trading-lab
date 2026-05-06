from __future__ import annotations

import csv
import hashlib
import json
from io import StringIO

from flask import Flask, Response, jsonify, render_template_string, request

from trading_bot.blockchain import (
    CHAIN_PROFILES,
    VENUE_PROFILES,
    WALLET_PROFILES,
)
from trading_bot.config import AppConfig
from trading_bot.onchain_sync import WalletSyncError, build_metamask_snapshot, sync_registered_wallet
from trading_bot.providers import PROVIDER_PROFILES, get_provider_profile, provider_state_items
from trading_bot.storage import TradingStorage, local_day_key


def _normalize_import_row(raw: dict[str, object]) -> dict[str, object]:
    event_time = str(
        raw.get("timestamp")
        or raw.get("event_time")
        or raw.get("time")
        or ""
    ).strip()
    event_type = str(raw.get("event_type") or raw.get("type") or "").strip().lower()
    if not event_time:
        raise ValueError("Ogni riga importata deve avere un timestamp.")
    if event_type not in {"trade", "deposit", "withdrawal", "fee"}:
        raise ValueError(
            "event_type deve essere uno tra trade, deposit, withdrawal, fee."
        )

    def number_from(value: object) -> float | None:
        if value in (None, ""):
            return None
        return float(str(value).strip().replace(",", "."))

    return {
        "event_time": event_time,
        "event_type": event_type,
        "symbol": str(raw.get("symbol") or "").strip().upper() or None,
        "side": str(raw.get("side") or "").strip().upper() or None,
        "quantity": number_from(raw.get("quantity")),
        "price": number_from(raw.get("price")),
        "notional": number_from(raw.get("notional")),
        "fee": number_from(raw.get("fee")),
        "currency": str(raw.get("currency") or "").strip().upper() or None,
        "notes": str(raw.get("notes") or "").strip() or None,
    }


def _parse_manual_import(format_name: str, raw_text: str) -> list[dict[str, object]]:
    payload = raw_text.strip()
    if not payload:
        raise ValueError("Incolla prima un payload CSV o JSON.")

    if format_name == "json":
        rows = json.loads(payload)
        if not isinstance(rows, list):
            raise ValueError("Il JSON deve essere una lista di oggetti.")
        return [_normalize_import_row(item) for item in rows]

    if format_name == "csv":
        reader = csv.DictReader(StringIO(payload))
        rows = list(reader)
        if not rows:
            raise ValueError("Il CSV e vuoto o non contiene righe valide.")
        return [_normalize_import_row(item) for item in rows]

    raise ValueError("Formato import non supportato.")


def _account_key(label: str, provider_key: str) -> str:
    seed = f"{provider_key.strip().upper()}::{label.strip().lower()}"
    digest = hashlib.sha256(seed.encode("utf-8")).hexdigest()[:12]
    slug = "".join(ch for ch in label.lower() if ch.isalnum())[:18] or "account"
    return f"{provider_key.strip().upper()}_{slug}_{digest}"


def _wallet_account_key(label: str, wallet_key: str, address: str) -> str:
    seed = f"{wallet_key.strip().upper()}::{label.strip().lower()}::{address.strip().lower()}"
    digest = hashlib.sha256(seed.encode("utf-8")).hexdigest()[:12]
    slug = "".join(ch for ch in label.lower() if ch.isalnum())[:18] or "wallet"
    return f"{wallet_key.strip().upper()}_{slug}_{digest}"


def _normalize_wallet_address(value: str) -> str:
    address = value.strip()
    if not address:
        raise ValueError("Inserisci un address wallet.")
    if address.startswith("0x"):
        if len(address) != 42:
            raise ValueError("Un address EVM deve avere 42 caratteri.")
        return address.lower()
    if len(address) < 8:
        raise ValueError("Address wallet troppo corto.")
    return address


PAGE_TEMPLATE = """
<!doctype html>
<html lang="it">
  <head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>Autopilota Paper Trading</title>
    <style>
      :root {
        --bg: #f5efe6;
        --bg-deep: #201713;
        --paper: rgba(255, 250, 243, 0.88);
        --paper-strong: rgba(255, 252, 248, 0.94);
        --ink: #241712;
        --muted: #6a584f;
        --line: rgba(74, 54, 43, 0.14);
        --line-strong: rgba(74, 54, 43, 0.22);
        --accent: #cf6d2a;
        --accent-soft: rgba(207, 109, 42, 0.14);
        --good: #12704d;
        --good-soft: rgba(18, 112, 77, 0.12);
        --bad: #b3473b;
        --bad-soft: rgba(179, 71, 59, 0.12);
        --watch: #8f6a1e;
        --watch-soft: rgba(143, 106, 30, 0.14);
        --shadow: 0 24px 80px rgba(39, 23, 13, 0.1);
      }
      * {
        box-sizing: border-box;
      }
      body {
        margin: 0;
        color: var(--ink);
        font-family: "Avenir Next", "Helvetica Neue", sans-serif;
        background:
          radial-gradient(circle at 0% 0%, rgba(207, 109, 42, 0.22), transparent 24%),
          radial-gradient(circle at 100% 0%, rgba(18, 112, 77, 0.16), transparent 20%),
          linear-gradient(180deg, #faf4ec 0%, #f4ede2 48%, #f0e7db 100%);
      }
      .shell {
        max-width: 1560px;
        margin: 0 auto;
        padding: 16px 16px 32px;
      }
      .hero {
        display: grid;
        grid-template-columns: 1.5fr 0.9fr;
        gap: 14px;
        margin-bottom: 14px;
      }
      .tabbar {
        position: sticky;
        top: 12px;
        z-index: 20;
        display: flex;
        gap: 8px;
        padding: 8px;
        margin-bottom: 14px;
        border-radius: 999px;
        border: 1px solid var(--line);
        background: rgba(255, 250, 243, 0.82);
        backdrop-filter: blur(16px);
        box-shadow: 0 18px 36px rgba(39, 23, 13, 0.08);
      }
      .tab-btn {
        border: 1px solid transparent;
        border-radius: 999px;
        padding: 9px 14px;
        background: transparent;
        color: var(--muted);
        cursor: pointer;
        transition: 140ms ease;
      }
      .tab-btn.active {
        color: white;
        background: linear-gradient(135deg, #c86124, #df8a42);
        box-shadow: 0 14px 28px rgba(201, 97, 36, 0.24);
      }
      .tab-pane {
        display: none;
        margin-bottom: 14px;
      }
      .tab-pane.active {
        display: block;
      }
      .pane-grid {
        display: grid;
        grid-template-columns: 1.45fr 0.95fr;
        gap: 14px;
        align-items: start;
      }
      .single-column {
        display: grid;
        gap: 14px;
      }
      .watch-grid,
      .alert-grid {
        display: grid;
        gap: 10px;
      }
      .alert-grid {
        grid-template-columns: repeat(var(--cols, 3), minmax(0, 1fr));
      }
      .watch-grid {
        grid-template-columns: repeat(var(--cols, 3), minmax(0, 1fr));
      }
      .watch-card,
      .alert-card {
        padding: 13px;
        border-radius: 16px;
        border: 1px solid var(--line);
        background: rgba(255, 255, 255, 0.56);
      }
      .watch-card .price {
        margin-top: 8px;
        font-size: 22px;
        font-weight: 700;
        line-height: 1;
      }
      .watch-card .sub {
        margin-top: 5px;
        font-size: 11px;
        color: var(--muted);
      }
      .market-selector {
        display: flex;
        gap: 8px;
        flex-wrap: wrap;
        margin-bottom: 12px;
      }
      .market-tab {
        border: 1px solid var(--line);
        border-radius: 999px;
        padding: 8px 12px;
        background: rgba(255, 255, 255, 0.62);
        color: var(--muted);
        cursor: pointer;
        font-size: 12px;
      }
      .market-tab.active {
        color: white;
        border-color: transparent;
        background: linear-gradient(135deg, #c86124, #df8a42);
        box-shadow: 0 12px 24px rgba(201, 97, 36, 0.22);
      }
      #market-brief-grid {
        grid-template-columns: repeat(var(--cols, 4), minmax(0, 1fr));
        margin-bottom: 12px;
      }
      .alert-card.ok {
        border-color: rgba(18, 112, 77, 0.18);
        background: linear-gradient(180deg, rgba(18, 112, 77, 0.08), rgba(255, 255, 255, 0.6));
      }
      .alert-card.bad {
        border-color: rgba(179, 71, 59, 0.22);
        background: linear-gradient(180deg, rgba(179, 71, 59, 0.08), rgba(255, 255, 255, 0.6));
      }
      .alert-card.watch {
        border-color: rgba(143, 106, 30, 0.2);
        background: linear-gradient(180deg, rgba(143, 106, 30, 0.08), rgba(255, 255, 255, 0.6));
      }
      .alert-card strong {
        display: block;
        margin-bottom: 8px;
      }
      .alert-card .foot {
        margin-top: 10px;
        font-size: 12px;
        color: var(--muted);
      }
      .layout {
        display: grid;
        grid-template-columns: 1.45fr 0.95fr;
        gap: 18px;
        align-items: start;
      }
      .stack {
        display: grid;
        gap: 14px;
      }
      .panel {
        position: relative;
        overflow: hidden;
        background: var(--paper);
        border: 1px solid var(--line);
        border-radius: 22px;
        padding: 18px;
        box-shadow: var(--shadow);
        backdrop-filter: blur(14px);
      }
      .panel.strong {
        background:
          linear-gradient(135deg, rgba(255, 252, 247, 0.98), rgba(255, 247, 235, 0.92)),
          radial-gradient(circle at top right, rgba(207, 109, 42, 0.12), transparent 26%);
      }
      .panel::after {
        content: "";
        position: absolute;
        inset: auto -80px -120px auto;
        width: 220px;
        height: 220px;
        border-radius: 999px;
        background: radial-gradient(circle, rgba(207, 109, 42, 0.08), transparent 70%);
        pointer-events: none;
      }
      h1, h2, h3 {
        margin: 0;
        font-family: "Baskerville", "Iowan Old Style", "Palatino Linotype", serif;
        font-weight: 600;
        letter-spacing: -0.02em;
      }
      h1 {
        font-size: 30px;
        line-height: 1.02;
        margin-bottom: 6px;
        max-width: 760px;
      }
      h2 {
        font-size: 20px;
        margin-bottom: 10px;
      }
      h3 {
        font-size: 18px;
      }
      p {
        margin: 0;
        color: var(--muted);
        line-height: 1.5;
      }
      .eyebrow {
        display: inline-flex;
        align-items: center;
        gap: 8px;
        padding: 6px 10px;
        border-radius: 999px;
        background: rgba(255, 255, 255, 0.62);
        border: 1px solid var(--line);
        font-size: 12px;
        text-transform: uppercase;
        letter-spacing: 0.09em;
        color: var(--muted);
        margin-bottom: 10px;
      }
      .title-row,
      .label-row,
      .metric-head,
      .subhead,
      .table-head,
      .progress-head,
      .provider-row {
        display: flex;
        align-items: center;
        gap: 8px;
        justify-content: space-between;
      }
      .title-group,
      .label-group {
        display: inline-flex;
        align-items: center;
        gap: 8px;
      }
      .hero-copy {
        max-width: 700px;
        font-size: 13px;
      }
      .chips,
      .meta-badges,
      .decision-meta {
        display: flex;
        flex-wrap: wrap;
        gap: 8px;
      }
      .chips {
        margin-top: 10px;
      }
      .chip,
      .badge {
        display: inline-flex;
        align-items: center;
        gap: 6px;
        padding: 6px 10px;
        border-radius: 999px;
        border: 1px solid var(--line);
        background: rgba(255, 255, 255, 0.58);
        color: var(--muted);
        font-size: 11px;
      }
      .kpis {
        display: grid;
        grid-template-columns: repeat(var(--cols, 4), minmax(0, 1fr));
        gap: 10px;
        margin-top: 12px;
      }
      .kpi {
        padding: 13px;
        border-radius: 18px;
        border: 1px solid var(--line);
        background: rgba(255, 255, 255, 0.46);
      }
      .kpi .value {
        margin-top: 6px;
        font-size: 18px;
        font-weight: 700;
        line-height: 1;
      }
      .kpi .sub {
        margin-top: 4px;
        font-size: 11px;
        color: var(--muted);
      }
      .provider-box {
        display: grid;
        gap: 10px;
      }
      .provider-actions {
        display: grid;
        grid-template-columns: minmax(0, 1fr) auto;
        gap: 10px;
        align-items: center;
      }
      .provider-actions .provider-status {
        grid-column: 1 / -1;
      }
      .provider-current {
        padding: 13px;
        border-radius: 16px;
        border: 1px solid var(--line);
        background: rgba(255, 255, 255, 0.5);
      }
      .provider-grid,
      .rules-grid,
      .system-grid,
      .metric-grid,
      .detail-grid,
      .summary-grid {
        display: grid;
        gap: 10px;
      }
      .provider-grid,
      .rules-grid,
      .system-grid,
      .summary-grid {
        grid-template-columns: repeat(var(--cols, 2), minmax(0, 1fr));
      }
      .metric-grid,
      .detail-grid {
        grid-template-columns: repeat(var(--cols, 4), minmax(0, 1fr));
      }
      .card {
        padding: 12px;
        border-radius: 16px;
        border: 1px solid var(--line);
        background: rgba(255, 255, 255, 0.52);
      }
      .card strong,
      .system-card strong {
        display: block;
        margin-bottom: 6px;
      }
      .system-card {
        padding: 12px;
        border-radius: 16px;
        border: 1px solid var(--line);
        background: rgba(255, 255, 255, 0.48);
      }
      .step {
        margin-bottom: 6px;
        color: var(--muted);
        font-size: 12px;
        text-transform: uppercase;
        letter-spacing: 0.08em;
      }
      .provider-form {
        display: grid;
        gap: 10px;
      }
      input,
      textarea,
      select,
      button {
        font: inherit;
      }
      input,
      textarea,
      select {
        width: 100%;
        padding: 10px 12px;
        border-radius: 12px;
        border: 1px solid var(--line-strong);
        background: rgba(255, 255, 255, 0.8);
        color: var(--ink);
      }
      textarea {
        min-height: 150px;
        resize: vertical;
      }
      .form-grid {
        display: grid;
        grid-template-columns: repeat(2, minmax(0, 1fr));
        gap: 12px;
      }
      .button-row {
        display: flex;
        gap: 8px;
        align-items: center;
        flex-wrap: wrap;
      }
      .primary {
        border: 0;
        border-radius: 999px;
        padding: 10px 14px;
        background: linear-gradient(135deg, #c86124, #df8a42);
        color: white;
        cursor: pointer;
        box-shadow: 0 14px 32px rgba(201, 97, 36, 0.24);
      }
      .primary:disabled {
        cursor: wait;
        opacity: 0.72;
      }
      .secondary {
        border: 1px solid var(--line-strong);
        border-radius: 999px;
        padding: 10px 14px;
        background: rgba(255, 255, 255, 0.72);
        color: var(--ink);
        cursor: pointer;
      }
      .provider-status {
        min-height: 20px;
        font-size: 13px;
      }
      .mini-list {
        display: grid;
        gap: 10px;
      }
      .mini-row {
        padding: 12px 14px;
        border-radius: 16px;
        border: 1px solid var(--line);
        background: rgba(255, 255, 255, 0.42);
      }
      .mini-row p {
        margin: 6px 0 0;
      }
      .compact-list {
        margin: 8px 0 0;
        padding-left: 18px;
        color: var(--muted);
      }
      .compact-list li + li {
        margin-top: 6px;
      }
      .decision-board {
        display: grid;
        gap: 12px;
      }
      .decision-card {
        border: 1px solid var(--line);
        border-radius: 20px;
        padding: 14px;
        background: rgba(255, 255, 255, 0.53);
      }
      .decision-head {
        display: flex;
        justify-content: space-between;
        gap: 12px;
        align-items: flex-start;
        margin-bottom: 12px;
      }
      .timestamp {
        color: var(--muted);
        font-size: 12px;
      }
      .status {
        display: inline-flex;
        align-items: center;
        gap: 6px;
        padding: 7px 11px;
        border-radius: 999px;
        font-size: 12px;
        border: 1px solid transparent;
      }
      .status.ok {
        color: var(--good);
        background: var(--good-soft);
        border-color: rgba(18, 112, 77, 0.18);
      }
      .status.bad {
        color: var(--bad);
        background: var(--bad-soft);
        border-color: rgba(179, 71, 59, 0.18);
      }
      .status.watch {
        color: var(--watch);
        background: var(--watch-soft);
        border-color: rgba(143, 106, 30, 0.18);
      }
      .callout {
        padding: 12px;
        border-radius: 16px;
        border: 1px solid var(--line);
        background: rgba(255, 255, 255, 0.58);
        margin-bottom: 10px;
      }
      .callout strong {
        display: block;
        margin-bottom: 6px;
      }
      .overview-toolbar,
      .overview-toolbar-actions,
      .overview-jumpbar,
      .overview-panel-actions {
        display: flex;
        align-items: center;
        gap: 8px;
        flex-wrap: wrap;
      }
      .overview-toolbar {
        justify-content: space-between;
        margin-bottom: 10px;
      }
      .overview-jumpbar {
        gap: 6px;
      }
      .overview-nav {
        border: 1px solid var(--line);
        border-radius: 999px;
        padding: 7px 11px;
        background: rgba(255, 255, 255, 0.62);
        color: var(--muted);
        cursor: pointer;
        font-size: 12px;
      }
      .overview-nav:hover {
        border-color: rgba(36, 23, 18, 0.22);
        color: var(--ink);
      }
      .panel.has-collapsible .section-body {
        margin-top: 10px;
      }
      .panel.has-collapsible.is-collapsed .section-body {
        display: none;
      }
      .panel.has-collapsible.is-collapsed {
        padding-bottom: 16px;
      }
      .overview-focus-card .value {
        margin-top: 6px;
        font-size: 17px;
        font-weight: 700;
      }
      .overview-focus-card .sub {
        margin-top: 4px;
        font-size: 11px;
        color: var(--muted);
      }
      .journal-toolbar,
      .journal-toolbar-actions,
      .journal-jumpbar,
      .journal-panel-actions {
        display: flex;
        align-items: center;
        gap: 8px;
        flex-wrap: wrap;
      }
      .journal-toolbar {
        justify-content: space-between;
        margin-bottom: 10px;
      }
      .journal-jumpbar {
        gap: 6px;
      }
      .compact-btn {
        padding: 7px 11px;
        font-size: 12px;
      }
      .journal-nav {
        border: 1px solid var(--line);
        border-radius: 999px;
        padding: 7px 11px;
        background: rgba(255, 255, 255, 0.62);
        color: var(--muted);
        cursor: pointer;
        font-size: 12px;
      }
      .journal-nav:hover,
      .compact-btn:hover {
        border-color: rgba(36, 23, 18, 0.22);
        color: var(--ink);
      }
      .section-count {
        padding: 5px 9px;
        border-radius: 999px;
        border: 1px solid var(--line);
        background: rgba(255, 255, 255, 0.5);
        font-size: 11px;
        color: var(--muted);
      }
      .journal-focus-card .value {
        margin-top: 6px;
        font-size: 16px;
        font-weight: 700;
      }
      .journal-focus-card .sub {
        margin-top: 4px;
        font-size: 11px;
        color: var(--muted);
      }
      .metric {
        padding: 12px;
        border-radius: 16px;
        border: 1px solid var(--line);
        background: rgba(255, 255, 255, 0.52);
      }
      .metric .value {
        margin-top: 6px;
        font-size: 18px;
        font-weight: 700;
      }
      .metric .sub {
        margin-top: 4px;
        font-size: 11px;
        color: var(--muted);
      }
      .progress-stack {
        display: grid;
        gap: 10px;
        margin-bottom: 12px;
      }
      .progress {
        padding: 10px;
        border-radius: 14px;
        border: 1px solid var(--line);
        background: rgba(255, 255, 255, 0.54);
      }
      .progress-title {
        display: inline-flex;
        align-items: center;
        gap: 8px;
      }
      .track {
        width: 100%;
        height: 9px;
        margin-top: 6px;
        border-radius: 999px;
        background: rgba(36, 23, 18, 0.09);
        overflow: hidden;
      }
      .fill {
        height: 100%;
        border-radius: 999px;
      }
      .chart-card {
        padding: 12px;
        border-radius: 16px;
        border: 1px solid var(--line);
        background: rgba(255, 255, 255, 0.58);
      }
      .chart-card svg {
        width: 100%;
        height: 190px;
        display: block;
      }
      .chart-note {
        display: flex;
        justify-content: space-between;
        gap: 12px;
        flex-wrap: wrap;
        font-size: 12px;
        color: var(--muted);
        margin-top: 8px;
      }
      .legend {
        display: flex;
        gap: 14px;
        flex-wrap: wrap;
      }
      .legend span::before {
        content: "";
        display: inline-block;
        width: 10px;
        height: 10px;
        border-radius: 999px;
        margin-right: 6px;
        vertical-align: middle;
      }
      .legend .mid::before {
        background: #cf6d2a;
      }
      .legend .up::before {
        background: #12704d;
      }
      .legend .down::before {
        background: #b3473b;
      }
      .detail-grid {
        margin-top: 12px;
      }
      .detail {
        padding: 10px;
        border-radius: 14px;
        border: 1px solid var(--line);
        background: rgba(255, 255, 255, 0.5);
      }
      .detail .value {
        margin-top: 6px;
        font-size: 16px;
        font-weight: 700;
      }
      .detail .sub {
        margin-top: 4px;
        font-size: 11px;
        color: var(--muted);
      }
      .table-wrap {
        max-height: 360px;
        overflow: auto;
      }
      .table-wrap.compact {
        max-height: 290px;
      }
      table {
        width: 100%;
        border-collapse: collapse;
      }
      th,
      td {
        text-align: left;
        padding: 8px 5px;
        border-bottom: 1px solid var(--line);
        vertical-align: top;
      }
      th {
        color: var(--muted);
        font-size: 11px;
        text-transform: uppercase;
        letter-spacing: 0.08em;
      }
      .mono {
        font-variant-numeric: tabular-nums;
      }
      .muted {
        color: var(--muted);
      }
      .good {
        color: var(--good);
      }
      .bad {
        color: var(--bad);
      }
      .empty {
        padding: 12px 0 6px;
        color: var(--muted);
      }
      .info-btn {
        width: 22px;
        height: 22px;
        border-radius: 999px;
        border: 1px solid var(--line-strong);
        background: rgba(255, 255, 255, 0.82);
        color: var(--muted);
        font-size: 12px;
        font-weight: 700;
        cursor: pointer;
        display: inline-flex;
        align-items: center;
        justify-content: center;
        flex: none;
      }
      .info-btn:hover {
        color: var(--ink);
        border-color: rgba(36, 23, 18, 0.22);
      }
      .modal {
        position: fixed;
        inset: 0;
        display: none;
        align-items: center;
        justify-content: center;
        background: rgba(25, 17, 12, 0.44);
        padding: 20px;
        z-index: 40;
      }
      .modal.open {
        display: flex;
      }
      .modal-card {
        width: min(520px, 100%);
        background: rgba(255, 251, 246, 0.98);
        border: 1px solid var(--line);
        border-radius: 18px;
        box-shadow: 0 28px 80px rgba(34, 22, 14, 0.18);
        padding: 18px;
      }
      .modal-close {
        border: 0;
        background: transparent;
        color: var(--muted);
        cursor: pointer;
        font-size: 14px;
        padding: 0;
      }
      .modal-body {
        margin-top: 12px;
      }
      #daily-review-rules,
      #daily-review-targets,
      #onboarding-checklist,
      #performance-grid,
      #journal-digest-cards {
        grid-template-columns: repeat(3, minmax(0, 1fr));
      }
      #journal-digest-cards {
        grid-template-columns: repeat(var(--cols, 6), minmax(0, 1fr));
      }
      #hero-ops-grid {
        grid-template-columns: repeat(var(--cols, 4), minmax(0, 1fr));
      }
      #journal-review-focus {
        grid-template-columns: repeat(var(--cols, 4), minmax(0, 1fr));
      }
      #journal-next-reads {
        grid-template-columns: repeat(var(--cols, 2), minmax(0, 1fr));
      }
      #overview-focus-grid {
        grid-template-columns: repeat(var(--cols, 4), minmax(0, 1fr));
      }
      #daily-review-rules {
        grid-template-columns: repeat(var(--cols, 4), minmax(0, 1fr));
      }
      #performance-grid {
        grid-template-columns: repeat(var(--cols, 3), minmax(0, 1fr));
      }
      #daily-review-targets,
      #onboarding-checklist {
        grid-template-columns: repeat(var(--cols, 2), minmax(0, 1fr));
      }
      #risk-grid {
        grid-template-columns: repeat(var(--cols, 3), minmax(0, 1fr));
      }
      @media (max-width: 1220px) {
        .hero,
        .layout,
        .pane-grid,
        .kpis,
        .provider-grid,
        .rules-grid,
        .system-grid,
        .watch-grid,
        .alert-grid,
        .metric-grid,
        .detail-grid,
        .summary-grid {
          grid-template-columns: 1fr;
        }
        .tabbar {
          overflow: auto;
          padding-bottom: 10px;
        }
      }
    </style>
  </head>
  <body>
    <div class="shell">
      <div class="hero">
        <section class="panel strong">
          <div class="eyebrow">Crypto Trading Control Plane</div>
          <h1>Desk locale, disciplinato e spiegabile prima del live.</h1>
          <p class="hero-copy" id="hero-copy"></p>
          <div class="chips" id="hero-chips"></div>
          <div class="summary-grid" id="hero-ops-grid" style="margin-top:12px;"></div>
          <div class="kpis" id="kpis"></div>
        </section>

        <section class="panel">
          <div class="title-row">
            <div class="title-group">
              <h2>Provider e commissioni</h2>
              <button
                class="info-btn"
                type="button"
                data-info="Qui scegliamo quale profilo commissionale usare nella simulazione. Il feed dati segue il venue operativo del desk: cambiano i costi calcolati su ogni trade paper e il contesto viene letto dal collector attivo."
              >i</button>
            </div>
          </div>
          <div class="provider-box">
            <div class="provider-current" id="provider-current"></div>
            <form class="provider-form" id="provider-form">
              <div class="label-row">
                <div class="label-group">
                  <strong>Profilo commissioni simulato</strong>
                  <button
                    class="info-btn"
                    type="button"
                    data-info="Serve per confrontare come cambiano PnL e costi a parita di segnale. Non sta ancora spostando il bot su un exchange diverso."
                  >i</button>
                </div>
              </div>
              <div class="provider-actions">
                <select id="provider-select"></select>
                <button class="primary" id="provider-submit" type="submit">Aggiorna simulazione</button>
                <div class="provider-status muted" id="provider-status"></div>
              </div>
            </form>
            <div class="provider-grid" id="provider-grid"></div>
          </div>
        </section>
      </div>

      <div class="tabbar">
        <button class="tab-btn active" type="button" data-tab="overview">Panoramica</button>
        <button class="tab-btn" type="button" data-tab="markets">Mercati</button>
        <button class="tab-btn" type="button" data-tab="accounts">Account</button>
        <button class="tab-btn" type="button" data-tab="positions">Posizioni</button>
        <button class="tab-btn" type="button" data-tab="journal">Journal</button>
      </div>

      <section class="tab-pane active" data-pane="overview">
        <section class="panel" style="margin-bottom:14px;">
          <div class="title-row">
            <div class="title-group">
              <h2>Panoramica operativa</h2>
              <button
                class="info-btn"
                type="button"
                data-info="Ingresso rapido alla giornata: dice cosa conta adesso, dove guardare e quali sezioni aprire per prime."
              >i</button>
            </div>
          </div>
          <div class="overview-toolbar">
            <div class="overview-jumpbar">
              <button class="overview-nav" type="button" data-overview-jump="overview-alerts-panel">Alert</button>
              <button class="overview-nav" type="button" data-overview-jump="overview-review-panel">Review</button>
              <button class="overview-nav" type="button" data-overview-jump="overview-risk-panel">Rischio</button>
              <button class="overview-nav" type="button" data-overview-jump="overview-performance-panel">Performance</button>
              <button class="overview-nav" type="button" data-overview-jump="overview-trust-panel">Trust</button>
              <button class="overview-nav" type="button" data-overview-jump="overview-onboarding-panel">Onboarding</button>
            </div>
            <div class="overview-toolbar-actions">
              <button class="secondary compact-btn" id="overview-expand-all" type="button">Espandi tutto</button>
              <button class="secondary compact-btn" id="overview-collapse-all" type="button">Compatta tutto</button>
            </div>
          </div>
          <p class="muted" id="overview-summary" style="margin-bottom:12px;"></p>
          <div class="summary-grid" id="overview-focus-grid"></div>
        </section>

        <div class="pane-grid">
          <div class="stack">
            <section class="panel has-collapsible overview-panel" id="overview-alerts-panel" data-overview-panel="alerts">
              <div class="title-row">
                <div class="title-group">
                  <h2>Centro alert</h2>
                  <button
                    class="info-btn"
                    type="button"
                    data-info="Qui trovi il riassunto operativo della sessione: blocchi, condizioni rilevanti, focus simboli e pressione commissionale."
                  >i</button>
                </div>
                <div class="overview-panel-actions">
                  <span class="section-count" id="overview-alerts-count">0 alert</span>
                  <button class="secondary compact-btn overview-toggle" type="button" data-overview-panel-toggle="alerts">Compatta</button>
                </div>
              </div>
              <div class="section-body">
                <div class="alert-grid" id="alert-grid"></div>
              </div>
            </section>

            <section class="panel has-collapsible overview-panel" id="overview-system-panel" data-overview-panel="system">
              <div class="title-row">
                <div class="title-group">
                  <h2>Come lavora il sistema</h2>
                  <button
                    class="info-btn"
                    type="button"
                    data-info="Questa sequenza ti dice come il bot passa dai dati live a una decisione. Nessun passaggio e nascosto."
                  >i</button>
                </div>
                <div class="overview-panel-actions">
                  <span class="section-count" id="overview-system-count">6 fasi</span>
                  <button class="secondary compact-btn overview-toggle" type="button" data-overview-panel-toggle="system">Compatta</button>
                </div>
              </div>
              <div class="section-body">
                <div class="system-grid" id="system-grid"></div>
              </div>
            </section>

            <section class="panel has-collapsible overview-panel" id="overview-review-panel" data-overview-panel="review">
              <div class="title-row">
                <div class="title-group">
                  <h2>Daily review</h2>
                  <button
                    class="info-btn"
                    type="button"
                    data-info="Questa e la review rapida della sessione: i 3 segnali piu importanti della giornata, i simboli da rivedere e le regole che hanno contato."
                  >i</button>
                </div>
                <div class="overview-panel-actions">
                  <span class="section-count" id="overview-review-count">0 focus</span>
                  <button class="secondary compact-btn overview-toggle" type="button" data-overview-panel-toggle="review">Compatta</button>
                </div>
              </div>
              <div class="section-body">
                <p class="muted" id="daily-review-summary" style="margin-bottom:12px;"></p>
                <div class="alert-grid" id="daily-review-highlights"></div>
                <div class="summary-grid" id="daily-review-rules" style="margin-top:12px;"></div>
                <div class="summary-grid" id="daily-review-targets" style="margin-top:12px;"></div>
                <div class="callout" style="margin-top:12px;">
                  <div class="label-row">
                    <div class="label-group">
                      <strong>Domanda finale</strong>
                      <button
                        class="info-btn"
                        type="button"
                        data-info="Chiude la review con una domanda semplice da tenere in testa: serve a trasformare i dati in abitudine di lettura."
                      >i</button>
                    </div>
                  </div>
                  <p style="margin-top:8px;" id="daily-review-prompt"></p>
                </div>
                <form id="daily-review-form" class="provider-form" style="margin-top:12px;">
                  <div class="form-grid">
                    <div>
                      <div class="label-row">
                        <div class="label-group">
                          <strong>Verdetto rapido</strong>
                          <button
                            class="info-btn"
                            type="button"
                            data-info="Etichetta veloce della sessione. Serve a creare memoria operativa senza scrivere troppo."
                          >i</button>
                        </div>
                      </div>
                      <select id="review-verdict">
                        <option value="setup_chiari">Setup chiari</option>
                        <option value="bot_troppo_cauto">Bot troppo cauto</option>
                        <option value="costi_pesanti">Costi troppo pesanti</option>
                        <option value="da_rivedere">Da rivedere</option>
                      </select>
                    </div>
                    <div>
                      <div class="label-row">
                        <div class="label-group">
                          <strong>Ultimo salvataggio</strong>
                          <button
                            class="info-btn"
                            type="button"
                            data-info="Ti ricorda se la review di oggi e gia stata annotata localmente."
                          >i</button>
                        </div>
                      </div>
                      <div class="card">
                        <div class="value mono" id="review-updated-at" style="margin-top:0; font-size:16px; font-weight:700;">n/d</div>
                        <p style="margin-top:6px;">Review locale della giornata corrente.</p>
                      </div>
                    </div>
                  </div>
                  <div>
                    <div class="label-row">
                      <div class="label-group">
                        <strong>Nota della giornata</strong>
                        <button
                          class="info-btn"
                          type="button"
                          data-info="Nota libera molto breve. L'obiettivo e salvare un pensiero utile per la review futura, non fare journaling lungo."
                        >i</button>
                      </div>
                    </div>
                    <textarea id="review-note" placeholder="Es. spread ancora alto su meta watchlist, bot molto prudente ma coerente con il costo."></textarea>
                  </div>
                  <div class="button-row">
                    <button class="primary" id="review-submit" type="submit">Salva review</button>
                    <div class="provider-status muted" id="review-status"></div>
                  </div>
                </form>
              </div>
            </section>
          </div>

          <div class="stack">
            <section class="panel has-collapsible overview-panel" id="overview-risk-panel" data-overview-panel="risk">
              <div class="title-row">
                <div class="title-group">
                  <h2>Controllo rischio</h2>
                  <button
                    class="info-btn"
                    type="button"
                    data-info="Qui vedi lo stato dei guard rail: limiti giornalieri, esposizione, drawdown, cooldown e kill switch."
                  >i</button>
                </div>
                <div class="overview-panel-actions">
                  <span class="section-count" id="overview-risk-count">0 controlli</span>
                  <button class="secondary compact-btn overview-toggle" type="button" data-overview-panel-toggle="risk">Compatta</button>
                </div>
              </div>
              <div class="section-body">
                <div class="summary-grid" id="risk-grid"></div>
              </div>
            </section>

            <section class="panel has-collapsible overview-panel" id="overview-onboarding-panel" data-overview-panel="onboarding">
              <div class="title-row">
                <div class="title-group">
                  <h2>Onboarding alpha</h2>
                  <button
                    class="info-btn"
                    type="button"
                    data-info="Questa sezione serve a capire in pochi secondi se l'alpha e pronta per una demo interna o per un design partner assistito."
                  >i</button>
                </div>
                <div class="overview-panel-actions">
                  <span class="section-count" id="overview-onboarding-count">0 / 0</span>
                  <button class="secondary compact-btn overview-toggle" type="button" data-overview-panel-toggle="onboarding">Compatta</button>
                </div>
              </div>
              <div class="section-body">
                <p class="muted" id="onboarding-summary" style="margin-bottom:12px;"></p>
                <div class="summary-grid" id="onboarding-progress"></div>
                <div class="summary-grid" id="onboarding-checklist" style="margin-top:12px;"></div>
                <div class="callout" style="margin-top:12px;">
                  <div class="label-row">
                    <div class="label-group">
                      <strong>Prossimi passi consigliati</strong>
                      <button
                        class="info-btn"
                        type="button"
                        data-info="Sono i passaggi piu utili per mostrare l'alpha senza disperdersi in feature secondarie."
                      >i</button>
                    </div>
                  </div>
                  <div class="mini-list" id="onboarding-next-steps" style="margin-top:10px;"></div>
                </div>
              </div>
            </section>

            <section class="panel has-collapsible overview-panel" id="overview-performance-panel" data-overview-panel="performance">
              <div class="title-row">
                <div class="title-group">
                  <h2>Statistiche professionali</h2>
                  <button
                    class="info-btn"
                    type="button"
                    data-info="Queste metriche servono a capire se il sistema ha davvero disciplina e edge netto dopo costi e drawdown."
                  >i</button>
                </div>
                <div class="overview-panel-actions">
                  <span class="section-count" id="overview-performance-count">0 metriche</span>
                  <button class="secondary compact-btn overview-toggle" type="button" data-overview-panel-toggle="performance">Compatta</button>
                </div>
              </div>
              <div class="section-body">
                <div class="summary-grid" id="performance-grid" style="margin-bottom:12px;"></div>
                <div id="equity-chart"></div>
              </div>
            </section>

            <section class="panel has-collapsible overview-panel" id="overview-trust-panel" data-overview-panel="trust">
              <div class="title-row">
                <div class="title-group">
                  <h2>Trust layer alpha</h2>
                  <button
                    class="info-btn"
                    type="button"
                    data-info="Qui dichiariamo in modo esplicito modalita operative, workflow supportati, capability del provider e limiti della alpha."
                  >i</button>
                </div>
                <div class="overview-panel-actions">
                  <span class="section-count" id="overview-trust-count">0 workflow</span>
                  <button class="secondary compact-btn overview-toggle" type="button" data-overview-panel-toggle="trust">Compatta</button>
                </div>
              </div>
              <div class="section-body">
                <div class="summary-grid" id="mode-grid"></div>
                <div class="summary-grid" id="capability-grid" style="margin-top:12px;"></div>
                <div class="summary-grid" id="cost-grid" style="margin-top:12px;"></div>
                <div class="summary-grid" id="workflow-grid" style="margin-top:12px;"></div>
                <div class="callout" style="margin-top:12px;">
                  <div class="label-row">
                    <div class="label-group">
                      <strong>Known limitations</strong>
                      <button
                        class="info-btn"
                        type="button"
                        data-info="Questa lista evita aspettative sbagliate: dice chiaramente cosa la alpha non fa ancora."
                      >i</button>
                    </div>
                  </div>
                  <div id="limitations-list" style="margin-top:10px;"></div>
                </div>
              </div>
            </section>
          </div>
        </div>
      </section>

      <section class="tab-pane" data-pane="markets">
        <div class="pane-grid">
          <div class="stack">
            <section class="panel">
              <div class="title-row">
                <div class="title-group">
                  <h2>Mercato selezionato</h2>
                  <button
                    class="info-btn"
                    type="button"
                    data-info="Selezioni una crypto alla volta e vedi solo il suo contesto completo: stato del setup, spread, prezzo medio e prossima mossa richiesta."
                  >i</button>
                </div>
              </div>
              <div class="market-selector" id="market-selector"></div>
              <div class="summary-grid" id="market-brief-grid"></div>
              <div id="watch-grid"></div>
            </section>

            <section class="panel">
              <div class="title-row">
                <div class="title-group">
                  <h2>Decision board</h2>
                  <button
                    class="info-btn"
                    type="button"
                    data-info="Ogni scheda spiega perche il bot sta aspettando, entrando o mantenendo una posizione paper sul singolo simbolo."
                  >i</button>
                </div>
              </div>
              <p class="muted" id="market-decision-summary" style="margin-bottom:14px;"></p>
              <div class="decision-board" id="decision-board"></div>
            </section>
          </div>

          <div class="stack">
            <section class="panel">
              <div class="title-row">
                <div class="title-group">
                  <h2>Regole del motore</h2>
                  <button
                    class="info-btn"
                    type="button"
                    data-info="Queste sono le soglie che il motore deterministico usa per decidere ingressi e uscite paper."
                  >i</button>
                </div>
              </div>
              <div class="rules-grid" id="rules-grid"></div>
            </section>
          </div>
        </div>
      </section>

      <section class="tab-pane" data-pane="accounts">
        <div class="pane-grid">
          <div class="stack">
            <section class="panel">
              <div class="title-row">
                <div class="title-group">
                  <h2>Account center</h2>
                  <button
                    class="info-btn"
                    type="button"
                    data-info="Qui teniamo separati il desk operativo principale, i wallet blockchain e gli account esterni importati manualmente per review e confronto."
                  >i</button>
                </div>
              </div>
              <div class="summary-grid" id="account-center-operational"></div>
              <div class="table-wrap" style="margin-top:14px;">
                <table>
                  <thead>
                    <tr>
                      <th><span class="table-head"><span>Account</span><button class="info-btn" type="button" data-info="Nome dell'account importato o operativo.">i</button></span></th>
                      <th><span class="table-head"><span>Provider</span><button class="info-btn" type="button" data-info="Exchange o provider associato all'account.">i</button></span></th>
                      <th><span class="table-head"><span>Modalita</span><button class="info-btn" type="button" data-info="Dice se l'account e operativo nativo o importato manualmente.">i</button></span></th>
                      <th><span class="table-head"><span>Coverage</span><button class="info-btn" type="button" data-info="Numero di eventi importati e conteggio base di trade, depositi e fee.">i</button></span></th>
                      <th><span class="table-head"><span>Ultimo aggiornamento</span><button class="info-btn" type="button" data-info="Ultimo import o ultimo ciclo disponibile per quell'account.">i</button></span></th>
                      <th><span class="table-head"><span>Azioni</span><button class="info-btn" type="button" data-info="Azioni disponibili sugli account esterni importati nella alpha.">i</button></span></th>
                    </tr>
                  </thead>
                  <tbody id="account-center-table"></tbody>
                </table>
              </div>
            </section>

            <section class="panel">
              <div class="title-row">
                <div class="title-group">
                  <h2>Wallet e venue on-chain</h2>
                  <button
                    class="info-btn"
                    type="button"
                    data-info="Questo e il layer blockchain del control plane: wallet browser, signer dedicati e venue on-chain vengono gestiti separatamente dal desk operativo CEX."
                  >i</button>
                </div>
              </div>
              <p class="muted" id="blockchain-summary" style="margin-bottom:12px;"></p>
              <div class="summary-grid" id="blockchain-operational"></div>
              <div class="summary-grid" id="blockchain-recommended" style="margin-top:12px;"></div>
              <div class="summary-grid" id="blockchain-required-inputs" style="margin-top:12px;"></div>
              <div class="table-wrap" style="margin-top:14px;">
                <table>
                  <thead>
                    <tr>
                      <th><span class="table-head"><span>Wallet</span><button class="info-btn" type="button" data-info="Label locale del wallet o signer registrato.">i</button></span></th>
                      <th><span class="table-head"><span>Venue</span><button class="info-btn" type="button" data-info="Venue on-chain a cui il wallet e associato per watch, shadow o live-prep.">i</button></span></th>
                      <th><span class="table-head"><span>Chain</span><button class="info-btn" type="button" data-info="Chain o ambiente operativo del wallet.">i</button></span></th>
                      <th><span class="table-head"><span>Modalita</span><button class="info-btn" type="button" data-info="WATCH per osservazione, SHADOW_PREP per preparazione, API_PREP o LIVE_PREP per setup piu vicino all'automazione.">i</button></span></th>
                      <th><span class="table-head"><span>Readiness e sync</span><button class="info-btn" type="button" data-info="Qui vedi sia il readiness operativo sia lo stato dell'ultimo snapshot salvato per il wallet.">i</button></span></th>
                      <th><span class="table-head"><span>Azioni</span><button class="info-btn" type="button" data-info="Azioni disponibili sui wallet registrati nel layer blockchain.">i</button></span></th>
                    </tr>
                  </thead>
                  <tbody id="wallet-account-table"></tbody>
                </table>
              </div>
            </section>
          </div>

          <div class="stack">
            <section class="panel">
              <div class="title-row">
                <div class="title-group">
                  <h2>Wallet connect alpha</h2>
                  <button
                    class="info-btn"
                    type="button"
                    data-info="Qui registri wallet browser o signer dedicati. MetaMask viene trattato come wallet layer, non come executor primario del bot."
                  >i</button>
                </div>
              </div>
              <form id="wallet-form" class="provider-form">
                <div class="form-grid">
                  <div>
                    <div class="label-row"><strong>Label wallet</strong></div>
                    <input id="wallet-label" type="text" placeholder="Es. MetaMask operativo">
                  </div>
                  <div>
                    <div class="label-row"><strong>Wallet</strong></div>
                    <select id="wallet-key"></select>
                  </div>
                  <div>
                    <div class="label-row"><strong>Venue</strong></div>
                    <select id="wallet-venue-key"></select>
                  </div>
                  <div>
                    <div class="label-row"><strong>Chain</strong></div>
                    <select id="wallet-chain-key"></select>
                  </div>
                  <div>
                    <div class="label-row"><strong>Modalita</strong></div>
                    <select id="wallet-mode">
                      <option value="WATCH">Watch</option>
                      <option value="SHADOW_PREP">Shadow prep</option>
                      <option value="API_PREP">API prep</option>
                      <option value="LIVE_PREP">Live prep</option>
                    </select>
                  </div>
                  <div>
                    <div class="label-row"><strong>Address / signer id</strong></div>
                    <input id="wallet-address" type="text" placeholder="0x... oppure id signer">
                  </div>
                </div>
                <div>
                  <div class="label-row"><strong>Note wallet</strong></div>
                  <input id="wallet-notes" type="text" placeholder="Es. wallet MetaMask per watch su Arbitrum o API wallet Hyperliquid">
                </div>
                <input id="wallet-source" type="hidden" value="manual">
                <div class="button-row">
                  <button class="secondary" id="wallet-connect-metamask" type="button">Collega MetaMask</button>
                  <button class="secondary" id="wallet-prefill-hyperliquid" type="button">Preset Hyperliquid</button>
                  <button class="secondary" id="wallet-sync-all" type="button">Sync wallet registrati</button>
                </div>
                <div class="button-row">
                  <button class="primary" id="wallet-submit" type="submit">Registra wallet</button>
                  <div class="provider-status muted" id="wallet-status"></div>
                </div>
              </form>
            </section>

            <section class="panel">
              <div class="title-row">
                <div class="title-group">
                  <h2>Import manuale alpha</h2>
                  <button
                    class="info-btn"
                    type="button"
                    data-info="Import minimale per account esterni. Serve a portare dentro dati di review e confronto senza costruire subito una vera integrazione live."
                  >i</button>
                </div>
              </div>
              <form id="manual-import-form" class="provider-form">
                <div class="form-grid">
                  <div>
                    <div class="label-row"><strong>Nome account</strong></div>
                    <input id="import-account-label" type="text" placeholder="Es. Kraken personale">
                  </div>
                  <div>
                    <div class="label-row"><strong>Provider</strong></div>
                    <select id="import-provider-key"></select>
                  </div>
                  <div>
                    <div class="label-row"><strong>Formato</strong></div>
                    <select id="import-format">
                      <option value="csv">CSV</option>
                      <option value="json">JSON</option>
                    </select>
                  </div>
                  <div>
                    <div class="label-row"><strong>Valuta base</strong></div>
                    <input id="import-base-currency" type="text" placeholder="EUR" value="EUR">
                  </div>
                </div>
                <div>
                  <div class="label-row"><strong>Note account</strong></div>
                  <input id="import-notes" type="text" placeholder="Es. import concierge per review settimanale">
                </div>
                <div>
                  <div class="label-row">
                    <strong>Payload da importare</strong>
                    <button
                      class="info-btn"
                      type="button"
                      data-info="Schema minimo: timestamp,event_type,symbol,side,quantity,price,notional,fee,currency,notes. event_type supportati: trade, deposit, withdrawal, fee."
                    >i</button>
                  </div>
                  <textarea id="import-payload" placeholder="timestamp,event_type,symbol,side,quantity,price,notional,fee,currency,notes"></textarea>
                </div>
                <div class="button-row">
                  <button class="secondary" id="import-example-csv" type="button">Carica esempio CSV</button>
                  <button class="secondary" id="import-example-json" type="button">Carica esempio JSON</button>
                  <button class="secondary" id="import-clear" type="button">Pulisci</button>
                </div>
                <div class="button-row">
                  <button class="primary" id="manual-import-submit" type="submit">Importa account</button>
                  <div class="provider-status muted" id="manual-import-status"></div>
                </div>
              </form>
            </section>

            <section class="panel">
              <div class="title-row">
                <div class="title-group">
                  <h2>Schema import alpha</h2>
                  <button
                    class="info-btn"
                    type="button"
                    data-info="Questo e il contratto minimo accettato dall'import manuale della alpha. E volutamente stretto per non allargare il perimetro troppo presto."
                  >i</button>
                </div>
              </div>
              <div class="summary-grid" id="import-schema"></div>
            </section>

            <section class="panel">
              <div class="title-row">
                <div class="title-group">
                  <h2>Insight account importati</h2>
                  <button
                    class="info-btn"
                    type="button"
                    data-info="Riassume la scala minima di ogni account importato: flow, fee e volume letto. Serve a capire se l'import sta gia diventando utile."
                  >i</button>
                </div>
              </div>
              <div class="summary-grid" id="imported-account-insights"></div>
            </section>
          </div>
        </div>

        <section class="panel" style="margin-top:18px;">
          <div class="title-row">
            <div class="title-group">
              <h2>Attivita importate recenti</h2>
              <button
                class="info-btn"
                type="button"
                data-info="Stream delle ultime righe importate dagli account esterni. Utile per verificare al volo che l'import manuale abbia portato dentro il contesto giusto."
              >i</button>
            </div>
          </div>
          <div class="table-wrap">
            <table>
              <thead>
                <tr>
                  <th><span class="table-head"><span>Ora</span><button class="info-btn" type="button" data-info="Timestamp dell'evento importato dall'account esterno.">i</button></span></th>
                  <th><span class="table-head"><span>Account</span><button class="info-btn" type="button" data-info="Account importato a cui appartiene l'evento.">i</button></span></th>
                  <th><span class="table-head"><span>Tipo</span><button class="info-btn" type="button" data-info="Tipo di evento importato: trade, deposito, prelievo o fee.">i</button></span></th>
                  <th><span class="table-head"><span>Dettaglio</span><button class="info-btn" type="button" data-info="Riassunto leggibile dell'evento con simbolo, side o importi principali.">i</button></span></th>
                  <th><span class="table-head"><span>Valore</span><button class="info-btn" type="button" data-info="Notional o fee associata all'evento importato.">i</button></span></th>
                </tr>
              </thead>
              <tbody id="import-events"></tbody>
            </table>
          </div>
        </section>
      </section>

      <section class="tab-pane" data-pane="positions">
        <div class="single-column">
          <section class="panel">
            <div class="title-row">
              <div class="title-group">
                <h2>Posizioni paper</h2>
                <button
                  class="info-btn"
                  type="button"
                  data-info="Qui vedi le posizioni simulate dal bot: ingressi, fee pagate, PnL aperto o chiuso."
                >i</button>
              </div>
            </div>
            <div class="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th><span class="table-head"><span>Simbolo</span><button class="info-btn" type="button" data-info="La coppia che il bot sta monitorando, per esempio BTC-USD.">i</button></span></th>
                    <th><span class="table-head"><span>Stato</span><button class="info-btn" type="button" data-info="OPEN vuol dire posizione ancora aperta. CLOSED vuol dire operazione gia terminata.">i</button></span></th>
                    <th><span class="table-head"><span>Ingresso</span><button class="info-btn" type="button" data-info="Prezzo e orario di entrata della posizione paper.">i</button></span></th>
                    <th><span class="table-head"><span>Piano rischio</span><button class="info-btn" type="button" data-info="Stop, target e rischio pianificato al momento dell'ingresso paper.">i</button></span></th>
                    <th><span class="table-head"><span>Uscita / motivo</span><button class="info-btn" type="button" data-info="Per le posizioni chiuse mostra prezzo, orario e causa di uscita. Per le aperte mostra lo stato attuale.">i</button></span></th>
                    <th><span class="table-head"><span>Fee</span><button class="info-btn" type="button" data-info="Somma delle commissioni simulate pagate in ingresso e, se presente, in uscita.">i</button></span></th>
                    <th><span class="table-head"><span>PnL</span><button class="info-btn" type="button" data-info="Profitto o perdita, al netto delle fee simulate.">i</button></span></th>
                  </tr>
                </thead>
                <tbody id="positions"></tbody>
              </table>
            </div>
          </section>
        </div>
      </section>

      <section class="tab-pane" data-pane="journal">
        <section class="panel" style="margin-bottom:14px;">
          <div class="title-row">
            <div class="title-group">
              <h2>Journal digest</h2>
              <button
                class="info-btn"
                type="button"
                data-info="Ingresso rapido alla review del journal: riassume cosa leggere prima e in che ordine, senza costringerti a scorrere tutte le tabelle."
              >i</button>
            </div>
          </div>
          <div class="journal-toolbar">
            <div class="journal-jumpbar">
              <button class="journal-nav" type="button" data-jump="journal-signals-panel">Segnali</button>
              <button class="journal-nav" type="button" data-jump="journal-events-panel">Timeline</button>
              <button class="journal-nav" type="button" data-jump="journal-replay-panel">Replay</button>
              <button class="journal-nav" type="button" data-jump="journal-ledger-panel">Ledger</button>
              <button class="journal-nav" type="button" data-jump="journal-failure-panel">Failure</button>
            </div>
            <div class="journal-toolbar-actions">
              <button class="secondary compact-btn" id="journal-expand-all" type="button">Espandi tutto</button>
              <button class="secondary compact-btn" id="journal-collapse-all" type="button">Compatta tutto</button>
            </div>
          </div>
          <p class="muted" id="journal-digest-summary" style="margin-bottom:12px;"></p>
          <div class="summary-grid" id="journal-digest-cards"></div>
          <div class="summary-grid" id="journal-review-focus" style="margin-top:12px;"></div>
          <div class="callout" style="margin-top:12px;">
            <div class="label-row">
              <div class="label-group">
                <strong>Cosa leggere per primo</strong>
                <button
                  class="info-btn"
                  type="button"
                  data-info="Ordine di lettura consigliato per trasformare il journal in una review veloce, non in un archivio da scorrere senza criterio."
                >i</button>
              </div>
            </div>
            <div class="mini-list" id="journal-next-reads" style="margin-top:10px;"></div>
          </div>
        </section>

        <div class="pane-grid">
          <div class="stack">
            <section class="panel journal-panel" id="journal-signals-panel" data-journal-panel="signals">
              <div class="title-row">
                <div class="title-group">
                  <h2>Segnali recenti</h2>
                  <button
                    class="info-btn"
                    type="button"
                    data-info="Sono le decisioni che il motore ha preso o segnalato di recente, con il motivo sintetico."
                  >i</button>
                </div>
                <div class="journal-panel-actions">
                  <span class="section-count" id="journal-signals-count">0 righe</span>
                  <button class="secondary compact-btn section-toggle" type="button" data-panel="signals">Compatta</button>
                </div>
              </div>
              <div class="section-body">
              <div class="table-wrap compact">
                <table>
                  <thead>
                    <tr>
                      <th><span class="table-head"><span>Ora</span><button class="info-btn" type="button" data-info="Timestamp UTC del segnale registrato.">i</button></span></th>
                      <th><span class="table-head"><span>Simbolo</span><button class="info-btn" type="button" data-info="La coppia associata al segnale.">i</button></span></th>
                      <th><span class="table-head"><span>Azione</span><button class="info-btn" type="button" data-info="La mossa suggerita o eseguita dal motore: attendi, compra, mantieni o vendi.">i</button></span></th>
                      <th><span class="table-head"><span>Motivo</span><button class="info-btn" type="button" data-info="La spiegazione sintetica del segnale.">i</button></span></th>
                    </tr>
                  </thead>
                  <tbody id="signals"></tbody>
                </table>
              </div>
              </div>
            </section>

            <section class="panel journal-panel" id="journal-replay-panel" data-journal-panel="replay">
              <div class="title-row">
                <div class="title-group">
                  <h2>Decision replay</h2>
                  <button
                    class="info-btn"
                    type="button"
                    data-info="Replay asciutto delle decisioni importanti: cosa ha visto il sistema, quale regola ha contato e in che modalita stavamo lavorando."
                  >i</button>
                </div>
                <div class="journal-panel-actions">
                  <span class="section-count" id="journal-replay-count">0 righe</span>
                  <button class="secondary compact-btn section-toggle" type="button" data-panel="replay">Compatta</button>
                </div>
              </div>
              <div class="section-body">
              <div class="table-wrap compact">
                <table>
                  <thead>
                    <tr>
                      <th><span class="table-head"><span>Ora</span><button class="info-btn" type="button" data-info="Quando il replay decisionale e stato registrato.">i</button></span></th>
                      <th><span class="table-head"><span>Simbolo</span><button class="info-btn" type="button" data-info="Il simbolo o mercato a cui si riferisce la decisione.">i</button></span></th>
                      <th><span class="table-head"><span>Modalita</span><button class="info-btn" type="button" data-info="Paper, live shadow o live. Nella alpha il live resta disabilitato.">i</button></span></th>
                      <th><span class="table-head"><span>Regola decisiva</span><button class="info-btn" type="button" data-info="La regola o il filtro che ha pesato di piu su quella decisione.">i</button></span></th>
                      <th><span class="table-head"><span>Motivo</span><button class="info-btn" type="button" data-info="Spiegazione sintetica del perche il sistema ha atteso, bloccato o mosso qualcosa.">i</button></span></th>
                    </tr>
                  </thead>
                  <tbody id="decision-replay"></tbody>
                </table>
              </div>
              </div>
            </section>

            <section class="panel journal-panel" id="journal-failure-panel" data-journal-panel="failure">
              <div class="title-row">
                <div class="title-group">
                  <h2>Failure analysis</h2>
                  <button
                    class="info-btn"
                    type="button"
                    data-info="Riassume gli insuccessi piu importanti della giornata o della finestra recente: blocchi, bassa convinzione, violazioni e anomalie di esecuzione."
                  >i</button>
                </div>
                <div class="journal-panel-actions">
                  <span class="section-count" id="journal-failure-count">0 focus</span>
                  <button class="secondary compact-btn section-toggle" type="button" data-panel="failure">Compatta</button>
                </div>
              </div>
              <div class="section-body">
                <div class="summary-grid" id="failure-analysis"></div>
              </div>
            </section>
          </div>

          <div class="stack">
            <section class="panel journal-panel" id="journal-events-panel" data-journal-panel="events">
              <div class="title-row">
                <div class="title-group">
                  <h2>Timeline operativa</h2>
                  <button
                    class="info-btn"
                    type="button"
                    data-info="Timeline filtrata degli eventi davvero utili alla review: errori, import, cambi stato e passaggi operativi significativi."
                  >i</button>
                </div>
                <div class="journal-panel-actions">
                  <span class="section-count" id="journal-events-count">0 righe</span>
                  <button class="secondary compact-btn section-toggle" type="button" data-panel="events">Compatta</button>
                </div>
              </div>
              <div class="section-body">
              <div class="table-wrap compact">
                <table>
                  <thead>
                    <tr>
                      <th><span class="table-head"><span>Ora</span><button class="info-btn" type="button" data-info="Quando l'evento e stato salvato nel log.">i</button></span></th>
                      <th><span class="table-head"><span>Sorgente</span><button class="info-btn" type="button" data-info="Il componente che ha prodotto l'evento, per esempio public_bot o paper_engine.">i</button></span></th>
                      <th><span class="table-head"><span>Messaggio</span><button class="info-btn" type="button" data-info="Descrizione sintetica di quello che e successo.">i</button></span></th>
                    </tr>
                  </thead>
                  <tbody id="events"></tbody>
                </table>
              </div>
              </div>
            </section>

            <section class="panel journal-panel" id="journal-ledger-panel" data-journal-panel="ledger">
              <div class="title-row">
                <div class="title-group">
                  <h2>Event ledger</h2>
                  <button
                    class="info-btn"
                    type="button"
                    data-info="Ledger strutturato degli eventi alpha: depositi, fee, cambi configurazione, blocchi guard rail e riferimenti al replay."
                  >i</button>
                </div>
                <div class="journal-panel-actions">
                  <span class="section-count" id="journal-ledger-count">0 righe</span>
                  <button class="secondary compact-btn section-toggle" type="button" data-panel="ledger">Compatta</button>
                </div>
              </div>
              <div class="section-body">
              <div class="table-wrap compact">
                <table>
                  <thead>
                    <tr>
                      <th><span class="table-head"><span>Ora</span><button class="info-btn" type="button" data-info="Timestamp dell'evento strutturato.">i</button></span></th>
                      <th><span class="table-head"><span>Tipo</span><button class="info-btn" type="button" data-info="Categoria dell'evento nel ledger: deposito, fee, blocco guard rail, replay, cambio strategia o simili.">i</button></span></th>
                      <th><span class="table-head"><span>Titolo</span><button class="info-btn" type="button" data-info="Messaggio breve leggibile anche da un partner esterno.">i</button></span></th>
                      <th><span class="table-head"><span>Riferimento</span><button class="info-btn" type="button" data-info="Collegamento logico a simbolo, posizione o altra entita importante.">i</button></span></th>
                    </tr>
                  </thead>
                  <tbody id="ledger"></tbody>
                </table>
              </div>
              </div>
            </section>
          </div>
        </div>
      </section>
    </div>

    <div class="modal" id="info-modal" aria-hidden="true">
      <div class="modal-card">
        <div class="title-row">
          <div class="title-group">
            <h3>Spiegazione</h3>
          </div>
          <button class="modal-close" id="modal-close" type="button">Chiudi</button>
        </div>
        <div class="modal-body" id="modal-body"></div>
      </div>
    </div>

    <script>
      let activeMoneyCurrency = "EUR";
      function setMoneyCurrency(currency) {
        const normalized = String(currency || "EUR").toUpperCase();
        activeMoneyCurrency = normalized;
      }

      function moneyFormatter() {
        return new Intl.NumberFormat("it-IT", {
          style: "currency",
          currency: activeMoneyCurrency,
          minimumFractionDigits: 2,
          maximumFractionDigits: 2
        });
      }
      const numberFormatter = new Intl.NumberFormat("it-IT", {
        minimumFractionDigits: 2,
        maximumFractionDigits: 6
      });

      function escapeAttr(value) {
        return String(value ?? "")
          .replace(/&/g, "&amp;")
          .replace(/"/g, "&quot;")
          .replace(/</g, "&lt;")
          .replace(/>/g, "&gt;");
      }

      function infoButton(text) {
        return `<button class="info-btn" type="button" data-info="${escapeAttr(text)}">i</button>`;
      }

      function eur(value) {
        if (value === null || value === undefined || Number.isNaN(Number(value))) return "n/d";
        return moneyFormatter().format(Number(value));
      }

      function num(value, digits = 4) {
        if (value === null || value === undefined || Number.isNaN(Number(value))) return "n/d";
        return Number(value).toLocaleString("it-IT", {
          minimumFractionDigits: digits,
          maximumFractionDigits: digits
        });
      }

      function qty(value) {
        if (value === null || value === undefined || Number.isNaN(Number(value))) return "n/d";
        return numberFormatter.format(Number(value));
      }

      function pct(value, digits = 3) {
        if (value === null || value === undefined || Number.isNaN(Number(value))) return "n/d";
        return Number(value).toLocaleString("it-IT", {
          minimumFractionDigits: digits,
          maximumFractionDigits: digits
        }) + "%";
      }

      function bps(value) {
        if (value === null || value === undefined || Number.isNaN(Number(value))) return "n/d";
        return Number(value).toLocaleString("it-IT", {
          minimumFractionDigits: 2,
          maximumFractionDigits: 2
        }) + " bps";
      }

      function toneClass(status) {
        const code = String(status || "").toUpperCase();
        if (["ENTRATA_ESEGUITA", "IN_POSIZIONE", "RUNNING", "ATTIVO"].includes(code)) return "ok";
        if (["BLOCCATO", "ERROR", "HARD_STOP"].includes(code)) return "bad";
        return "watch";
      }

      function niceStatus(status) {
        const labels = {
          "DATI_INSUFFICIENTI": "Dati insufficienti",
          "ATTESA_CANDELE": "Attesa candele",
          "OSSERVAZIONE": "Osservazione",
          "BLOCCATO": "Bloccato",
          "ENTRATA_ESEGUITA": "Entrata eseguita",
          "IN_POSIZIONE": "In posizione",
          "USCITA_ESEGUITA": "Uscita eseguita",
          "ATTIVO": "Attivo",
          "COOLDOWN": "Cooldown",
          "HARD_STOP": "Hard stop",
          "starting": "Avvio",
          "running": "Attivo",
          "stopped": "Fermo",
          "error": "Errore"
        };
        return labels[status] || status || "n/d";
      }

      function niceAction(action) {
        const labels = {
          "ATTENDI": "Attendi",
          "COMPRA": "Compra",
          "MANTIENI": "Mantieni",
          "VENDI": "Vendi",
          "BUY": "Compra",
          "SELL": "Vendi",
          "HOLD": "Mantieni",
          "WAIT": "Attendi"
        };
        return labels[action] || action || "n/d";
      }

      function buildBadge(text, kind = "watch") {
        return `<span class="status ${kind}">${text}</span>`;
      }

      function progressColor(kind) {
        if (kind === "bad") return "var(--bad)";
        if (kind === "ok") return "var(--good)";
        return "var(--accent)";
      }

      function clamp(value, min, max) {
        return Math.max(min, Math.min(max, value));
      }

      function progressCard(label, valueText, ratio, kind, infoText) {
        const width = clamp(ratio, 0, 1) * 100;
        return `
          <div class="progress">
            <div class="progress-head">
              <div class="progress-title">
                <strong>${label}</strong>
                ${infoButton(infoText)}
              </div>
              <span class="mono muted">${valueText}</span>
            </div>
            <div class="track">
              <div class="fill" style="width:${width}%; background:${progressColor(kind)};"></div>
            </div>
          </div>
        `;
      }

      function metricCard(label, value, sub, infoText, valueClass = "") {
        return `
          <div class="metric">
            <div class="metric-head">
              <div class="label-group">
                <strong>${label}</strong>
                ${infoButton(infoText)}
              </div>
            </div>
            <div class="value mono ${valueClass}">${value}</div>
            <div class="sub">${sub}</div>
          </div>
        `;
      }

      function detailCard(label, value, sub, infoText, valueClass = "") {
        return `
          <div class="detail">
            <div class="label-row">
              <div class="label-group">
                <strong>${label}</strong>
                ${infoButton(infoText)}
              </div>
            </div>
            <div class="value mono ${valueClass}">${value}</div>
            <div class="sub">${sub}</div>
          </div>
        `;
      }

      function alertCard(title, body, kind = "watch", foot = "") {
        return `
          <div class="alert-card ${kind}">
            <strong>${title}</strong>
            <p>${body}</p>
            <div class="foot">${foot}</div>
          </div>
        `;
      }

      function statusToneFromValue(current, target, invert = false) {
        const c = Number(current);
        const t = Number(target);
        if (!Number.isFinite(c) || !Number.isFinite(t) || t === 0) return "watch";
        if (invert) {
          return c <= t ? "ok" : "bad";
        }
        return c >= t ? "ok" : "watch";
      }

      function directionalSide(side) {
        return (side || "LONG").toUpperCase() === "SHORT" ? "SHORT" : "LONG";
      }

      function directionalMultiplier(side) {
        return directionalSide(side) === "SHORT" ? -1 : 1;
      }

      function directionalReady(current, target, side) {
        const c = Number(current);
        const t = Number(target);
        if (!Number.isFinite(c) || !Number.isFinite(t) || t === 0) return false;
        const multiplier = directionalMultiplier(side);
        return (c * multiplier) >= (t * multiplier);
      }

      function directionalRatio(current, target, side) {
        const c = Number(current);
        const t = Number(target);
        if (!Number.isFinite(c) || !Number.isFinite(t) || t === 0) return 0;
        const multiplier = directionalMultiplier(side);
        return (c * multiplier) / Math.abs(t);
      }

      function directionalTone(current, target, side) {
        return directionalReady(current, target, side) ? "ok" : "watch";
      }

      function buildChart(midHistory, candleHistory) {
        const candles = (candleHistory || []).slice(-18).map(item => ({
          open: Number(item.open),
          high: Number(item.high),
          low: Number(item.low),
          close: Number(item.close)
        })).filter(item => [item.open, item.high, item.low, item.close].every(Number.isFinite));
        const mids = (midHistory || []).slice(-26).map(item => Number(item.mid)).filter(Number.isFinite);
        const values = [
          ...candles.flatMap(item => [item.low, item.high]),
          ...mids
        ];

        if (values.length < 2) {
          return `
            <div class="chart-card">
              <div class="muted">Ancora troppo poca storia per disegnare un grafico leggibile.</div>
            </div>
          `;
        }

        const min = Math.min(...values);
        const max = Math.max(...values);
        const range = max - min || 1;
        const padX = 6;
        const padY = 8;
        const plotWidth = 88;
        const plotHeight = 84;

        function scaleY(value) {
          return padY + (1 - ((value - min) / range)) * plotHeight;
        }

        const grid = [0, 0.25, 0.5, 0.75, 1].map(step => {
          const y = padY + step * plotHeight;
          return `<line x1="${padX}" y1="${y}" x2="${padX + plotWidth}" y2="${y}" stroke="rgba(36,23,18,0.08)" stroke-width="0.6" />`;
        }).join("");

        const candleMarkup = candles.map((item, index) => {
          const step = candles.length === 1 ? 0 : plotWidth / (candles.length - 1);
          const x = padX + index * step;
          const bodyWidth = Math.max(2.2, plotWidth / Math.max(candles.length * 2.4, 8));
          const openY = scaleY(item.open);
          const closeY = scaleY(item.close);
          const highY = scaleY(item.high);
          const lowY = scaleY(item.low);
          const bodyTop = Math.min(openY, closeY);
          const bodyHeight = Math.max(Math.abs(openY - closeY), 1.2);
          const color = item.close >= item.open ? "#12704d" : "#b3473b";
          return `
            <line x1="${x}" y1="${highY}" x2="${x}" y2="${lowY}" stroke="${color}" stroke-width="1.1" />
            <rect x="${x - bodyWidth / 2}" y="${bodyTop}" width="${bodyWidth}" height="${bodyHeight}" fill="${color}" rx="0.7" />
          `;
        }).join("");

        const midPoints = mids.map((value, index) => {
          const x = padX + (mids.length === 1 ? plotWidth / 2 : (index / (mids.length - 1)) * plotWidth);
          const y = scaleY(value);
          return `${x},${y}`;
        }).join(" ");

        return `
          <div class="chart-card">
            <div class="subhead" style="margin-bottom:8px;">
              <div class="label-group">
                <strong>Grafico contesto prezzo</strong>
                ${infoButton("Le barre mostrano le ultime candele del venue operativo. La linea arancione mostra i mid-price piu recenti dell'order book. Serve a capire se il micro-movimento conferma il trend piu lento.")}
              </div>
              <span class="muted mono">${eur(max)} / ${eur(min)}</span>
            </div>
            <svg viewBox="0 0 100 100" preserveAspectRatio="none">
              ${grid}
              ${candleMarkup}
              <polyline fill="none" stroke="#cf6d2a" stroke-width="2" points="${midPoints}"></polyline>
            </svg>
            <div class="chart-note">
              <div class="legend">
                <span class="mid">Linea mid-price</span>
                <span class="up">Candle in rialzo</span>
                <span class="down">Candle in ribasso</span>
              </div>
              <div>Range visibile: ${eur(min)} - ${eur(max)}</div>
            </div>
          </div>
        `;
      }

      function buildEquityChart(history) {
        const points = (history || []).slice(-90).map(item => ({
          equity: Number(item.equity),
          exposure: Number(item.exposure_pct)
        })).filter(item => Number.isFinite(item.equity));

        if (points.length < 2) {
          return `
            <div class="chart-card">
              <div class="muted">Servono ancora piu snapshot per costruire una curva equity leggibile.</div>
            </div>
          `;
        }

        const min = Math.min(...points.map(item => item.equity));
        const max = Math.max(...points.map(item => item.equity));
        const range = max - min || 1;
        const padX = 6;
        const padY = 8;
        const plotWidth = 88;
        const plotHeight = 84;

        function scaleY(value) {
          return padY + (1 - ((value - min) / range)) * plotHeight;
        }

        const grid = [0, 0.25, 0.5, 0.75, 1].map(step => {
          const y = padY + step * plotHeight;
          return `<line x1="${padX}" y1="${y}" x2="${padX + plotWidth}" y2="${y}" stroke="rgba(36,23,18,0.08)" stroke-width="0.6" />`;
        }).join("");

        const equityLine = points.map((item, index) => {
          const x = padX + (index / (points.length - 1)) * plotWidth;
          const y = scaleY(item.equity);
          return `${x},${y}`;
        }).join(" ");

        return `
          <div class="chart-card">
            <div class="subhead" style="margin-bottom:8px;">
              <div class="label-group">
                <strong>Curva equity</strong>
                ${infoButton("Mostra come si muove il capitale totale del paper account nel tempo. E uno dei grafici piu importanti per capire stabilita, drawdown e recupero del sistema.")}
              </div>
              <span class="muted mono">${eur(max)} / ${eur(min)}</span>
            </div>
            <svg viewBox="0 0 100 100" preserveAspectRatio="none">
              ${grid}
              <polyline fill="none" stroke="#1a7e56" stroke-width="2.2" points="${equityLine}"></polyline>
            </svg>
            <div class="chart-note">
              <div class="legend">
                <span class="up">Linea equity</span>
              </div>
              <div>Range visibile: ${eur(min)} - ${eur(max)}</div>
            </div>
          </div>
        `;
      }

      function renderEmpty(message, colspan) {
        return `<tr><td colspan="${colspan}" class="empty">${message}</td></tr>`;
      }

      function previewPairs(objectValue, maxItems = 2) {
        if (!objectValue || typeof objectValue !== "object") return "";
        return Object.entries(objectValue)
          .slice(0, maxItems)
          .map(([key, value]) => {
            const rendered = value && typeof value === "object"
              ? JSON.stringify(value)
              : String(value);
            return `${key}: ${rendered}`;
          })
          .join(" | ");
      }

      function compactList(items, emptyText) {
        if (!items || !items.length) {
          return `<p style="margin-top:8px;">${emptyText}</p>`;
        }
        return `<ul class="compact-list">${items.map(item => `<li>${item}</li>`).join("")}</ul>`;
      }

      function balancedColumnCount(count, maxCols = 4) {
        if (!count || count <= 1) return 1;
        const limit = Math.min(maxCols, count);
        let bestCols = 1;
        let bestScore = Number.POSITIVE_INFINITY;
        for (let cols = 1; cols <= limit; cols += 1) {
          const rows = Math.ceil(count / cols);
          const empties = rows * cols - count;
          const score = (empties * 5) + (rows * 2) + Math.abs(cols - 3);
          if (score < bestScore) {
            bestScore = score;
            bestCols = cols;
          }
        }
        return bestCols;
      }

      function setBalancedGridColumns(elementId, count, maxCols = 4) {
        const node = document.getElementById(elementId);
        if (!node) return;
        node.style.setProperty("--cols", String(balancedColumnCount(count, maxCols)));
      }

      const importExamples = {
        csv: [
          "timestamp,event_type,symbol,side,quantity,price,notional,fee,currency,notes",
          "2026-03-17T08:30:00Z,deposit,,,,500,0,EUR,deposito iniziale",
          "2026-03-17T09:12:00Z,trade,BTC-USD,BUY,0.0015,64200,96.30,0.09,USD,ingresso test",
          "2026-03-17T09:55:00Z,trade,BTC-USD,SELL,0.0015,64540,96.81,0.09,USD,uscita test",
          "2026-03-17T09:55:05Z,fee,,,,,0,0.18,EUR,fee giornata"
        ].join("\\n"),
        json: JSON.stringify(
          [
            {
              timestamp: "2026-03-17T08:30:00Z",
              event_type: "deposit",
              notional: 500,
              currency: "EUR",
              notes: "deposito iniziale"
            },
            {
              timestamp: "2026-03-17T09:12:00Z",
              event_type: "trade",
              symbol: "BTC-USD",
              side: "BUY",
              quantity: 0.0015,
              price: 64200,
              notional: 96.3,
              fee: 0.09,
              currency: "EUR",
              notes: "ingresso test"
            },
            {
              timestamp: "2026-03-17T09:55:00Z",
              event_type: "trade",
              symbol: "BTC-USD",
              side: "SELL",
              quantity: 0.0015,
              price: 64540,
              notional: 96.81,
              fee: 0.09,
              currency: "EUR",
              notes: "uscita test"
            }
          ],
          null,
          2
        )
      };

      function loadImportExample(formatName) {
        document.getElementById("import-format").value = formatName;
        document.getElementById("import-payload").value = importExamples[formatName];
        if (!document.getElementById("import-account-label").value) {
          document.getElementById("import-account-label").value = "Account demo";
        }
        if (!document.getElementById("import-notes").value) {
          document.getElementById("import-notes").value = "template alpha per review manuale";
        }
        document.getElementById("manual-import-status").textContent =
          `Template ${formatName.toUpperCase()} caricato nel form.`;
      }

      function clearImportForm() {
        document.getElementById("import-payload").value = "";
        document.getElementById("manual-import-status").textContent = "Form di import pulito.";
      }

      let currentSummary = null;

      function walletStatus(message) {
        const node = document.getElementById("wallet-status");
        if (node) {
          node.textContent = message;
        }
      }

      function chainKeyFromChainHex(chainHex) {
        const chainId = Number.parseInt(chainHex, 16);
        const chains = currentSummary?.blockchain?.chains || [];
        const match = chains.find(item => Number(item.chain_id) === chainId);
        return match ? match.key : "ARBITRUM";
      }

      function chainHexFromChainKey(chainKey) {
        const chains = currentSummary?.blockchain?.chains || [];
        const match = chains.find(item => item.key === chainKey);
        if (!match || match.chain_id === null || match.chain_id === undefined) {
          return null;
        }
        return `0x${Number(match.chain_id).toString(16)}`;
      }

      function prefillHyperliquidSetup() {
        document.getElementById("wallet-key").value = "HYPERLIQUID_API_WALLET";
        document.getElementById("wallet-venue-key").value = "HYPERLIQUID";
        document.getElementById("wallet-chain-key").value = "HYPERLIQUID";
        document.getElementById("wallet-mode").value = "API_PREP";
        document.getElementById("wallet-source").value = "manual";
        if (!document.getElementById("wallet-label").value) {
          document.getElementById("wallet-label").value = "Hyperliquid API wallet";
        }
        if (!document.getElementById("wallet-notes").value) {
          document.getElementById("wallet-notes").value = "Signer dedicato per future automazioni su Hyperliquid.";
        }
        walletStatus("Preset Hyperliquid caricato nel form.");
      }

      async function connectMetaMask() {
        if (!window.ethereum || typeof window.ethereum.request !== "function") {
          walletStatus("MetaMask non rilevato nel browser. Apri la dashboard in un browser con estensione MetaMask.");
          return;
        }
        walletStatus("Connessione MetaMask in corso...");
        try {
          const accounts = await window.ethereum.request({ method: "eth_requestAccounts" });
          if (!accounts || !accounts.length) {
            walletStatus("MetaMask non ha restituito alcun account.");
            return;
          }
          const chainHex = await window.ethereum.request({ method: "eth_chainId" });
          const chainKey = chainKeyFromChainHex(chainHex);
          const address = String(accounts[0]);
          document.getElementById("wallet-key").value = "METAMASK_EXTENSION";
          document.getElementById("wallet-chain-key").value = chainKey;
          document.getElementById("wallet-venue-key").value =
            chainKey === "ARBITRUM" || chainKey === "AVALANCHE" ? "GMX_V2" : "UNISWAP_EVM";
          document.getElementById("wallet-mode").value = "WATCH";
          document.getElementById("wallet-address").value = address;
          document.getElementById("wallet-source").value = "metamask";
          if (!document.getElementById("wallet-label").value) {
            document.getElementById("wallet-label").value = `MetaMask ${address.slice(0, 6)}...${address.slice(-4)}`;
          }
          if (!document.getElementById("wallet-notes").value) {
            document.getElementById("wallet-notes").value = "Wallet collegato via MetaMask per watch, review e manual mode.";
          }
          walletStatus(`MetaMask collegato: ${address.slice(0, 6)}...${address.slice(-4)} su ${chainKey}.`);
        } catch (error) {
          walletStatus("Connessione MetaMask non riuscita o rifiutata.");
        }
      }

      async function updateWalletAccount(event) {
        event.preventDefault();
        const button = document.getElementById("wallet-submit");
        button.disabled = true;
        walletStatus("Registrazione wallet in corso...");
        try {
          const response = await fetch("/api/wallet/register", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
              label: document.getElementById("wallet-label").value,
              wallet_key: document.getElementById("wallet-key").value,
              venue_key: document.getElementById("wallet-venue-key").value,
              chain_key: document.getElementById("wallet-chain-key").value,
              mode: document.getElementById("wallet-mode").value,
              address: document.getElementById("wallet-address").value,
              notes: document.getElementById("wallet-notes").value,
              source: document.getElementById("wallet-source").value || "manual"
            })
          });
          const payload = await response.json();
          if (!response.ok) {
            walletStatus(payload.message || "Registrazione wallet non riuscita.");
          } else {
            walletStatus(payload.message || "Wallet registrato.");
            document.getElementById("wallet-source").value = "manual";
            await loadSummary();
          }
        } catch (error) {
          walletStatus("Errore di rete durante la registrazione del wallet.");
        } finally {
          button.disabled = false;
        }
      }

      async function deleteWalletAccount(accountKey, label) {
        if (!window.confirm(`Rimuovere il wallet "${label}" dal layer blockchain?`)) {
          return;
        }
        walletStatus(`Rimozione di ${label} in corso...`);
        try {
          const response = await fetch("/api/wallet/delete", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ account_key: accountKey })
          });
          const payload = await response.json();
          if (!response.ok) {
            walletStatus(payload.message || "Rimozione wallet non riuscita.");
          } else {
            walletStatus(payload.message || "Wallet rimosso.");
            await loadSummary();
          }
        } catch (error) {
          walletStatus("Errore durante la rimozione del wallet.");
        }
      }

      async function buildBrowserSnapshotForWallet(account) {
        if (!window.ethereum || typeof window.ethereum.request !== "function") {
          throw new Error("MetaMask non disponibile in questo browser.");
        }
        await window.ethereum.request({ method: "eth_requestAccounts" });
        const expectedChainHex = chainHexFromChainKey(account.chain_key);
        if (expectedChainHex) {
          try {
            await window.ethereum.request({
              method: "wallet_switchEthereumChain",
              params: [{ chainId: expectedChainHex }]
            });
          } catch (error) {
            throw new Error("Non sono riuscito a portare MetaMask sulla chain del wallet selezionato.");
          }
        }
        const [chainIdHex, balanceHex, txCountHex, blockNumberHex] = await Promise.all([
          window.ethereum.request({ method: "eth_chainId" }),
          window.ethereum.request({ method: "eth_getBalance", params: [account.address, "latest"] }),
          window.ethereum.request({ method: "eth_getTransactionCount", params: [account.address, "latest"] }),
          window.ethereum.request({ method: "eth_blockNumber" }),
        ]);
        return {
          address: account.address,
          chain_id_hex: chainIdHex,
          balance_hex: balanceHex,
          tx_count_hex: txCountHex,
          block_number_hex: blockNumberHex,
          provider: "MetaMask"
        };
      }

      async function syncWalletAccount(accountKey, silent = false) {
        const account = (currentSummary?.blockchain?.accounts || []).find(item => item.account_key === accountKey);
        if (!account) {
          walletStatus("Wallet non trovato nella summary corrente.");
          return { ok: false, message: "Wallet non trovato." };
        }
        if (!silent) {
          walletStatus(`Sync in corso per ${account.label}...`);
        }
        try {
          const requestPayload = { account_key: accountKey };
          if (account.sync_capability === "browser_wallet") {
            requestPayload.browser_snapshot = await buildBrowserSnapshotForWallet(account);
          }
          const response = await fetch("/api/wallet/sync", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(requestPayload)
          });
          const payload = await response.json();
          if (!response.ok) {
            if (!silent) {
              walletStatus(payload.message || `Sync non riuscita per ${account.label}.`);
            }
            return { ok: false, message: payload.message || "Sync non riuscita." };
          }
          if (!silent) {
            walletStatus(payload.message || `Sync completata per ${account.label}.`);
          }
          await loadSummary();
          return { ok: true, message: payload.message || "Sync completata." };
        } catch (error) {
          if (!silent) {
            walletStatus(error?.message || `Errore durante la sync di ${account.label}.`);
          }
          return { ok: false, message: error?.message || "Errore di rete durante la sync." };
        }
      }

      async function syncAllWalletAccounts() {
        const accounts = currentSummary?.blockchain?.accounts || [];
        if (!accounts.length) {
          walletStatus("Non ci sono wallet registrati da sincronizzare.");
          return;
        }
        walletStatus("Sync wallet registrati in corso...");
        const results = [];
        for (const account of accounts) {
          if (account.sync_capability === "manual_only") {
            results.push({ label: account.label, ok: false, skipped: true });
            continue;
          }
          const result = await syncWalletAccount(account.account_key, true);
          results.push({ label: account.label, ...result });
        }
        const successCount = results.filter(item => item.ok).length;
        const skippedCount = results.filter(item => item.skipped).length;
        const failedCount = results.length - successCount - skippedCount;
        walletStatus(
          `Sync completata: ${successCount} ok, ${failedCount} errori, ${skippedCount} manual-only.`
        );
        await loadSummary();
      }

      function botStatusBadge(status) {
        return buildBadge(niceStatus(status), toneClass(status));
      }

      function setActiveTab(tabName) {
        document.querySelectorAll(".tab-btn").forEach(button => {
          button.classList.toggle("active", button.dataset.tab === tabName);
        });
        document.querySelectorAll(".tab-pane").forEach(pane => {
          pane.classList.toggle("active", pane.dataset.pane === tabName);
        });
        try {
          window.localStorage.setItem("deskActiveTab", tabName);
        } catch (error) {
          // Ignore storage issues in embedded browsers.
        }
      }

      const overviewPanels = ["alerts", "review", "risk", "performance", "trust", "onboarding", "system"];

      function setOverviewPanelCollapsed(panelName, collapsed, persist = true) {
        const panel = document.querySelector(`[data-overview-panel="${panelName}"]`);
        if (!panel) return;
        panel.classList.toggle("is-collapsed", collapsed);
        const button = panel.querySelector(".overview-toggle");
        if (button) {
          button.textContent = collapsed ? "Espandi" : "Compatta";
        }
        if (!persist) return;
        try {
          window.localStorage.setItem(`overviewPanel:${panelName}`, collapsed ? "1" : "0");
        } catch (error) {
          // Ignore storage issues in embedded browsers.
        }
      }

      function restoreOverviewPanels() {
        overviewPanels.forEach(panelName => {
          let collapsed = ["system", "trust", "onboarding"].includes(panelName);
          try {
            const saved = window.localStorage.getItem(`overviewPanel:${panelName}`);
            if (saved !== null) {
              collapsed = saved === "1";
            }
          } catch (error) {
            // Ignore storage issues in embedded browsers.
          }
          setOverviewPanelCollapsed(panelName, collapsed, false);
        });
      }

      function setAllOverviewPanels(collapsed) {
        overviewPanels.forEach(panelName => setOverviewPanelCollapsed(panelName, collapsed));
      }

      function jumpToOverviewPanel(panelId) {
        setActiveTab("overview");
        const node = document.getElementById(panelId);
        if (!node) return;
        node.scrollIntoView({ behavior: "smooth", block: "start" });
      }

      const journalPanels = ["signals", "events", "replay", "ledger", "failure"];

      function setJournalPanelCollapsed(panelName, collapsed, persist = true) {
        const panel = document.querySelector(`[data-journal-panel="${panelName}"]`);
        if (!panel) return;
        panel.classList.toggle("is-collapsed", collapsed);
        const button = panel.querySelector(".section-toggle");
        if (button) {
          button.textContent = collapsed ? "Espandi" : "Compatta";
        }
        if (!persist) return;
        try {
          window.localStorage.setItem(`journalPanel:${panelName}`, collapsed ? "1" : "0");
        } catch (error) {
          // Ignore storage issues in embedded browsers.
        }
      }

      function restoreJournalPanels() {
        journalPanels.forEach(panelName => {
          let collapsed = ["ledger", "failure"].includes(panelName);
          try {
            const saved = window.localStorage.getItem(`journalPanel:${panelName}`);
            if (saved !== null) {
              collapsed = saved === "1";
            }
          } catch (error) {
            // Ignore storage issues in embedded browsers.
          }
          setJournalPanelCollapsed(panelName, collapsed, false);
        });
      }

      function setAllJournalPanels(collapsed) {
        journalPanels.forEach(panelName => setJournalPanelCollapsed(panelName, collapsed));
      }

      function jumpToJournalPanel(panelId) {
        setActiveTab("journal");
        const node = document.getElementById(panelId);
        if (!node) return;
        node.scrollIntoView({ behavior: "smooth", block: "start" });
      }

      function getSelectedMarketSymbol(summary, fallbackSymbol = null) {
        try {
          const saved = window.localStorage.getItem("selectedMarketSymbol");
          if (saved && summary.symbols.some(item => item.symbol === saved)) {
            return saved;
          }
        } catch (error) {
          // Ignore storage issues in embedded browsers.
        }
        return fallbackSymbol || summary.symbols[0]?.symbol || null;
      }

      function setSelectedMarketSymbol(symbol) {
        try {
          window.localStorage.setItem("selectedMarketSymbol", symbol);
        } catch (error) {
          // Ignore storage issues in embedded browsers.
        }
      }

      async function updateProvider(event) {
        event.preventDefault();
        const provider = document.getElementById("provider-select").value;
        const statusNode = document.getElementById("provider-status");
        const button = document.getElementById("provider-submit");
        button.disabled = true;
        statusNode.textContent = "Aggiornamento in corso...";
        try {
          const response = await fetch("/api/provider", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ provider })
          });
          const payload = await response.json();
          if (!response.ok) {
            statusNode.textContent = payload.message || "Cambio provider non riuscito.";
          } else {
            statusNode.textContent = payload.message || "Provider aggiornato.";
            await loadSummary();
          }
        } catch (error) {
          statusNode.textContent = "Errore di rete durante il cambio provider.";
        } finally {
          button.disabled = false;
        }
      }

      async function updateManualImport(event) {
        event.preventDefault();
        const statusNode = document.getElementById("manual-import-status");
        const button = document.getElementById("manual-import-submit");
        button.disabled = true;
        statusNode.textContent = "Import in corso...";
        try {
          const response = await fetch("/api/import/manual", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
              account_label: document.getElementById("import-account-label").value,
              provider_key: document.getElementById("import-provider-key").value,
              format: document.getElementById("import-format").value,
              base_currency: document.getElementById("import-base-currency").value,
              notes: document.getElementById("import-notes").value,
              raw_text: document.getElementById("import-payload").value
            })
          });
          const payload = await response.json();
          if (!response.ok) {
            statusNode.textContent = payload.message || "Import non riuscito.";
          } else {
            statusNode.textContent = payload.message || "Import completato.";
            await loadSummary();
          }
        } catch (error) {
          statusNode.textContent = "Errore durante l'import manuale.";
        } finally {
          button.disabled = false;
        }
      }

      async function saveDailyReview(event) {
        event.preventDefault();
        const statusNode = document.getElementById("review-status");
        const button = document.getElementById("review-submit");
        button.disabled = true;
        statusNode.textContent = "Salvataggio review in corso...";
        try {
          const response = await fetch("/api/review/note", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
              verdict: document.getElementById("review-verdict").value,
              note: document.getElementById("review-note").value
            })
          });
          const payload = await response.json();
          if (!response.ok) {
            statusNode.textContent = payload.message || "Salvataggio review non riuscito.";
          } else {
            statusNode.textContent = payload.message || "Review salvata.";
            await loadSummary();
          }
        } catch (error) {
          statusNode.textContent = "Errore durante il salvataggio della review.";
        } finally {
          button.disabled = false;
        }
      }

      async function deleteImportedAccount(accountKey, label) {
        if (!window.confirm(`Rimuovere l'account importato "${label}" dalla alpha?`)) {
          return;
        }
        const statusNode = document.getElementById("manual-import-status");
        statusNode.textContent = `Rimozione di ${label} in corso...`;
        try {
          const response = await fetch("/api/import/delete", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ account_key: accountKey })
          });
          const payload = await response.json();
          if (!response.ok) {
            statusNode.textContent = payload.message || "Rimozione non riuscita.";
          } else {
            statusNode.textContent = payload.message || "Account importato rimosso.";
            await loadSummary();
          }
        } catch (error) {
          statusNode.textContent = "Errore durante la rimozione dell'account importato.";
        }
      }

      function openInfo(text) {
        const modal = document.getElementById("info-modal");
        document.getElementById("modal-body").textContent = text;
        modal.classList.add("open");
        modal.setAttribute("aria-hidden", "false");
      }

      function closeInfo() {
        const modal = document.getElementById("info-modal");
        modal.classList.remove("open");
        modal.setAttribute("aria-hidden", "true");
      }

      async function loadSummary() {
        const response = await fetch("/api/summary");
        const summary = await response.json();
        currentSummary = summary;

        const openPositions = summary.account.open_positions;
        const focusSymbol = summary.symbols.find(item => {
          const code = String(item.analysis?.status || "");
          return ["ENTRATA_ESEGUITA", "IN_POSIZIONE", "OSSERVAZIONE", "BLOCCATO"].includes(code);
        }) || summary.symbols[0];
        const reviewVerdictLabels = {
          setup_chiari: "Setup chiari",
          bot_troppo_cauto: "Bot troppo cauto",
          costi_pesanti: "Costi pesanti",
          da_rivedere: "Da rivedere"
        };
        const selectedMarketSymbol = getSelectedMarketSymbol(summary, focusSymbol?.symbol);
        const selectedMarket = summary.symbols.find(item => item.symbol === selectedMarketSymbol) || summary.symbols[0] || null;
        setMoneyCurrency(summary.account.portfolio_currency || "EUR");

        document.getElementById("hero-copy").textContent =
          `${summary.strategy.description} Oggi il desk e ${niceStatus(summary.risk.guardrail_status).toLowerCase()}, il bot e ${niceStatus(summary.bot.status).toLowerCase()} e stiamo lavorando con ${pct(summary.account.current_exposure_pct, 2)} di capitale esposto sul venue ${summary.account_center.operational_account.provider_label}.`;

        document.getElementById("hero-chips").innerHTML = `
          <span class="chip">Modalita ${summary.bot.mode}</span>
          <span class="chip">Dati ${summary.bot.data_mode}</span>
          <span class="chip">Venue ${summary.account_center.operational_account.provider_label}</span>
          <span class="chip">Fee profile ${summary.provider.current.label}</span>
          <span class="chip">Guard rail ${niceStatus(summary.risk.guardrail_status)}</span>
          <span class="chip">${summary.experiment.drift_detected ? "Config drift" : "Baseline stabile"}</span>
          <span class="chip">${summary.capital_plan.recurring_enabled ? `Versamento ${eur(summary.capital_plan.amount_eur)} ${summary.capital_plan.frequency}` : "Versamento manuale"}</span>
          <span class="chip">Candles ${summary.strategy.candles_interval_minutes}m</span>
          <span class="chip">Ultimo ciclo ${summary.bot.last_cycle_at || "n/d"}</span>
        `;

        document.getElementById("hero-ops-grid").innerHTML = `
          <div class="card">
            <div class="label-row">
              <div class="label-group">
                <strong>Stato desk</strong>
                ${infoButton("Riassunto immediato dello stato operativo del desk, utile prima ancora di entrare nella Panoramica.")}
              </div>
            </div>
            <div class="value ${toneClass(summary.risk.guardrail_status)}" style="margin-top:8px; font-size:18px; font-weight:700;">${niceStatus(summary.risk.guardrail_status)}</div>
            <div class="sub">Bot ${niceStatus(summary.bot.status)} | ciclo ${summary.bot.last_cycle_at || "n/d"}</div>
          </div>
          <div class="card">
            <div class="label-row">
              <div class="label-group">
                <strong>Focus oggi</strong>
                ${infoButton("Il simbolo o contesto piu interessante da leggere ora, senza aprire subito tutte le sezioni sotto.")}
              </div>
            </div>
            <div class="value mono ${focusSymbol ? toneClass(focusSymbol.analysis?.status) : "watch"}" style="margin-top:8px; font-size:18px; font-weight:700;">${focusSymbol ? focusSymbol.symbol : "n/d"}</div>
            <div class="sub">${focusSymbol?.analysis?.reason || "Nessun focus dominante."}</div>
          </div>
          <div class="card">
            <div class="label-row">
              <div class="label-group">
                <strong>Review</strong>
                ${infoButton("Riprende il verdetto della giornata senza costringerti ad aprire subito la Daily Review completa.")}
              </div>
            </div>
            <div class="value ${summary.daily_review.annotation?.verdict === "setup_chiari" ? "good" : "watch"}" style="margin-top:8px; font-size:18px; font-weight:700;">${reviewVerdictLabels[summary.daily_review.annotation?.verdict || "da_rivedere"]}</div>
            <div class="sub">${summary.daily_review.annotation?.note || "Nessuna nota review salvata."}</div>
          </div>
          <div class="card">
            <div class="label-row">
              <div class="label-group">
                <strong>Prossimo passo</strong>
                ${infoButton("Il passo piu sensato da fare adesso, utile soprattutto quando stai usando o mostrando l'alpha in modo guidato.")}
              </div>
            </div>
            <div class="value mono ${summary.alpha_onboarding.readiness_label.includes("DESIGN") ? "good" : "watch"}" style="margin-top:8px; font-size:18px; font-weight:700;">${summary.alpha_onboarding.readiness_label}</div>
            <div class="sub">${summary.alpha_onboarding.next_steps[0]?.title || "Continua a raccogliere dati."}</div>
          </div>
        `;
        setBalancedGridColumns("hero-ops-grid", 4, 4);

        document.getElementById("kpis").innerHTML = `
          <div class="kpi">
            <div class="label-row">
              <div class="label-group">
                <strong>Cassa disponibile</strong>
                ${infoButton("E la cassa ancora libera nella valuta base del desk, non impegnata in posizioni aperte.")}
              </div>
            </div>
            <div class="value mono">${eur(summary.account.cash)}</div>
            <div class="sub">Valuta portafoglio: ${summary.account.portfolio_currency}</div>
          </div>
          <div class="kpi">
            <div class="label-row">
              <div class="label-group">
                <strong>Equity stimata</strong>
                ${infoButton("Cassa disponibile piu PnL aperto sulle posizioni ancora in corso.")}
              </div>
            </div>
            <div class="value mono">${eur(summary.account.equity)}</div>
            <div class="sub">Capitale versato: ${eur(summary.account.contributed_capital)}</div>
          </div>
          <div class="kpi">
            <div class="label-row">
              <div class="label-group">
                <strong>Profitto netto</strong>
                ${infoButton("Equity attuale meno capitale totale versato nel tempo. Serve per separare i risultati del trading dai versamenti periodici.")}
              </div>
            </div>
            <div class="value mono ${Number(summary.account.net_profit_after_contributions) >= 0 ? "good" : "bad"}">${eur(summary.account.net_profit_after_contributions)}</div>
            <div class="sub">Realizzato ${eur(summary.account.realized_pnl)} | aperto ${eur(summary.account.unrealized_pnl)}</div>
          </div>
          <div class="kpi">
            <div class="label-row">
              <div class="label-group">
                <strong>Fee totali</strong>
                ${infoButton("Somma di tutte le commissioni simulate pagate in ingresso e in uscita.")}
              </div>
            </div>
            <div class="value mono">${eur(summary.account.fees_total)}</div>
            <div class="sub">Ingresso ${eur(summary.account.fees_entry_total)} | uscita ${eur(summary.account.fees_exit_total)}</div>
          </div>
        `;
        setBalancedGridColumns("kpis", 4, 4);

        document.getElementById("provider-current").innerHTML = `
          <div class="provider-row">
            <div class="label-group">
              <strong>Fee profile attivo: ${summary.provider.current.label}</strong>
              ${infoButton("Questo e il profilo commissionale che il motore sta usando adesso per i conti del paper trading. Il venue operativo del collector e mostrato separatamente." )}
            </div>
            ${buildBadge("Taker " + pct(summary.provider.current.taker_fee_rate * 100, 2), "watch")}
          </div>
          <p style="margin-top:8px;">${summary.provider.current.description}</p>
          <div class="chips" style="margin-top:12px;">
            <span class="chip">Maker ${pct(summary.provider.current.maker_fee_rate * 100, 2)}</span>
            <span class="chip">Taker ${pct(summary.provider.current.taker_fee_rate * 100, 2)}</span>
            <span class="chip">Feed dati ${summary.account_center.operational_account.provider_label}</span>
            <span class="chip">Paper ${summary.provider.current.paper_supported ? "si" : "no"}</span>
            <span class="chip">Shadow ${summary.provider.current.shadow_supported ? "si" : "no"}</span>
          </div>
          <p style="margin-top:10px;">${summary.provider.current.notes}</p>
        `;

        const select = document.getElementById("provider-select");
        select.innerHTML = summary.provider.available.map(item => `
          <option value="${item.key}" ${item.key === summary.provider.current.key ? "selected" : ""}>
            ${item.label} | maker ${pct(item.maker_fee_rate * 100, 2)} | taker ${pct(item.taker_fee_rate * 100, 2)}
          </option>
        `).join("");
        document.getElementById("import-provider-key").innerHTML = summary.provider.available.map(item => `
          <option value="${item.key}">${item.label}</option>
        `).join("");
        document.getElementById("wallet-key").innerHTML = summary.blockchain.wallets.map(item => `
          <option value="${item.key}">${item.label}</option>
        `).join("");
        document.getElementById("wallet-chain-key").innerHTML = summary.blockchain.chains.map(item => `
          <option value="${item.key}">${item.label} | ${item.ecosystem}</option>
        `).join("");
        document.getElementById("wallet-venue-key").innerHTML = summary.blockchain.venues.map(item => `
          <option value="${item.key}">${item.label} | ${item.execution_style}</option>
        `).join("");

        document.getElementById("provider-grid").innerHTML = `
          <div class="card">
            <div class="label-row">
              <div class="label-group">
                <strong>Ordine paper per trade</strong>
                ${infoButton("Taglia standard dell'operazione simulata. In questa versione il motore usa un importo fisso nella valuta base del desk per ogni ingresso.")}
              </div>
            </div>
            <div class="value mono" style="margin-top:8px; font-size:26px; font-weight:700;">${eur(summary.strategy.paper_trade_size)}</div>
            <p style="margin-top:6px;">Assunzione attuale per rendere leggibili fee e PnL sulla base paper da ${eur(summary.account.starting_balance || summary.account.contributed_capital)}.</p>
          </div>
          <div class="card">
            <div class="label-row">
              <div class="label-group">
                <strong>Scope provider alpha</strong>
                ${infoButton("Nella alpha usiamo Hyperliquid come venue operativo di default. Gli altri provider oggi servono per confronti commissioni, storico o import manuale concierge, non per live trading reale." )}
              </div>
            </div>
            <p>Fee model ${summary.provider.current.fee_model} | market data ${summary.provider.current.market_data ? "si" : "no"} | import ${summary.provider.current.import_supported ? "si" : "no"}</p>
            <p style="margin-top:10px;">${summary.provider.current.notes}</p>
          </div>
          <div class="card">
            <div class="label-row">
              <div class="label-group">
                <strong>Setup perps alpha</strong>
                ${infoButton("Configurazione operativa del motore per Hyperliquid perps: leva base, modalita margine, policy di esecuzione e uscite reduce-only.")}
              </div>
            </div>
            <div class="value mono" style="margin-top:8px; font-size:26px; font-weight:700;">${num(summary.strategy.perps_default_leverage, 2)}x</div>
            <p style="margin-top:6px;">${summary.strategy.perps_margin_mode} | ${summary.strategy.perps_execution_policy} | short ${summary.strategy.short_entries_enabled ? "attivo" : "off"}</p>
            <p style="margin-top:10px;">Uscite reduce-only ${summary.strategy.reduce_only_exits_enabled ? "attive" : "off"}.</p>
          </div>
          <div class="card">
            <div class="label-row">
              <div class="label-group">
                <strong>Round trip stimato</strong>
                ${infoButton("Costo teorico di ingresso + uscita se la simulazione continua a comportarsi come taker sul notional standard del paper trade.")}
              </div>
            </div>
            <div class="value mono" style="margin-top:8px; font-size:26px; font-weight:700;">${eur(summary.strategy.paper_trade_size * summary.provider.current.taker_fee_rate * 2)}</div>
            <p style="margin-top:6px;">Stimato su ${eur(summary.strategy.paper_trade_size)} con doppio passaggio taker.</p>
          </div>
        `;
        setBalancedGridColumns("provider-grid", 4, 4);

        document.getElementById("daily-review-summary").textContent = summary.daily_review.summary;
        document.getElementById("daily-review-highlights").innerHTML = summary.daily_review.highlights.map(item =>
          alertCard(item.title, item.body, item.tone || "watch", "")
        ).join("");
        setBalancedGridColumns("daily-review-highlights", summary.daily_review.highlights.length, 3);
        document.getElementById("daily-review-rules").innerHTML = summary.daily_review.rule_checks.map(item => `
          <div class="card">
            <div class="label-row">
              <div class="label-group">
                <strong>${item.label}</strong>
                ${infoButton("Questa regola e entrata nella review giornaliera per mostrarti quali vincoli o stati hanno contato davvero oggi.")}
              </div>
            </div>
            <div class="value mono ${item.tone || ""}" style="margin-top:8px; font-size:26px; font-weight:700;">${item.value}</div>
          </div>
        `).join("");
        setBalancedGridColumns("daily-review-rules", summary.daily_review.rule_checks.length, 4);
        document.getElementById("daily-review-targets").innerHTML = summary.daily_review.review_targets.map(item => `
          <div class="card">
            <div class="label-row">
              <div class="label-group">
                <strong>${item.symbol}</strong>
                ${infoButton("Target di review suggerito dalla giornata: serve a capire quale simbolo o setup merita attenzione prima degli altri.")}
              </div>
            </div>
            <p style="margin-top:8px;">${item.reason}</p>
            <p class="muted" style="margin-top:8px;">${item.next_condition || "Nessuna condizione aggiuntiva registrata."}</p>
          </div>
        `).join("");
        setBalancedGridColumns("daily-review-targets", Math.max(summary.daily_review.review_targets.length, 1), 3);
        document.getElementById("daily-review-prompt").textContent = summary.daily_review.closing_prompt;
        document.getElementById("review-verdict").value = summary.daily_review.annotation.verdict || "da_rivedere";
        document.getElementById("review-note").value = summary.daily_review.annotation.note || "";
        document.getElementById("review-updated-at").textContent = summary.daily_review.annotation.updated_at || "non salvata";
        document.getElementById("overview-review-count").textContent = `${summary.daily_review.highlights.length + summary.daily_review.review_targets.length} focus`;

        document.getElementById("onboarding-summary").textContent = summary.alpha_onboarding.summary;
        document.getElementById("onboarding-progress").innerHTML = `
          <div class="card">
            <div class="label-row">
              <div class="label-group">
                <strong>Readiness alpha</strong>
                ${infoButton("Stato sintetico della maturita della alpha, utile per capire se la build e pronta solo per demo interne o gia per design partner assistiti.")}
              </div>
            </div>
            <div class="value mono ${summary.alpha_onboarding.readiness_label.includes("DESIGN") ? "good" : "watch"}" style="margin-top:8px; font-size:24px; font-weight:700;">${summary.alpha_onboarding.readiness_label}</div>
            <p style="margin-top:6px;">${summary.alpha_onboarding.completed_steps} step completati su ${summary.alpha_onboarding.total_steps}</p>
          </div>
          <div class="card">
            <div class="label-row">
              <div class="label-group">
                <strong>Promise alpha</strong>
                ${infoButton("La promessa dell'alpha non e performance magica: e chiarezza operativa, costi leggibili e review rapida.")}
              </div>
            </div>
            <p style="margin-top:8px;">Capire cosa e successo, perche e successo o non e successo e quanto e costato davvero, prima di parlare di live execution.</p>
          </div>
        `;
        setBalancedGridColumns("onboarding-progress", 2, 2);
        document.getElementById("onboarding-checklist").innerHTML = summary.alpha_onboarding.checklist.map(item => `
          <div class="card">
            <div class="label-row">
              <div class="label-group">
                <strong>${item.label}</strong>
                ${infoButton("Checklist alpha: ogni riga mostra se quel tassello e gia pronto o se richiede ancora dati o lavoro.")}
              </div>
            </div>
            <div class="value mono ${item.status === "DONE" ? "good" : "watch"}" style="margin-top:8px; font-size:20px; font-weight:700;">${item.status === "DONE" ? "Pronto" : item.status === "NEXT" ? "Prossimo" : "In attesa"}</div>
            <p style="margin-top:6px;">${item.detail}</p>
          </div>
        `).join("");
        setBalancedGridColumns("onboarding-checklist", summary.alpha_onboarding.checklist.length, 3);
        document.getElementById("onboarding-next-steps").innerHTML = summary.alpha_onboarding.next_steps.map(item => `
          <div class="mini-row">
            <strong>${item.title}</strong>
            <p class="muted">${item.detail}</p>
          </div>
        `).join("");
        document.getElementById("overview-onboarding-count").textContent = `${summary.alpha_onboarding.completed_steps} / ${summary.alpha_onboarding.total_steps}`;

        document.getElementById("mode-grid").innerHTML = summary.modes.map(item => `
          <div class="card">
            <div class="label-row">
              <div class="label-group">
                <strong>${item.label}</strong>
                ${infoButton("Le modalita sono sempre separate in modo esplicito: paper, shadow e live non devono mai sembrare la stessa cosa.")}
              </div>
            </div>
            <div class="value mono ${item.enabled ? (item.active ? "good" : "") : "bad"}" style="margin-top:8px; font-size:26px; font-weight:700;">${item.enabled ? (item.active ? "Attiva" : "Disponibile") : "Disabilitata"}</div>
            <p style="margin-top:6px;">${item.description}</p>
          </div>
        `).join("");
        setBalancedGridColumns("mode-grid", summary.modes.length, 3);
        document.getElementById("capability-grid").innerHTML = `
          <div class="card">
            <div class="label-row">
              <div class="label-group">
                <strong>Capability provider</strong>
                ${infoButton("Matrice minima della alpha: dice cosa il provider attuale sa fare davvero dentro questo prodotto.")}
              </div>
            </div>
            <div class="chips" style="margin-top:10px;">
              ${buildBadge(`Market data ${summary.provider.current.market_data ? "si" : "no"}`, summary.provider.current.market_data ? "ok" : "bad")}
              ${buildBadge(`Paper ${summary.provider.current.paper_supported ? "si" : "no"}`, summary.provider.current.paper_supported ? "ok" : "bad")}
              ${buildBadge(`Shadow ${summary.provider.current.shadow_supported ? "si" : "no"}`, summary.provider.current.shadow_supported ? "ok" : "bad")}
              ${buildBadge(`Live ${summary.provider.current.live_supported ? "si" : "no"}`, summary.provider.current.live_supported ? "ok" : "bad")}
              ${buildBadge(`Short ${summary.provider.current.short_supported ? "si" : "no"}`, summary.provider.current.short_supported ? "ok" : "bad")}
              ${buildBadge(`Import ${summary.provider.current.import_supported ? "si" : "no"}`, summary.provider.current.import_supported ? "ok" : "watch")}
            </div>
          </div>
          <div class="card">
            <div class="label-row">
              <div class="label-group">
                <strong>Trust UX</strong>
                ${infoButton("Principi base della alpha: nessuna azione opaca, ogni blocco e spiegato e le modalita sono sempre separate in modo leggibile.")}
              </div>
            </div>
            <p>Nessuna azione opaca, ogni blocco ha un motivo, paper/shadow/live sono visivamente separati e ogni vista risponde a una domanda forte.</p>
          </div>
        `;
        setBalancedGridColumns("capability-grid", 2, 2);
        document.getElementById("cost-grid").innerHTML = `
          <div class="card">
            <div class="label-row">
              <div class="label-group">
                <strong>Cost attribution</strong>
                ${infoButton("Decompone il costo operativo della alpha in fee esplicite, spread stimato e slippage stimato.")}
              </div>
            </div>
            <div class="value mono" style="margin-top:8px; font-size:26px; font-weight:700;">${eur(summary.cost_attribution.estimated_total_cost_eur)}</div>
            <p style="margin-top:6px;">Fee ${eur(summary.cost_attribution.fee_total_eur)} | Spread stimato ${eur(summary.cost_attribution.spread_cost_estimate_eur)} | Slippage stimato ${eur(summary.cost_attribution.slippage_cost_estimate_eur)}</p>
          </div>
          <div class="card">
            <div class="label-row">
              <div class="label-group">
                <strong>Net edge dopo costi</strong>
                ${infoButton("Confronta il profitto realizzato con il costo operativo stimato per capire se l'edge resiste davvero dopo le frizioni.")}
              </div>
            </div>
            <div class="value mono ${Number(summary.account.realized_pnl - summary.cost_attribution.estimated_total_cost_eur) >= 0 ? "good" : "bad"}" style="margin-top:8px; font-size:26px; font-weight:700;">${eur(summary.account.realized_pnl - summary.cost_attribution.estimated_total_cost_eur)}</div>
            <p style="margin-top:6px;">Realizzato ${eur(summary.account.realized_pnl)} | costo stimato ${eur(summary.cost_attribution.estimated_total_cost_eur)}</p>
          </div>
        `;
        setBalancedGridColumns("cost-grid", 2, 2);
        document.getElementById("workflow-grid").innerHTML = summary.supported_workflows.map(item => `
          <div class="card">
            <div class="label-row">
              <div class="label-group">
                <strong>${item.title}</strong>
                ${infoButton("Workflow dichiarato ufficialmente nella alpha, per evitare aspettative implicite o funzioni 'magiche' non realmente supportate.")}
              </div>
            </div>
            <div class="value mono ${item.status === "ATTIVO" ? "good" : "watch"}" style="margin-top:8px; font-size:20px; font-weight:700;">${item.status}</div>
            <p style="margin-top:6px;">${item.description}</p>
          </div>
        `).join("");
        setBalancedGridColumns("workflow-grid", summary.supported_workflows.length, 4);
        document.getElementById("limitations-list").innerHTML = summary.known_limitations.map(item => `
          <div class="badge" style="margin:0 8px 8px 0;">${item}</div>
        `).join("");
        document.getElementById("overview-trust-count").textContent = `${summary.supported_workflows.length} workflow`;
        document.getElementById("account-center-operational").innerHTML = `
          <div class="card">
            <div class="label-row">
              <div class="label-group">
                <strong>Desk operativo</strong>
                ${infoButton("E il desk locale nativo: il cuore del control plane che gira sul venue operativo selezionato e produce review, replay e guard rail in tempo reale.")}
              </div>
            </div>
            <div class="value mono good" style="margin-top:8px; font-size:26px; font-weight:700;">${summary.account_center.operational_account.provider_label}</div>
            <p style="margin-top:6px;">Modalita ${summary.account_center.operational_account.mode} | ultimo ciclo ${summary.account_center.operational_account.last_cycle_at || "n/d"}</p>
          </div>
          <div class="card">
            <div class="label-row">
              <div class="label-group">
                <strong>Coverage locale</strong>
                ${infoButton("Dati raccolti dal desk operativo locale per alimentare decisioni, review e audit trail.")}
              </div>
            </div>
            <div class="value mono" style="margin-top:8px; font-size:26px; font-weight:700;">${summary.account_center.operational_account.order_book_records}</div>
            <p style="margin-top:6px;">Snapshot order book | trade pubblici ${summary.account_center.operational_account.public_trade_records}</p>
          </div>
          <div class="card">
            <div class="label-row">
              <div class="label-group">
                <strong>Layer blockchain</strong>
                ${infoButton("Stato sintetico del layer blockchain: quanti wallet watch abbiamo e quanti setup sono gia pronti per venue on-chain piu evolute.")}
              </div>
            </div>
            <div class="value mono ${summary.blockchain.accounts.length ? "good" : "watch"}" style="margin-top:8px; font-size:26px; font-weight:700;">${summary.blockchain.accounts.length}</div>
            <p style="margin-top:6px;">Wallet registrati | execution-ready ${summary.blockchain.execution_ready_count}</p>
          </div>
        `;
        setBalancedGridColumns("account-center-operational", 3, 3);
        document.getElementById("account-center-table").innerHTML = [
          `
            <tr>
              <td><strong>${summary.account_center.operational_account.label}</strong><div class="muted">Provider operativo</div></td>
              <td>${summary.account_center.operational_account.provider_label}</td>
              <td>${buildBadge("Nativo", "ok")}</td>
              <td>book ${summary.account_center.operational_account.order_book_records} | trade ${summary.account_center.operational_account.public_trade_records}</td>
              <td class="mono">${summary.account_center.operational_account.last_cycle_at || "n/d"}</td>
              <td><span class="muted">Gestito dal desk</span></td>
            </tr>
          `,
          ...(summary.account_center.imported_accounts || []).map(item => `
            <tr>
              <td><strong>${item.label}</strong><div class="muted">${item.account_key}</div></td>
              <td>${item.provider_label || item.provider_key}</td>
              <td>${buildBadge("Import", "watch")}</td>
              <td>${item.event_count} eventi | ${item.trade_count} trade | fee ${eur(item.fee_total)}</td>
              <td class="mono">${item.last_import_at || item.updated_at || "n/d"}</td>
              <td><button class="secondary" type="button" onclick='deleteImportedAccount(${JSON.stringify(String(item.account_key))}, ${JSON.stringify(String(item.label))})'>Rimuovi</button></td>
            </tr>
          `)
        ].join("");
        document.getElementById("blockchain-summary").textContent = summary.blockchain.summary;
        document.getElementById("blockchain-operational").innerHTML = `
          <div class="card">
            <div class="label-row">
              <div class="label-group">
                <strong>Stack consigliato</strong>
                ${infoButton("Riassume la tesi operativa: MetaMask per wallet UX, venue on-chain dedicata per automazione vera.")}
              </div>
            </div>
            <div class="value mono ${summary.blockchain.accounts.length ? "good" : "watch"}" style="margin-top:8px; font-size:22px; font-weight:700;">${summary.blockchain.headline}</div>
            <p style="margin-top:6px;">${summary.blockchain.mode_note}</p>
          </div>
          <div class="card">
            <div class="label-row">
              <div class="label-group">
                <strong>Venue primaria</strong>
                ${infoButton("Venue on-chain che considero la piu adatta per la futura execution automatica del progetto.")}
              </div>
            </div>
            <div class="value mono" style="margin-top:8px; font-size:24px; font-weight:700;">${summary.blockchain.venues.find(item => item.key === summary.blockchain.primary_venue_key)?.label || "Hyperliquid"}</div>
            <p style="margin-top:6px;">Wallet watch ${summary.blockchain.wallet_watch_count} | execution-ready ${summary.blockchain.execution_ready_count}</p>
          </div>
          <div class="card">
            <div class="label-row">
              <div class="label-group">
                <strong>Sync wallet</strong>
                ${infoButton("Conta quanti wallet hanno gia uno snapshot valido e quanti richiedono ancora attenzione o sync manuale.")}
              </div>
            </div>
            <div class="value mono ${summary.blockchain.synced_count ? "good" : "watch"}" style="margin-top:8px; font-size:24px; font-weight:700;">${summary.blockchain.synced_count}</div>
            <p style="margin-top:6px;">synced | pending ${summary.blockchain.sync_pending_count} | error ${summary.blockchain.sync_error_count}</p>
          </div>
        `;
        setBalancedGridColumns("blockchain-operational", 3, 3);
        document.getElementById("blockchain-recommended").innerHTML = summary.blockchain.recommended_stack.map(item => `
          <div class="card">
            <div class="label-row">
              <div class="label-group">
                <strong>${item.title}</strong>
                ${infoButton("Scelta consigliata per integrare blockchain senza confondere wallet, venue e automazione.")}
              </div>
            </div>
            <div class="value mono" style="margin-top:8px; font-size:22px; font-weight:700;">${item.choice}</div>
            <p style="margin-top:6px;">${item.reason}</p>
          </div>
        `).join("");
        setBalancedGridColumns("blockchain-recommended", summary.blockchain.recommended_stack.length, 2);
        document.getElementById("blockchain-required-inputs").innerHTML = summary.blockchain.required_inputs.length
          ? summary.blockchain.required_inputs.map(item => `
              <div class="card">
                <div class="label-row">
                  <div class="label-group">
                    <strong>${item.label}</strong>
                    ${infoButton("Input o setup che manca ancora per portare il layer blockchain verso shadow o future execution.") }
                  </div>
                </div>
                <p style="margin-top:8px;">${item.detail}</p>
              </div>
            `).join("")
          : `
              <div class="card">
                <div class="label-row">
                  <div class="label-group">
                    <strong>Stack blockchain pronto per la fase successiva</strong>
                    ${infoButton("Quando questa lista e vuota, vuol dire che il layer blockchain ha gia i prerequisiti minimi per passare a shadow piu serio o venue-specific execution prep.")}
                  </div>
                </div>
                <p style="margin-top:8px;">Hai gia i prerequisiti minimi registrati: wallet, venue e almeno un setup adatto a preparare automazione futura.</p>
              </div>
            `;
        setBalancedGridColumns("blockchain-required-inputs", Math.max(summary.blockchain.required_inputs.length, 1), 2);
        document.getElementById("wallet-account-table").innerHTML = summary.blockchain.accounts.length
          ? summary.blockchain.accounts.map(item => `
              <tr>
                <td><strong>${item.label}</strong><div class="muted mono">${item.address}</div></td>
                <td>${item.venue_label}<div class="muted">${item.venue_execution_style}</div></td>
                <td>${item.chain_label}<div class="muted">${item.wallet_label}</div></td>
                <td>${buildBadge(item.mode, item.mode === "WATCH" ? "watch" : "ok")}</td>
                <td>
                  <div style="display:flex; flex-wrap:wrap; gap:6px; align-items:center;">
                    ${item.execution_ready ? buildBadge("Automation-ready", "ok") : item.shadow_ready ? buildBadge("Shadow-ready", "watch") : buildBadge("Watch-only", "bad")}
                    ${buildBadge(
                      item.sync_status === "SYNCED" ? "Synced" : item.sync_status === "ERROR" ? "Errore sync" : "Pending sync",
                      item.sync_status === "SYNCED" ? "ok" : item.sync_status === "ERROR" ? "bad" : "watch"
                    )}
                  </div>
                  <div class="muted" style="margin-top:6px;">${item.sync_summary}</div>
                  <div class="muted" style="margin-top:4px;">${item.last_sync_at ? `ultimo sync ${item.last_sync_at}` : item.sync_capability_note}</div>
                  ${item.sync_error ? `<div class="muted" style="margin-top:4px; color: var(--bad);">${item.sync_error}</div>` : ""}
                </td>
                <td>
                  <div style="display:flex; flex-wrap:wrap; gap:8px;">
                    <button class="secondary" type="button" onclick='syncWalletAccount(${JSON.stringify(String(item.account_key))})'>Sync</button>
                    <button class="secondary" type="button" onclick='deleteWalletAccount(${JSON.stringify(String(item.account_key))}, ${JSON.stringify(String(item.label))})'>Rimuovi</button>
                  </div>
                </td>
              </tr>
            `).join("")
          : renderEmpty("Ancora nessun wallet registrato nel layer blockchain.", 6);
        document.getElementById("import-schema").innerHTML = summary.account_center.manual_import_schema.map(item => `
          <div class="card">
            <div class="label-row">
              <div class="label-group">
                <strong>${item}</strong>
                ${infoButton("Campo del contratto minimo di import alpha.")}
              </div>
            </div>
            <p style="margin-top:6px;">Campo supportato dal parser CSV/JSON della alpha.</p>
          </div>
        `).join("");
        setBalancedGridColumns("import-schema", summary.account_center.manual_import_schema.length, 4);
        document.getElementById("imported-account-insights").innerHTML = summary.account_center.imported_accounts.length
          ? summary.account_center.imported_accounts.map(item => `
              <div class="card">
                <div class="label-row">
                  <div class="label-group">
                    <strong>${item.label}</strong>
                    ${infoButton("Card sintetica dell'account importato: mette subito in vista fee, flussi e volume dei trade letti.")}
                  </div>
                </div>
                <div class="value mono" style="margin-top:8px; font-size:24px; font-weight:700;">${item.trade_count} trade</div>
                <p style="margin-top:6px;">Provider ${item.provider_label || item.provider_key} | fee ${eur(item.fee_total)} | volume trade ${eur(item.trade_notional_total)}</p>
                <p class="muted" style="margin-top:8px;">Net transfer ${eur(item.net_transfer_total)} | flow buy/sell ${eur(item.net_trade_flow_total)} | ultimo evento ${item.last_event_time || "n/d"}</p>
              </div>
            `).join("")
          : `
              <div class="card">
                <div class="label-row">
                  <div class="label-group">
                    <strong>Nessun account importato</strong>
                    ${infoButton("Quando importerai un account esterno, qui compariranno i numeri minimi per review e confronto senza integrazione live.")}
                  </div>
                </div>
                <p style="margin-top:8px;">Usa i template CSV o JSON per popolare un account demo e verificare il workflow di review multi-account.</p>
              </div>
            `;
        setBalancedGridColumns("imported-account-insights", Math.max(summary.account_center.imported_accounts.length, 1), 3);
        document.getElementById("import-events").innerHTML = summary.account_center.recent_import_events.length
          ? summary.account_center.recent_import_events.map(item => `
              <tr>
                <td class="mono">${item.event_time}</td>
                <td><strong>${item.label}</strong><div class="muted">${item.provider_label || item.provider_key}</div></td>
                <td>${buildBadge(item.event_type, item.event_type === "trade" ? "ok" : "watch")}</td>
                <td>${item.symbol ? `${item.symbol}${item.side ? ` ${item.side}` : ""}` : (item.event_type === "deposit" ? "Deposito" : item.event_type === "withdrawal" ? "Prelievo" : item.event_type === "fee" ? "Fee" : "Evento importato")}<div class="muted">${item.raw.notes || "Nessuna nota"}</div></td>
                <td class="mono">${Number(item.fee || 0) > 0 ? `${eur(item.notional)} | fee ${eur(item.fee)}` : eur(item.notional)}</td>
              </tr>
            `).join("")
          : renderEmpty("Ancora nessuna attivita importata da account esterni.", 5);

        const alertCards = [];
        if (summary.risk.guardrail_status === "HARD_STOP") {
          alertCards.push(
            alertCard(
              "Desk in hard stop",
              summary.risk.kill_switch_reason || "Il risk manager ha bloccato nuove entrate.",
              "bad",
              "Nuove entrate sospese finche non resettamo la sessione o cambia la giornata operativa."
            )
          );
        } else if (summary.risk.guardrail_status === "COOLDOWN") {
          alertCards.push(
            alertCard(
              "Cooldown attivo",
              "Il desk e in pausa temporanea dopo una chiusura recente.",
              "watch",
              `Ripartenza prevista: ${summary.risk.cooldown_until || "n/d"}`
            )
          );
        } else {
          alertCards.push(
            alertCard(
              "Desk operativo",
              "Le nuove entrate sono abilitate e il sistema puo continuare a lavorare sui prossimi setup.",
              "ok",
            `Venue ${summary.account_center.operational_account.provider_label} | bot ${niceStatus(summary.bot.status)}`
          )
        );
        }
        if (focusSymbol) {
          const focusAnalysis = focusSymbol.analysis || {};
          const focusDetails = focusAnalysis.details || {};
          alertCards.push(
            alertCard(
              `Focus ${focusSymbol.symbol}`,
              focusAnalysis.reason || "Sto aspettando dati piu chiari sul simbolo.",
              toneClass(focusAnalysis.status),
              focusDetails.prossima_condizione || "Monitoraggio continuo del setup."
            )
          );
        }
        alertCards.push(
          alertCard(
            "Costo di sessione",
            `Fee oggi ${eur(summary.performance.today_fees_eur)} con ${summary.risk.daily_trade_count} trade registrati nella giornata.`,
            summary.performance.today_fees_eur > Math.abs(summary.risk.daily_realized_pnl) ? "watch" : "ok",
            `Expectancy ${eur(summary.performance.expectancy_eur)} | fee totali ${eur(summary.account.fees_total)}`
          )
        );
        document.getElementById("overview-summary").textContent =
          `Il desk e ${niceStatus(summary.risk.guardrail_status).toLowerCase()}, il bot e ${niceStatus(summary.bot.status).toLowerCase()} e il focus operativo resta ${focusSymbol ? focusSymbol.symbol : "sul monitoraggio generale"}. Apri review se vuoi capire la giornata, rischio se vuoi validare i limiti, trust se vuoi ricordare scope e limiti dell'alpha.`;
        document.getElementById("overview-focus-grid").innerHTML = `
          <div class="card overview-focus-card">
            <div class="label-row">
              <div class="label-group">
                <strong>Desk adesso</strong>
                ${infoButton("Riassunto istantaneo dello stato del desk: salute operativa, ultimo ciclo e numero di trade gia consumati oggi.")}
              </div>
            </div>
            <div class="value ${toneClass(summary.risk.guardrail_status)}">${niceStatus(summary.risk.guardrail_status)}</div>
            <div class="sub">Bot ${niceStatus(summary.bot.status)} | ${summary.risk.daily_trade_count} trade oggi</div>
          </div>
          <div class="card overview-focus-card">
            <div class="label-row">
              <div class="label-group">
                <strong>Focus simbolo</strong>
                ${infoButton("Il simbolo che oggi merita la lettura piu veloce: e quello piu vicino a uno stato operativo interessante o bloccato.")}
              </div>
            </div>
            <div class="value mono ${focusSymbol ? toneClass(focusSymbol.analysis?.status) : "watch"}">${focusSymbol ? focusSymbol.symbol : "n/d"}</div>
            <div class="sub">${focusSymbol?.analysis?.reason || "Nessun focus dominante disponibile."}</div>
          </div>
          <div class="card overview-focus-card">
            <div class="label-row">
              <div class="label-group">
                <strong>Review del giorno</strong>
                ${infoButton("Il verdetto rapido che hai salvato nella review giornaliera, utile per riprendere il contesto senza rileggere tutto.")}
              </div>
            </div>
            <div class="value ${summary.daily_review.annotation?.verdict === "setup_chiari" ? "good" : "watch"}">${reviewVerdictLabels[summary.daily_review.annotation?.verdict || "da_rivedere"]}</div>
            <div class="sub">${summary.daily_review.annotation?.note || summary.daily_review.summary}</div>
          </div>
          <div class="card overview-focus-card">
            <div class="label-row">
              <div class="label-group">
                <strong>Prossimo passo</strong>
                ${infoButton("L'azione piu sensata da fare ora per continuare a usare o mostrare l'alpha senza disperdersi in cose secondarie.")}
              </div>
            </div>
            <div class="value mono ${summary.alpha_onboarding.readiness_label.includes("DESIGN") ? "good" : "watch"}">${summary.alpha_onboarding.readiness_label}</div>
            <div class="sub">${summary.alpha_onboarding.next_steps[0]?.detail || "Nessun next step registrato."}</div>
          </div>
        `;
        setBalancedGridColumns("overview-focus-grid", 4, 4);
        document.getElementById("alert-grid").innerHTML = alertCards.join("");
        setBalancedGridColumns("alert-grid", alertCards.length, 3);
        document.getElementById("overview-alerts-count").textContent = `${alertCards.length} alert`;

        document.getElementById("system-grid").innerHTML = `
          <div class="system-card">
            <div class="step">Fase 1</div>
            <div class="label-group">
                <strong>Raccolta dati</strong>
              ${infoButton("Il bot legge order book pubblico, trade pubblici e candele dal venue operativo della sessione.")}
            </div>
            <p>Il collector salva tutto in SQLite, cosi non lavoriamo su memoria volatile.</p>
          </div>
          <div class="system-card">
            <div class="step">Fase 2</div>
            <div class="label-group">
              <strong>Costruzione contesto</strong>
              ${infoButton("Il sistema calcola momentum sul micro-movimento e confronta il prezzo con il trend delle candele recenti.")}
            </div>
            <p>Serve a evitare ingressi quando il book accelera ma il contesto piu ampio non conferma.</p>
          </div>
          <div class="system-card">
            <div class="step">Fase 3</div>
            <div class="label-group">
              <strong>Filtro microstruttura</strong>
              ${infoButton("Prima di entrare, il motore controlla spread, imbalance del book, numero di trade recenti e finestra di volatilita.")}
            </div>
            <p>Questa fase serve a evitare mercati troppo vuoti, troppo costosi o troppo violenti.</p>
          </div>
          <div class="system-card">
            <div class="step">Fase 4</div>
            <div class="label-group">
              <strong>Decisione deterministica</strong>
              ${infoButton("Non c'e improvvisazione: il motore controlla soglie precise e poi chiede permesso al risk manager.")}
            </div>
            <p>Se una soglia non passa o il rischio non rientra nei limiti, il trade non parte.</p>
          </div>
          <div class="system-card">
            <div class="step">Fase 5</div>
            <div class="label-group">
              <strong>Risk manager e kill switch</strong>
              ${infoButton("Il desk paper applica limiti di esposizione, trade giornalieri, drawdown, perdite consecutive, cooldown e salute del collector.")}
            </div>
            <p>Questo e il blocco che rende il sistema controllato, non solo automatizzato.</p>
          </div>
          <div class="system-card">
            <div class="step">Fase 6</div>
            <div class="label-group">
              <strong>Esecuzione e journal</strong>
              ${infoButton("Quando tutte le condizioni sono allineate, il sistema apre una posizione simulata, applica fee, slippage, stop loss, take profit e registra tutto.")}
            </div>
            <p>In questa fase usiamo ${summary.provider.current.label} come profilo commissionale della simulazione e salviamo un journal completo del trade.</p>
          </div>
        `;
        setBalancedGridColumns("system-grid", 6, 3);
        document.getElementById("overview-system-count").textContent = "6 fasi";

        document.getElementById("market-selector").innerHTML = summary.symbols.map(symbol => `
          <button class="market-tab ${selectedMarket && symbol.symbol === selectedMarket.symbol ? "active" : ""}" type="button" data-market-symbol="${symbol.symbol}">
            ${symbol.symbol}
          </button>
        `).join("");
        if (selectedMarket) {
          const marketAnalysis = selectedMarket.analysis || {};
          const marketDetails = marketAnalysis.details || {};
          document.getElementById("market-brief-grid").innerHTML = `
            <div class="card">
              <div class="label-row">
                <div class="label-group">
                  <strong>Prezzo medio</strong>
                  ${infoButton("Mid-price della crypto selezionata: media tra miglior bid e miglior ask del book attuale.")}
                </div>
              </div>
              <div class="value mono" style="margin-top:8px; font-size:24px; font-weight:700;">${eur(selectedMarket.mid_price)}</div>
              <p style="margin-top:6px;">Bid ${eur(selectedMarket.best_bid)} | Ask ${eur(selectedMarket.best_ask)}</p>
            </div>
            <div class="card">
              <div class="label-row">
                <div class="label-group">
                  <strong>Stato setup</strong>
                  ${infoButton("Stato operativo attuale del setup sulla crypto selezionata: osservazione, blocco, entrata o gestione posizione.")}
                </div>
              </div>
              <div class="value ${toneClass(marketAnalysis.status)}" style="margin-top:8px; font-size:24px; font-weight:700;">${niceStatus(marketAnalysis.status)}</div>
              <p style="margin-top:6px;">${marketAnalysis.reason || "Analisi in aggiornamento."}</p>
            </div>
            <div class="card">
              <div class="label-row">
                <div class="label-group">
                  <strong>Costo immediato</strong>
                  ${infoButton("Lo spread dice quanto pagheresti subito entrando a mercato. E il primo filtro da guardare quando il bot sembra troppo prudente.")}
                </div>
              </div>
              <div class="value mono" style="margin-top:8px; font-size:24px; font-weight:700;">${selectedMarket.spread_bps === null || selectedMarket.spread_bps === undefined ? "n/d" : bps(selectedMarket.spread_bps)}</div>
              <p style="margin-top:6px;">Trade recenti ${selectedMarket.trade_activity.count} | candele ${selectedMarket.candle_count}</p>
            </div>
            <div class="card">
              <div class="label-row">
                <div class="label-group">
                  <strong>Prossima condizione</strong>
                  ${infoButton("Il prossimo evento che dovrebbe verificarsi sul mercato prima che il sistema cambi stato su questa crypto.")}
                </div>
              </div>
              <div class="value mono" style="margin-top:8px; font-size:18px; font-weight:700;">${selectedMarket.symbol}</div>
              <p style="margin-top:6px;">${marketDetails.prossima_condizione || "Nessuna condizione aggiuntiva registrata."}</p>
            </div>
          `;
          setBalancedGridColumns("market-brief-grid", 4, 4);
          document.getElementById("watch-grid").innerHTML = `
            <div class="watch-card">
              <div class="provider-row">
                <div class="label-group">
                  <strong>${selectedMarket.symbol}</strong>
                  ${infoButton("Scheda compatta della crypto selezionata: stato attuale del setup, costo spread e contesto immediato.")}
                </div>
                ${buildBadge(niceStatus(marketAnalysis.status), toneClass(marketAnalysis.status))}
              </div>
              <div class="price mono">${eur(selectedMarket.mid_price)}</div>
              <div class="sub">Spread ${selectedMarket.spread_bps === null || selectedMarket.spread_bps === undefined ? "n/d" : bps(selectedMarket.spread_bps)} | trade recenti ${selectedMarket.trade_activity.count}</div>
              <div class="chips" style="margin-top:10px;">
                <span class="chip">Momentum ${Number.isFinite(Number(marketDetails.momentum_pct)) ? pct(marketDetails.momentum_pct, 4) : "n/d"}</span>
                <span class="chip">Trend ${Number.isFinite(Number(marketDetails.candle_trend_pct)) ? pct(marketDetails.candle_trend_pct, 4) : "n/d"}</span>
                <span class="chip">Imbalance ${Number.isFinite(Number(marketDetails.book_imbalance_pct)) ? pct(marketDetails.book_imbalance_pct, 2) : "n/d"}</span>
              </div>
              <p style="margin-top:10px;">${marketAnalysis.reason || "Analisi in aggiornamento."}</p>
              <div class="sub">${marketDetails.prossima_condizione || "Nessuna condizione speciale registrata."}</div>
            </div>
          `;
          setBalancedGridColumns("watch-grid", 1, 1);
        } else {
          document.getElementById("market-brief-grid").innerHTML = "";
          document.getElementById("watch-grid").innerHTML = `<div class="card"><p>Nessun mercato disponibile nella watchlist.</p></div>`;
        }

        document.getElementById("risk-grid").innerHTML = `
          <div class="card">
            <div class="label-row">
              <div class="label-group">
                <strong>Stato guard rail</strong>
                ${infoButton("Se e ATTIVO il motore puo aprire nuovi trade. COOLDOWN pausa temporanea. HARD_STOP blocco di sicurezza fino a reset o nuovo giorno.")}
              </div>
            </div>
            <div class="value mono ${toneClass(summary.risk.guardrail_status)}" style="margin-top:8px; font-size:26px; font-weight:700;">${niceStatus(summary.risk.guardrail_status)}</div>
            <p style="margin-top:6px;">${summary.risk.kill_switch_reason || "Nessun blocco attivo."}</p>
          </div>
          <div class="card">
            <div class="label-row">
              <div class="label-group">
                <strong>Perdita giornaliera</strong>
                ${infoButton("Confronta il PnL realizzato di oggi con il limite massimo che il desk si concede prima di fermarsi.")}
              </div>
            </div>
            <div class="value mono ${Number(summary.risk.daily_realized_pnl) >= 0 ? "good" : "bad"}" style="margin-top:8px; font-size:26px; font-weight:700;">${eur(summary.risk.daily_realized_pnl)}</div>
            <p style="margin-top:6px;">Limite ${eur(summary.risk.daily_loss_limit_eur)}</p>
          </div>
          <div class="card">
            <div class="label-row">
              <div class="label-group">
                <strong>Esposizione</strong>
                ${infoButton("Quanto capitale e attualmente esposto al mercato rispetto al limite massimo deciso dal risk manager.")}
              </div>
            </div>
            <div class="value mono" style="margin-top:8px; font-size:26px; font-weight:700;">${eur(summary.risk.current_exposure_eur)}</div>
            <p style="margin-top:6px;">${pct(summary.risk.current_exposure_pct, 2)} su max ${pct(summary.risk.max_exposure_pct, 2)} (${eur(summary.risk.max_exposure_eur)})</p>
          </div>
          <div class="card">
            <div class="label-row">
              <div class="label-group">
                <strong>Drawdown</strong>
                ${infoButton("Misura quanto siamo sotto il picco di equity. E un indicatore chiave per capire se il sistema sta soffrendo troppo.")}
              </div>
            </div>
            <div class="value mono ${Number(summary.risk.current_drawdown_pct) > 0 ? "bad" : "good"}" style="margin-top:8px; font-size:26px; font-weight:700;">${pct(summary.risk.current_drawdown_pct, 2)}</div>
            <p style="margin-top:6px;">Max osservato ${pct(summary.risk.max_drawdown_observed_pct, 2)} | limite ${pct(summary.risk.max_drawdown_limit_pct, 2)}</p>
          </div>
          <div class="card">
            <div class="label-row">
              <div class="label-group">
                <strong>Disciplina trade</strong>
                ${infoButton("Conta trade della giornata e streak di perdite. Serve a bloccare overtrading e rincorsa al recupero.")}
              </div>
            </div>
            <div class="value mono" style="margin-top:8px; font-size:26px; font-weight:700;">${summary.risk.daily_trade_count} / ${summary.risk.daily_trade_limit}</div>
            <p style="margin-top:6px;">Perdite consecutive ${summary.risk.consecutive_losses} su limite ${summary.risk.max_consecutive_losses}</p>
          </div>
          <div class="card">
            <div class="label-row">
              <div class="label-group">
                <strong>Posizioni aperte</strong>
                ${infoButton("Quante posizioni sono aperte adesso rispetto al massimo consentito dal desk paper.")}
              </div>
            </div>
            <div class="value mono" style="margin-top:8px; font-size:26px; font-weight:700;">${summary.risk.open_positions} / ${summary.risk.max_open_positions}</div>
            <p style="margin-top:6px;">Allocazione max per trade ${pct(summary.risk.max_trade_allocation_pct, 2)}</p>
          </div>
          <div class="card">
            <div class="label-row">
              <div class="label-group">
                <strong>Drawdown di oggi</strong>
                ${infoButton("Peggior drawdown osservato nella giornata corrente: aiuta a capire se il desk si sta deteriorando anche prima del limite assoluto.")}
              </div>
            </div>
            <div class="value mono ${Number(summary.risk.today_max_drawdown_pct) > 0 ? "bad" : "good"}" style="margin-top:8px; font-size:26px; font-weight:700;">${pct(summary.risk.today_max_drawdown_pct, 2)}</div>
            <p style="margin-top:6px;">Cash reserve minima ${pct(summary.risk.min_cash_reserve_pct, 2)}</p>
          </div>
          <div class="card">
            <div class="label-row">
              <div class="label-group">
                <strong>Cooldown e salute</strong>
                ${infoButton("Mostra se il sistema e in pausa dopo un trade/perdita e quanti errori consecutivi ha visto il collector.")}
              </div>
            </div>
            <div class="value mono" style="margin-top:8px; font-size:26px; font-weight:700;">${summary.risk.cooldown_until || "Nessuno"}</div>
            <p style="margin-top:6px;">Errori ciclo ${summary.risk.cycle_error_count} su limite ${summary.risk.max_cycle_errors}</p>
          </div>
          <div class="card">
            <div class="label-row">
              <div class="label-group">
                <strong>Budget di rischio</strong>
                ${infoButton("Quanta perdita massima teorica per trade puo tollerare il sistema e qual e il notional minimo per aprire un trade disciplinato.")}
              </div>
            </div>
            <div class="value mono" style="margin-top:8px; font-size:26px; font-weight:700;">${pct(summary.risk.max_risk_per_trade_pct, 2)}</div>
            <p style="margin-top:6px;">Minimo ordine ${eur(summary.risk.min_order_notional_eur)} | stop day ${pct(summary.risk.daily_loss_limit_pct, 2)}</p>
          </div>
        `;
        setBalancedGridColumns("risk-grid", 9, 3);
        document.getElementById("overview-risk-count").textContent = "9 controlli";

        document.getElementById("performance-grid").innerHTML = `
          <div class="card">
            <div class="label-row">
              <div class="label-group">
                <strong>Win rate</strong>
                ${infoButton("Percentuale dei trade chiusi in profitto. Da sola non basta: va letta insieme a expectancy e profit factor.")}
              </div>
            </div>
            <div class="value mono" style="margin-top:8px; font-size:26px; font-weight:700;">${pct(summary.performance.win_rate_pct, 2)}</div>
            <p style="margin-top:6px;">Trade chiusi ${summary.performance.closed_trades} | long ${summary.performance.long_trades} | short ${summary.performance.short_trades}</p>
          </div>
          <div class="card">
            <div class="label-row">
              <div class="label-group">
                <strong>Expectancy</strong>
                ${infoButton("Guadagno o perdita media attesa per trade chiuso. E una delle metriche piu importanti per capire se l'edge e reale.")}
              </div>
            </div>
            <div class="value mono ${Number(summary.performance.expectancy_eur) >= 0 ? "good" : "bad"}" style="margin-top:8px; font-size:26px; font-weight:700;">${eur(summary.performance.expectancy_eur)}</div>
            <p style="margin-top:6px;">Media per trade chiuso</p>
          </div>
          <div class="card">
            <div class="label-row">
              <div class="label-group">
                <strong>Profit factor</strong>
                ${infoButton("Rapporto tra profitti lordi e perdite lorde. Sopra 1 vuol dire che il sistema guadagna piu di quanto perde, almeno sul campione osservato.")}
              </div>
            </div>
            <div class="value mono" style="margin-top:8px; font-size:26px; font-weight:700;">${summary.performance.profit_factor === null ? "n/d" : num(summary.performance.profit_factor, 2)}</div>
            <p style="margin-top:6px;">Best ${eur(summary.performance.best_trade_eur)} | Worst ${eur(summary.performance.worst_trade_eur)}</p>
          </div>
          <div class="card">
            <div class="label-row">
              <div class="label-group">
                <strong>Media win / loss</strong>
                ${infoButton("Confronta il guadagno medio dei trade vincenti con la perdita media dei trade perdenti. Serve a capire la qualita del payoff.")}
              </div>
            </div>
            <div class="value mono" style="margin-top:8px; font-size:26px; font-weight:700;">${eur(summary.performance.average_win_eur)} / ${eur(summary.performance.average_loss_eur)}</div>
            <p style="margin-top:6px;">Profitti lordi ${eur(summary.performance.gross_profit_eur)} | Perdite lorde ${eur(summary.performance.gross_loss_eur)}</p>
          </div>
          <div class="card">
            <div class="label-row">
              <div class="label-group">
                <strong>Holding medio</strong>
                ${infoButton("Tempo medio di permanenza in posizione sui trade chiusi. Aiuta a capire se il sistema e davvero intraday disciplinato.")}
              </div>
            </div>
            <div class="value mono" style="margin-top:8px; font-size:26px; font-weight:700;">${num(summary.performance.average_hold_minutes, 1)} min</div>
            <p style="margin-top:6px;">Ingresso ${pct(summary.performance.average_entry_slippage_pct, 3)} | Uscita ${pct(summary.performance.average_exit_slippage_pct, 3)}</p>
          </div>
          <div class="card">
            <div class="label-row">
              <div class="label-group">
                <strong>Fee di oggi</strong>
                ${infoButton("Costo commissionale accumulato oggi. Anche un sistema con buoni segnali puo peggiorare se questo valore cresce troppo rispetto all'expectancy.")}
              </div>
            </div>
            <div class="value mono" style="margin-top:8px; font-size:26px; font-weight:700;">${eur(summary.performance.today_fees_eur)}</div>
            <p style="margin-top:6px;">Controlla sempre questo dato insieme al numero di trade.</p>
          </div>
        `;
        setBalancedGridColumns("performance-grid", 6, 3);
        document.getElementById("overview-performance-count").textContent = `${summary.performance.closed_trades} trade`;

        document.getElementById("equity-chart").innerHTML = buildEquityChart(summary.performance.equity_history);

        document.getElementById("rules-grid").innerHTML = `
          <div class="card">
            <div class="label-row">
              <div class="label-group">
                <strong>Momentum direzionale</strong>
                ${infoButton("Soglia minima del momentum order book richiesta per aprire un long o uno short paper. Il motore usa la stessa intensita in valore assoluto per entrambe le direzioni.")}
              </div>
            </div>
            <div class="value mono" style="margin-top:8px; font-size:26px; font-weight:700;">${pct(summary.strategy.entry_momentum_threshold_pct, 4)}</div>
            <p style="margin-top:6px;">Long sopra soglia | short sotto la stessa soglia in negativo.</p>
          </div>
          <div class="card">
            <div class="label-row">
              <div class="label-group">
                <strong>Trend candele direzionale</strong>
                ${infoButton("Serve per evitare ingressi quando il micro-momentum e forte ma il contesto delle candele non conferma il verso del trade.")}
              </div>
            </div>
            <div class="value mono" style="margin-top:8px; font-size:26px; font-weight:700;">${pct(summary.strategy.candle_trend_threshold_pct, 4)}</div>
            <p style="margin-top:6px;">Il long chiede trend positivo, lo short trend negativo della stessa intensita.</p>
          </div>
          <div class="card">
            <div class="label-row">
              <div class="label-group">
                <strong>Spread massimo</strong>
                ${infoButton("Se spread bid-ask e troppo largo, il bot considera l'ingresso troppo costoso e aspetta.")}
              </div>
            </div>
            <div class="value mono" style="margin-top:8px; font-size:26px; font-weight:700;">${bps(summary.strategy.spread_limit_bps)}</div>
            <p style="margin-top:6px;">Filtro di costo immediato prima dell'ingresso.</p>
          </div>
          <div class="card">
            <div class="label-row">
              <div class="label-group">
                <strong>Uscite</strong>
                ${infoButton("La posizione chiude per stop loss, take profit, inversione del momentum o superamento del tempo massimo. In alpha simuliamo uscite reduce-only.")}
              </div>
            </div>
            <div class="value mono" style="margin-top:8px; font-size:26px; font-weight:700;">TP ${pct(summary.strategy.take_profit_pct, 2)} | SL ${pct(summary.strategy.stop_loss_pct, 2)}</div>
            <p style="margin-top:6px;">R/R ${num(summary.strategy.reward_to_risk_ratio, 2)} | tempo max ${num(summary.strategy.max_hold_minutes, 0)} minuti.</p>
          </div>
          <div class="card">
            <div class="label-row">
              <div class="label-group">
                <strong>Imbalance book</strong>
                ${infoButton("Richiede che il book confermi il verso del trade: bid dominante per il long, ask dominante per lo short.")}
              </div>
            </div>
            <div class="value mono" style="margin-top:8px; font-size:26px; font-weight:700;">L ${pct(summary.strategy.long_book_imbalance_threshold_pct, 2)} | S ${pct(summary.strategy.short_book_imbalance_threshold_pct, 2)}</div>
            <p style="margin-top:6px;">Filtro di qualita sulla microstruttura per entrambe le direzioni.</p>
          </div>
          <div class="card">
            <div class="label-row">
              <div class="label-group">
                <strong>Volatilita utile</strong>
                ${infoButton("Il motore evita sia mercati troppo morti, sia mercati troppo violenti rispetto al profilo di rischio scelto.")}
              </div>
            </div>
            <div class="value mono" style="margin-top:8px; font-size:26px; font-weight:700;">${pct(summary.strategy.volatility_floor_pct, 3)} - ${pct(summary.strategy.volatility_ceiling_pct, 2)}</div>
            <p style="margin-top:6px;">Trade minimi recenti ${summary.strategy.minimum_recent_trade_count}</p>
          </div>
          <div class="card">
            <div class="label-row">
              <div class="label-group">
                <strong>Limiti desk</strong>
                ${infoButton("Cap di esposizione e perdita giornaliera oltre i quali il risk manager blocca nuove entrate.")}
              </div>
            </div>
            <div class="value mono" style="margin-top:8px; font-size:26px; font-weight:700;">Expo ${pct(summary.risk.max_exposure_pct, 0)} | Stop day ${pct(summary.risk.daily_loss_limit_pct, 1)}</div>
            <p style="margin-top:6px;">Open max ${summary.risk.max_open_positions} | risk/trade ${pct(summary.risk.max_risk_per_trade_pct, 2)}</p>
          </div>
          <div class="card">
            <div class="label-row">
              <div class="label-group">
                <strong>Trigger di uscita</strong>
                ${infoButton("Soglie di inversione che possono anticipare la chiusura prima di stop o target, quando il contesto di breve peggiora.")}
              </div>
            </div>
            <div class="value mono" style="margin-top:8px; font-size:26px; font-weight:700;">Mom ${pct(summary.strategy.exit_reverse_threshold_pct, 4)} | Imb ${pct(summary.strategy.imbalance_reverse_threshold_pct, 2)}</div>
            <p style="margin-top:6px;">Riduce la permanenza in setup deteriorati.</p>
          </div>
          <div class="card">
            <div class="label-row">
              <div class="label-group">
                <strong>Perps setup</strong>
                ${infoButton("La strategia opera in modalita perps-aware: leva base, margine e execution policy vengono salvati nei trade per confrontare le versioni future in modo serio.")}
              </div>
            </div>
            <div class="value mono" style="margin-top:8px; font-size:26px; font-weight:700;">${num(summary.strategy.perps_default_leverage, 2)}x</div>
            <p style="margin-top:6px;">${summary.strategy.perps_margin_mode} | ${summary.strategy.perps_execution_policy} | short ${summary.strategy.short_entries_enabled ? "si" : "no"}</p>
          </div>
        `;
        setBalancedGridColumns("rules-grid", 9, 3);

        document.getElementById("market-decision-summary").textContent = selectedMarket
          ? `Stai leggendo ${selectedMarket.symbol}: la board sotto mostra solo il contesto, i filtri e il piano del simbolo selezionato.`
          : "Seleziona una crypto per vedere la decision board.";
        document.getElementById("decision-board").innerHTML = selectedMarket ? [selectedMarket].map(symbol => {
          const analysis = symbol.analysis || { status: "DATI_INSUFFICIENTI", action: "ATTENDI", reason: "Analisi non ancora disponibile.", details: {} };
          const details = analysis.details || {};
          const decisionSide = directionalSide(
            details.decision_side
            || symbol.position?.side
            || (Number(details.momentum_pct) < 0 && Number(details.candle_trend_pct) < 0 ? "SHORT" : "LONG")
          );
          const momentum = Number(details.momentum_pct);
          const momentumTarget = decisionSide === "SHORT"
            ? -Number(details.entry_momentum_threshold_pct || summary.strategy.entry_momentum_threshold_pct)
            : Number(details.entry_momentum_threshold_pct || summary.strategy.entry_momentum_threshold_pct);
          const trend = Number(details.candle_trend_pct);
          const trendTarget = decisionSide === "SHORT"
            ? -Number(details.candle_trend_threshold_pct || summary.strategy.candle_trend_threshold_pct)
            : Number(details.candle_trend_threshold_pct || summary.strategy.candle_trend_threshold_pct);
          const imbalance = Number(details.book_imbalance_pct);
          const imbalanceTarget = decisionSide === "SHORT"
            ? Number(details.short_book_imbalance_threshold_pct || summary.strategy.short_book_imbalance_threshold_pct)
            : Number(details.long_book_imbalance_threshold_pct || details.book_imbalance_threshold_pct || summary.strategy.long_book_imbalance_threshold_pct || summary.strategy.book_imbalance_threshold_pct);
          const volatility = Number(details.candle_volatility_pct);
          const volatilityFloor = Number(details.volatility_floor_pct || summary.strategy.volatility_floor_pct);
          const volatilityCeiling = Number(details.volatility_ceiling_pct || summary.strategy.volatility_ceiling_pct);
          const spread = Number(symbol.spread_bps);
          const spreadLimit = Number(details.spread_limit_bps || summary.strategy.spread_limit_bps);
          const openPosition = symbol.position;
          const positionEntryContext = openPosition?.entry_context || {};
          const riskManager = details.risk_manager || positionEntryContext.risk_manager || {};
          const approvedNotional = Number(
            riskManager.approved_notional_eur
            ?? details.notional_eur
            ?? positionEntryContext.notional_eur
            ?? summary.strategy.paper_trade_size
          );
          const entrySlippage = Number(
            details.entry_slippage_pct
            ?? positionEntryContext.slippage_pct
          );
          const stopLossPrice = Number(
            details.stop_loss_price
            ?? positionEntryContext.stop_loss_price
          );
          const takeProfitPrice = Number(
            details.take_profit_price
            ?? positionEntryContext.take_profit_price
          );
          const plannedRisk = Number(
            details.planned_risk_eur
            ?? positionEntryContext.planned_risk_eur
          );
          const plannedReward = Number(
            details.planned_reward_eur
            ?? positionEntryContext.planned_reward_eur
          );
          const leverage = Number(
            details.perps_default_leverage
            ?? positionEntryContext.leverage
            ?? summary.strategy.perps_default_leverage
          );
          const marginReserved = Number(
            details.margin_reserved
            ?? positionEntryContext.margin_reserved
            ?? symbol.position?.margin_reserved
          );
          const positionText = openPosition
            ? `Aperta da ${openPosition.opened_at}, lato ${openPosition.side || decisionSide}, PnL teorico ${eur(openPosition.unrealized_pnl)}`
            : "Nessuna posizione paper aperta su questo simbolo.";

          return `
            <article class="decision-card">
              <div class="decision-head">
                <div>
                  <div class="title-row" style="justify-content:flex-start;">
                    <div class="title-group">
                      <h3>${symbol.symbol}</h3>
                      ${infoButton("Questa scheda mostra il ragionamento del motore sul singolo simbolo.")}
                    </div>
                  </div>
                  <div class="decision-meta" style="margin-top:10px;">
                    ${buildBadge(niceStatus(analysis.status), toneClass(analysis.status))}
                    ${buildBadge(niceAction(analysis.action), toneClass(analysis.status))}
                    ${buildBadge(`Bias ${decisionSide}`, decisionSide === "SHORT" ? "bad" : "ok")}
                    <span class="badge">${symbol.candle_count} candele</span>
                    <span class="badge">${symbol.trade_activity.count} trade letti</span>
                    <span class="badge">Provider ${summary.provider.current.label}</span>
                  </div>
                </div>
                <div class="timestamp mono">${analysis.updated_at || symbol.updated_at || "n/d"}</div>
              </div>

              <div class="callout">
                <div class="label-row">
                  <div class="label-group">
                    <strong>Cosa sta facendo adesso</strong>
                    ${infoButton("Questa e la spiegazione piu importante: ti dice il motivo attuale per cui il bot aspetta, entra o mantiene la posizione.")}
                  </div>
                </div>
                <p style="margin-top:8px;">${analysis.reason}</p>
              </div>

              <div class="callout">
                <div class="label-row">
                  <div class="label-group">
                    <strong>Prossima condizione per muoversi</strong>
                    ${infoButton("Ti dice cosa deve succedere nel mercato prima che il sistema cambi stato o faccia il prossimo paper trade.")}
                  </div>
                </div>
                <p style="margin-top:8px;">${details.prossima_condizione || "Sto aspettando un setup piu pulito."}</p>
              </div>

              <div class="metric-grid">
                ${metricCard(
                  "Momentum order book",
                  Number.isFinite(momentum) ? pct(momentum, 4) : "n/d",
                  `Soglia ${pct(momentumTarget, 4)}`,
                  decisionSide === "SHORT"
                    ? "Misura se il prezzo medio degli ultimi snapshot sta accelerando verso il basso abbastanza da sostenere uno short."
                    : "Misura se il prezzo medio degli ultimi snapshot sta accelerando verso l'alto abbastanza da sostenere un long.",
                  Number.isFinite(momentum) && directionalReady(momentum, momentumTarget, decisionSide) ? "good" : ""
                )}
                ${metricCard(
                  "Trend candele",
                  Number.isFinite(trend) ? pct(trend, 4) : "n/d",
                  `Soglia ${pct(trendTarget, 4)}`,
                  decisionSide === "SHORT"
                    ? "Confronta la chiusura recente col contesto per capire se le candele confermano il lato ribassista."
                    : "Confronta la chiusura recente col contesto per capire se le candele confermano il lato rialzista.",
                  Number.isFinite(trend) && directionalReady(trend, trendTarget, decisionSide) ? "good" : ""
                )}
                ${metricCard(
                  "Imbalance book",
                  Number.isFinite(imbalance) ? pct(imbalance, 2) : "n/d",
                  `Soglia ${pct(imbalanceTarget, 2)}`,
                  decisionSide === "SHORT"
                    ? "Misura se sul lato ask del book c'e abbastanza pressione da sostenere uno short."
                    : "Misura se sul lato bid del book c'e abbastanza pressione da sostenere un long.",
                  Number.isFinite(imbalance) && directionalReady(imbalance, imbalanceTarget, decisionSide) ? "good" : ""
                )}
                ${metricCard(
                  "Volatilita utile",
                  Number.isFinite(volatility) ? pct(volatility, 3) : "n/d",
                  `Finestra ${pct(volatilityFloor, 3)} - ${pct(volatilityCeiling, 2)}`,
                  "Il bot preferisce un mercato vivo ma non eccessivamente violento.",
                  Number.isFinite(volatility) && volatility >= volatilityFloor && volatility <= volatilityCeiling ? "good" : "bad"
                )}
                ${metricCard(
                  "Spread attuale",
                  Number.isFinite(spread) ? bps(spread) : "n/d",
                  `Limite ${bps(spreadLimit)}`,
                  "Differenza tra miglior bid e miglior ask, espressa in basis point.",
                  Number.isFinite(spread) && spread <= spreadLimit ? "good" : "bad"
                )}
                ${metricCard(
                  "Notional approvato",
                  Number.isFinite(approvedNotional) ? eur(approvedNotional) : eur(summary.strategy.paper_trade_size),
                  `Margine ${Number.isFinite(marginReserved) ? eur(marginReserved) : "n/d"} | leva ${num(leverage, 2)}x`,
                  "Importo realmente approvato dal risk manager per il prossimo ingresso paper, con margine riservato e leva del setup perps.",
                  Number.isFinite(approvedNotional) && approvedNotional >= summary.risk.min_order_notional_eur ? "good" : ""
                )}
              </div>

              <div class="progress-stack">
                ${progressCard(
                  "Prontezza momentum",
                  `${Number.isFinite(momentum) ? pct(momentum, 4) : "n/d"} su ${pct(momentumTarget, 4)}`,
                  directionalRatio(momentum, momentumTarget, decisionSide),
                  directionalTone(momentum, momentumTarget, decisionSide),
                  "Se questa barra supera la soglia, il micro-momentum e abbastanza forte per supportare il verso del trade scelto."
                )}
                ${progressCard(
                  "Prontezza trend candele",
                  `${Number.isFinite(trend) ? pct(trend, 4) : "n/d"} su ${pct(trendTarget, 4)}`,
                  directionalRatio(trend, trendTarget, decisionSide),
                  directionalTone(trend, trendTarget, decisionSide),
                  "Questa barra dice se il contesto delle candele supporta davvero il verso del setup."
                )}
                ${progressCard(
                  "Prontezza imbalance",
                  `${Number.isFinite(imbalance) ? pct(imbalance, 2) : "n/d"} su ${pct(imbalanceTarget, 2)}`,
                  directionalRatio(imbalance, imbalanceTarget, decisionSide),
                  directionalTone(imbalance, imbalanceTarget, decisionSide),
                  decisionSide === "SHORT"
                    ? "Se questa barra supera la soglia, il lato ask del book e abbastanza presente da sostenere lo short."
                    : "Se questa barra supera la soglia, il lato bid del book e abbastanza presente da sostenere il long."
                )}
                ${progressCard(
                  "Sicurezza spread",
                  `${Number.isFinite(spread) ? bps(spread) : "n/d"} su ${bps(spreadLimit)}`,
                  Number.isFinite(spread) && spreadLimit > 0 ? 1 - (spread / spreadLimit) : 0,
                  statusToneFromValue(spread, spreadLimit, true),
                  "Piu la barra e alta, piu il costo immediato bid-ask e sotto controllo."
                )}
              </div>

              ${buildChart(symbol.mid_history, symbol.candle_history)}

              <div class="detail-grid">
                ${detailCard("Bid / Ask", `${eur(symbol.best_bid)} / ${eur(symbol.best_ask)}`, "Prezzi del book adesso", "Miglior prezzo compratore e miglior prezzo venditore visibili nel book.")}
                ${detailCard("Prezzo medio", eur(symbol.mid_price), "Media tra bid e ask", "Il mid-price e un riferimento comodo per capire il centro del book senza spread.")}
                ${detailCard("Ultimo trade visto", symbol.trade_activity.last_trade_at || "n/d", symbol.trade_activity.last_price ? `Prezzo ${eur(symbol.trade_activity.last_price)}` : "Nessun trade recente", "Timestamp dell'ultimo trade pubblico letto per questo simbolo.")}
                ${detailCard("Posizione aperta", openPosition ? `${openPosition.side || decisionSide}` : "No", positionText, "Indica se in questo momento il bot ha gia una posizione paper aperta sul simbolo e in quale verso.")}
                ${detailCard("Leva / margine", `${num(leverage, 2)}x / ${Number.isFinite(marginReserved) ? eur(marginReserved) : "n/d"}`, `${summary.strategy.perps_margin_mode} | ${summary.strategy.perps_execution_policy}`, "Setup perps registrato sul trade o sul prossimo setup del simbolo.")}
                ${detailCard("Stop / target", `${Number.isFinite(stopLossPrice) ? eur(stopLossPrice) : "n/d"} / ${Number.isFinite(takeProfitPrice) ? eur(takeProfitPrice) : "n/d"}`, "Prezzi di difesa e obiettivo", "Livelli di uscita pianificati sul trade paper.")}
                ${detailCard("Rischio / premio", `${Number.isFinite(plannedRisk) ? eur(plannedRisk) : "n/d"} / ${Number.isFinite(plannedReward) ? eur(plannedReward) : "n/d"}`, "Stimati al momento dell'ingresso", "Budget di rischio pianificato e guadagno atteso teorico prima dell'uscita.")}
                ${detailCard("Slippage atteso", Number.isFinite(entrySlippage) ? pct(entrySlippage, 3) : "n/d", "Impatto stimato del fill sul book", "Dice quanto il prezzo medio di esecuzione si allontana dal prezzo di riferimento migliore.")}
                ${detailCard("Guard rail simbolo", niceStatus(details.guardrail_status || summary.risk.guardrail_status), details.risk_kill_reason || "Nessun blocco specifico attivo.", "Stato del risk manager al momento dell'ultima decisione su questo simbolo.")}
              </div>
            </article>
          `;
        }).join("") : `<div class="card"><p>Nessuna decision board disponibile: la watchlist e vuota.</p></div>`;

        document.getElementById("positions").innerHTML = summary.positions.length
          ? summary.positions.map(item => {
              const totalFee = Number(item.entry_fee || 0) + Number(item.exit_fee || 0);
              const pnl = item.realized_pnl === null || item.realized_pnl === undefined
                ? null
                : Number(item.realized_pnl);
              const entryContext = item.entry_context || {};
              const exitContext = item.exit_context || {};
              const riskPlan = `${Number.isFinite(Number(entryContext.stop_loss_price)) ? eur(entryContext.stop_loss_price) : "n/d"} / ${Number.isFinite(Number(entryContext.take_profit_price)) ? eur(entryContext.take_profit_price) : "n/d"}`;
              const exitText = item.status === "OPEN"
                ? "Ancora aperta"
                : `${eur(item.exit_price)}${item.closed_at ? `<div class="muted">${item.closed_at}</div>` : ""}`;
              return `
                <tr>
                  <td>
                    <strong>${item.symbol}</strong>
                    <div class="muted">${item.side}</div>
                  </td>
                  <td>${buildBadge(item.status === "OPEN" ? "Aperta" : "Chiusa", item.status === "OPEN" ? "watch" : "ok")}</td>
                  <td class="mono">
                    ${eur(item.entry_price)}
                    <div class="muted">${item.opened_at}</div>
                  </td>
                  <td class="mono">
                    ${riskPlan}
                    <div class="muted">Rischio ${Number.isFinite(Number(entryContext.planned_risk_eur)) ? eur(entryContext.planned_risk_eur) : "n/d"} | Reward ${Number.isFinite(Number(entryContext.planned_reward_eur)) ? eur(entryContext.planned_reward_eur) : "n/d"}</div>
                  </td>
                  <td class="mono">
                    ${exitText}
                    <div class="muted">${item.close_reason || "Monitoraggio attivo"}${Number.isFinite(Number(exitContext.slippage_pct)) ? ` | Slip ${pct(exitContext.slippage_pct, 3)}` : ""}</div>
                  </td>
                  <td class="mono">${eur(totalFee)}</td>
                  <td class="mono ${pnl === null ? "" : (pnl >= 0 ? "good" : "bad")}">${pnl === null ? "Aperta" : eur(pnl)}</td>
                </tr>
              `;
            }).join("")
          : renderEmpty("Nessuna posizione paper registrata finora.", 7);

        document.getElementById("journal-digest-summary").textContent = summary.journal_digest.summary;
        document.getElementById("journal-digest-cards").innerHTML = summary.journal_digest.scorecards.map(item => `
          <div class="card">
            <div class="label-row">
              <div class="label-group">
                <strong>${item.label}</strong>
                ${infoButton("Card di sintesi del journal: serve a capire al volo quanta materia utile c'e davvero nella review di oggi.")}
              </div>
            </div>
            <div class="value mono ${item.tone || ""}" style="margin-top:8px; font-size:20px; font-weight:700;">${item.value}</div>
            <p style="margin-top:6px;">${item.sub}</p>
          </div>
        `).join("");
        setBalancedGridColumns("journal-digest-cards", summary.journal_digest.scorecards.length, 6);
        document.getElementById("journal-next-reads").innerHTML = summary.journal_digest.next_reads.map(item => `
          <div class="mini-row">
            <strong>${item.title}</strong>
            <p class="muted">${item.detail}</p>
          </div>
        `).join("");
        setBalancedGridColumns("journal-next-reads", summary.journal_digest.next_reads.length, 2);
        const blockedFocus = summary.failure_analysis.blocked_trades[0];
        const replayFocus = summary.decision_replay[0];
        const signalFocus = summary.signals[0];
        const reviewAnnotation = summary.daily_review.annotation || {};
        document.getElementById("journal-review-focus").innerHTML = `
          <div class="card journal-focus-card">
            <div class="label-row">
              <div class="label-group">
                <strong>Verdetto review</strong>
                ${infoButton("La lettura rapida che hai salvato per oggi. Serve a non rientrare nel Journal ogni volta da zero.")}
              </div>
            </div>
            <div class="value mono ${reviewAnnotation.verdict === "setup_chiari" ? "good" : "watch"}">${({
              setup_chiari: "Setup chiari",
              bot_troppo_cauto: "Bot troppo cauto",
              costi_pesanti: "Costi pesanti",
              da_rivedere: "Da rivedere"
            })[reviewAnnotation.verdict || "da_rivedere"]}</div>
            <div class="sub">${reviewAnnotation.note || "Nessuna nota review salvata per oggi."}</div>
          </div>
          <div class="card journal-focus-card">
            <div class="label-row">
              <div class="label-group">
                <strong>Blocco dominante</strong>
                ${infoButton("Il motivo che sta fermando di piu il desk in questa finestra. E il primo punto da verificare se il bot sembra troppo fermo.")}
              </div>
            </div>
            <div class="value mono ${blockedFocus ? "bad" : "good"}">${blockedFocus ? blockedFocus.symbol : "Nessuno"}</div>
            <div class="sub">${blockedFocus ? blockedFocus.last_reason : "Nessun blocco dominante rilevato nella finestra recente."}</div>
          </div>
          <div class="card journal-focus-card">
            <div class="label-row">
              <div class="label-group">
                <strong>Ultimo replay</strong>
                ${infoButton("Ultima decisione spiegabile salvata dal sistema. Serve a capire subito se il motore sta osservando, bloccando o entrando.")}
              </div>
            </div>
            <div class="value mono ${replayFocus ? toneClass(replayFocus.status) : "watch"}">${replayFocus ? replayFocus.symbol : "n/d"}</div>
            <div class="sub">${replayFocus ? replayFocus.reason : "Ancora nessun replay disponibile."}</div>
          </div>
          <div class="card journal-focus-card">
            <div class="label-row">
              <div class="label-group">
                <strong>Segnale piu vicino</strong>
                ${infoButton("Il segnale recente piu utile da leggere per capire se ci stiamo avvicinando a un setup o se il motore resta in attesa.")} 
              </div>
            </div>
            <div class="value mono ${signalFocus ? (signalFocus.action === "COMPRA" ? "good" : (signalFocus.action === "VENDI" ? "bad" : "watch")) : "watch"}">${signalFocus ? signalFocus.symbol : "n/d"}</div>
            <div class="sub">${signalFocus ? signalFocus.reason : "Nessun segnale recente abbastanza forte da mostrare."}</div>
          </div>
        `;
        setBalancedGridColumns("journal-review-focus", 4, 4);

        document.getElementById("signals").innerHTML = summary.signals.length
          ? summary.signals.map(item => `
              <tr>
                <td class="mono">${item.created_at}</td>
                <td><strong>${item.symbol}</strong><div class="muted">score ${num(item.score || 0, 2)}</div></td>
                <td>${buildBadge(niceAction(item.action), item.action === "COMPRA" ? "ok" : (item.action === "VENDI" ? "bad" : "watch"))}</td>
                <td>${item.reason}</td>
              </tr>
            `).join("")
          : renderEmpty("Ancora nessun segnale registrato: il motore e in osservazione e non ha visto setup abbastanza puliti.", 4);
        document.getElementById("journal-signals-count").textContent = `${summary.signals.length} righe`;

        document.getElementById("events").innerHTML = summary.events.length
          ? summary.events.map(item => `
              <tr>
                <td class="mono">${item.created_at}</td>
                <td>${item.source}<div class="muted">${buildBadge(item.level, item.level === "ERROR" ? "bad" : (item.level === "WARNING" ? "watch" : "ok"))}</div></td>
                <td>${item.message}${item.details && Object.keys(item.details).length ? `<div class="muted">${previewPairs(item.details)}</div>` : ""}</td>
              </tr>
            `).join("")
          : renderEmpty("Ancora nessun evento operativo rilevante da mostrare.", 3);
        document.getElementById("journal-events-count").textContent = `${summary.events.length} righe`;

        document.getElementById("decision-replay").innerHTML = summary.decision_replay.length
          ? summary.decision_replay.map(item => `
              <tr>
                <td class="mono">${item.created_at}</td>
                <td><strong>${item.symbol}</strong><div class="muted">${niceStatus(item.status)} | ${niceAction(item.action)}</div></td>
                <td>${buildBadge(item.mode === "SHADOW" ? "Live Shadow" : item.mode, item.mode === "PAPER" ? "ok" : "watch")}</td>
                <td>${item.decisive_rule || item.filter_code}<div class="muted">${item.signal_present ? "Segnale presente" : "Segnale assente"}</div></td>
                <td>${item.reason}</td>
              </tr>
            `).join("")
          : renderEmpty("Ancora nessun replay decisionale disponibile.", 5);
        document.getElementById("journal-replay-count").textContent = `${summary.decision_replay.length} righe`;

        document.getElementById("ledger").innerHTML = summary.ledger.length
          ? summary.ledger.map(item => `
              <tr>
                <td class="mono">${item.created_at}</td>
                <td>${buildBadge(item.event_type, item.level === "ERROR" ? "bad" : (item.level === "WARNING" ? "watch" : "ok"))}</td>
                <td>${item.title}</td>
                <td>${item.symbol || item.reference_type || "desk"}${item.reference_id ? `<div class="muted">${item.reference_type || "ref"} ${item.reference_id}</div>` : ""}${item.payload && Object.keys(item.payload).length ? `<div class="muted">${previewPairs(item.payload)}</div>` : ""}</td>
              </tr>
            `).join("")
          : renderEmpty("Ancora nessun evento strutturato nel ledger.", 4);
        document.getElementById("journal-ledger-count").textContent = `${summary.ledger.length} righe`;

        document.getElementById("failure-analysis").innerHTML = `
          <div class="card">
            <div class="label-row">
              <div class="label-group">
                <strong>Blocked trades</strong>
                ${infoButton("I blocchi piu rilevanti del momento: servono a capire cosa sta fermando davvero il desk.")}
              </div>
            </div>
            ${compactList(
              summary.failure_analysis.blocked_trades.slice(0, 4).map(item => `${item.symbol}: ${item.last_reason}`),
              "Nessun blocco forte registrato oggi."
            )}
          </div>
          <div class="card">
            <div class="label-row">
              <div class="label-group">
                <strong>Low-conviction states</strong>
                ${infoButton("Situazioni in cui il bot non vede abbastanza qualita per agire: spesso anticipano i punti dove si perde tempo o si forza il setup.")}
              </div>
            </div>
            ${compactList(
              summary.failure_analysis.low_conviction_states.slice(0, 4).map(item => `${item.symbol}: ${item.last_reason}`),
              "Nessuno stato di bassa convinzione rilevante."
            )}
          </div>
          <div class="card">
            <div class="label-row">
              <div class="label-group">
                <strong>Disciplina e violazioni</strong>
                ${infoButton("Legge i segnali di disciplina del desk, per esempio streak di perdite o guard rail che stanno intervenendo.")}
              </div>
            </div>
            ${compactList(
              summary.failure_analysis.discipline_violations.slice(0, 4),
              "Nessuna violazione di disciplina evidente nella sessione."
            )}
          </div>
          <div class="card">
            <div class="label-row">
              <div class="label-group">
                <strong>Anomalie di execution</strong>
                ${infoButton("Serve a vedere se ci sono state uscite di emergenza o slippage anomali che meritano review manuale.")}
              </div>
            </div>
            ${compactList(
              summary.failure_analysis.execution_anomalies.slice(0, 4).map(item => `${item.symbol}: ${item.title}`),
              "Nessuna anomalia di execution rilevata."
            )}
          </div>
        `;
        setBalancedGridColumns("failure-analysis", 4, 2);
        const failureCount =
          summary.failure_analysis.blocked_trades.length +
          summary.failure_analysis.low_conviction_states.length +
          summary.failure_analysis.discipline_violations.length +
          summary.failure_analysis.execution_anomalies.length;
        document.getElementById("journal-failure-count").textContent = `${failureCount} focus`;
      }

      document.querySelectorAll(".tab-btn").forEach(button => {
        button.addEventListener("click", () => setActiveTab(button.dataset.tab));
      });
      try {
        setActiveTab(window.localStorage.getItem("deskActiveTab") || "overview");
      } catch (error) {
        setActiveTab("overview");
      }

      document.getElementById("provider-form").addEventListener("submit", updateProvider);
      document.getElementById("wallet-form").addEventListener("submit", updateWalletAccount);
      document.getElementById("wallet-connect-metamask").addEventListener("click", connectMetaMask);
      document.getElementById("wallet-prefill-hyperliquid").addEventListener("click", prefillHyperliquidSetup);
      document.getElementById("wallet-sync-all").addEventListener("click", syncAllWalletAccounts);
      document.getElementById("manual-import-form").addEventListener("submit", updateManualImport);
      document.getElementById("daily-review-form").addEventListener("submit", saveDailyReview);
      document.getElementById("import-example-csv").addEventListener("click", () => loadImportExample("csv"));
      document.getElementById("import-example-json").addEventListener("click", () => loadImportExample("json"));
      document.getElementById("import-clear").addEventListener("click", clearImportForm);
      restoreOverviewPanels();
      document.getElementById("overview-expand-all").addEventListener("click", () => setAllOverviewPanels(false));
      document.getElementById("overview-collapse-all").addEventListener("click", () => setAllOverviewPanels(true));
      document.querySelectorAll(".overview-toggle").forEach(button => {
        button.addEventListener("click", () => {
          const panelName = button.dataset.overviewPanelToggle;
          const panel = document.querySelector(`[data-overview-panel="${panelName}"]`);
          const collapsed = !panel || !panel.classList.contains("is-collapsed") ? true : false;
          setOverviewPanelCollapsed(panelName, collapsed);
        });
      });
      document.querySelectorAll(".overview-nav").forEach(button => {
        button.addEventListener("click", () => jumpToOverviewPanel(button.dataset.overviewJump));
      });
      restoreJournalPanels();
      document.getElementById("journal-expand-all").addEventListener("click", () => setAllJournalPanels(false));
      document.getElementById("journal-collapse-all").addEventListener("click", () => setAllJournalPanels(true));
      document.querySelectorAll(".section-toggle").forEach(button => {
        button.addEventListener("click", () => {
          const panelName = button.dataset.panel;
          const panel = document.querySelector(`[data-journal-panel="${panelName}"]`);
          const collapsed = !panel || !panel.classList.contains("is-collapsed") ? true : false;
          setJournalPanelCollapsed(panelName, collapsed);
        });
      });
      document.querySelectorAll(".journal-nav").forEach(button => {
        button.addEventListener("click", () => jumpToJournalPanel(button.dataset.jump));
      });
      document.body.addEventListener("click", event => {
        const marketButton = event.target.closest(".market-tab");
        if (marketButton && marketButton.dataset.marketSymbol) {
          setSelectedMarketSymbol(marketButton.dataset.marketSymbol);
          loadSummary();
          return;
        }
        const button = event.target.closest(".info-btn");
        if (button && button.dataset.info) {
          openInfo(button.dataset.info);
        }
      });
      document.getElementById("modal-close").addEventListener("click", closeInfo);
      document.getElementById("info-modal").addEventListener("click", event => {
        if (event.target.id === "info-modal") {
          closeInfo();
        }
      });
      document.addEventListener("keydown", event => {
        if (event.key === "Escape") {
          closeInfo();
        }
      });

      loadSummary();
      setInterval(loadSummary, 5000);
    </script>
  </body>
</html>
"""


def create_dashboard_app(config: AppConfig, storage: TradingStorage) -> Flask:
    storage.init_db()
    app = Flask(__name__)

    @app.get("/")
    def dashboard() -> str:
        return render_template_string(PAGE_TEMPLATE)

    @app.get("/favicon.ico")
    def favicon() -> Response:
        return Response(status=204)

    @app.get("/api/summary")
    def summary():
        return jsonify(
            storage.build_dashboard_summary(
                symbols=config.monitored_symbols,
                paper_start_balance=config.paper_start_balance,
                candles_interval_minutes=config.candles_interval_minutes,
            )
        )

    @app.post("/api/provider")
    def change_provider():
        payload = request.get_json(silent=True) or {}
        provider_key = str(payload.get("provider", "")).strip().upper()
        if provider_key not in PROVIDER_PROFILES:
            return jsonify({"ok": False, "message": "Provider non riconosciuto."}), 400

        if storage.get_open_position_count() > 0:
            return (
                jsonify(
                    {
                        "ok": False,
                        "message": "Chiudi prima le posizioni aperte: cambiare profilo fee a meta trade falserebbe i conti.",
                    }
                ),
                409,
            )

        profile = get_provider_profile(provider_key)
        for key, value in provider_state_items(profile).items():
            storage.set_state(key, value)
        storage.log_event(
            "INFO",
            "dashboard",
            f"Provider commissioni aggiornato a {profile.label}",
            {
                "provider_key": profile.key,
                "maker_fee_rate": profile.maker_fee_rate,
                "taker_fee_rate": profile.taker_fee_rate,
            },
        )
        return jsonify(
            {
                "ok": True,
                "message": f"Simulazione aggiornata su {profile.label}. Le nuove fee si applicheranno ai prossimi trade.",
            }
        )

    @app.post("/api/review/note")
    def save_review_note():
        payload = request.get_json(silent=True) or {}
        verdict = str(payload.get("verdict", "da_rivedere")).strip() or "da_rivedere"
        note = str(payload.get("note", "")).strip()
        review_date = str(payload.get("review_date", "")).strip() or local_day_key()
        if verdict not in {
            "setup_chiari",
            "bot_troppo_cauto",
            "costi_pesanti",
            "da_rivedere",
        }:
            return jsonify({"ok": False, "message": "Verdetto review non valido."}), 400

        storage.upsert_review_annotation(
            review_date=review_date,
            verdict=verdict,
            note=note,
        )
        storage.log_ledger_event(
            event_type="daily_review_note",
            title="Review giornaliera aggiornata",
            mode="PAPER",
            reference_type="review_date",
            reference_id=review_date,
            payload={
                "verdict": verdict,
                "note_length": len(note),
            },
        )
        storage.log_event(
            "INFO",
            "dashboard",
            "Review giornaliera salvata",
            {"review_date": review_date, "verdict": verdict},
        )
        return jsonify(
            {
                "ok": True,
                "message": "Review giornaliera salvata in locale.",
            }
        )

    @app.post("/api/wallet/register")
    def register_wallet():
        payload = request.get_json(silent=True) or {}
        label = str(payload.get("label", "")).strip()
        wallet_key = str(payload.get("wallet_key", "")).strip().upper()
        venue_key = str(payload.get("venue_key", "")).strip().upper()
        chain_key = str(payload.get("chain_key", "")).strip().upper()
        mode = str(payload.get("mode", "WATCH")).strip().upper() or "WATCH"
        address = str(payload.get("address", "")).strip()
        notes = str(payload.get("notes", "")).strip()
        source = str(payload.get("source", "manual")).strip().lower() or "manual"

        if not label:
            return jsonify({"ok": False, "message": "Inserisci una label wallet."}), 400
        if wallet_key not in WALLET_PROFILES:
            return jsonify({"ok": False, "message": "Wallet non riconosciuto."}), 400
        if venue_key not in VENUE_PROFILES:
            return jsonify({"ok": False, "message": "Venue on-chain non riconosciuta."}), 400
        if chain_key not in CHAIN_PROFILES:
            return jsonify({"ok": False, "message": "Chain non riconosciuta."}), 400
        if mode not in {"WATCH", "SHADOW_PREP", "API_PREP", "LIVE_PREP"}:
            return jsonify({"ok": False, "message": "Modalita wallet non valida."}), 400

        try:
            normalized_address = _normalize_wallet_address(address)
        except ValueError as exc:
            return jsonify({"ok": False, "message": str(exc)}), 400

        wallet = WALLET_PROFILES[wallet_key]
        venue = VENUE_PROFILES[venue_key]
        if chain_key not in wallet.supported_chain_keys:
            return (
                jsonify(
                    {
                        "ok": False,
                        "message": f"{wallet.label} non supporta la chain selezionata in questo progetto.",
                    }
                ),
                400,
            )
        if venue.wallet_keys and wallet_key not in venue.wallet_keys:
            return (
                jsonify(
                    {
                        "ok": False,
                        "message": f"{wallet.label} non e il wallet giusto per {venue.label}.",
                    }
                ),
                400,
            )
        if venue.chain_keys and chain_key not in venue.chain_keys:
            return (
                jsonify(
                    {
                        "ok": False,
                        "message": f"La chain selezionata non combacia con il venue {venue.label}.",
                    }
                ),
                400,
            )

        account_key = _wallet_account_key(label, wallet_key, normalized_address)
        result = storage.upsert_wallet_account(
            account_key=account_key,
            label=label,
            wallet_key=wallet_key,
            address=normalized_address,
            chain_key=chain_key,
            venue_key=venue_key,
            mode=mode,
            notes=notes,
            source=source,
        )
        storage.log_event(
            "INFO",
            "dashboard",
            f"Wallet registrato: {label}",
            {
                "account_key": account_key,
                "wallet_key": wallet_key,
                "venue_key": venue_key,
                "chain_key": chain_key,
                "mode": mode,
                "source": source,
            },
        )
        return jsonify(
            {
                "ok": True,
                "message": f"Wallet registrato: {label} su {venue.label}.",
                "wallet_account": result,
            }
        )

    @app.post("/api/wallet/sync")
    def sync_wallet():
        payload = request.get_json(silent=True) or {}
        account_key = str(payload.get("account_key", "")).strip()
        if not account_key:
            return jsonify({"ok": False, "message": "Account key wallet mancante."}), 400

        account = storage.get_wallet_account(account_key)
        if not account:
            return jsonify({"ok": False, "message": "Wallet non trovato."}), 404

        browser_snapshot = payload.get("browser_snapshot")
        try:
            if isinstance(browser_snapshot, dict) and browser_snapshot:
                result = build_metamask_snapshot(account, browser_snapshot)
            else:
                result = sync_registered_wallet(account)
            updated = storage.update_wallet_sync(
                account_key=account_key,
                sync_status=result.status,
                snapshot=result.snapshot,
                sync_error="",
            )
            storage.log_event(
                "INFO",
                "dashboard",
                f"Wallet sincronizzato: {account['label']}",
                {
                    "account_key": account_key,
                    "wallet_key": account["wallet_key"],
                    "venue_key": account["venue_key"],
                    "sync_status": result.status,
                    "snapshot_kind": result.snapshot.get("snapshot_kind"),
                },
            )
            storage.log_ledger_event(
                event_type="wallet_sync",
                title=f"Wallet sincronizzato: {account['label']}",
                mode="SHADOW",
                reference_type="wallet_account",
                reference_id=account_key,
                payload={
                    "wallet_key": account["wallet_key"],
                    "venue_key": account["venue_key"],
                    "chain_key": account["chain_key"],
                    "snapshot_kind": result.snapshot.get("snapshot_kind"),
                    "summary": result.snapshot.get("summary"),
                },
            )
            return jsonify(
                {
                    "ok": True,
                    "message": result.snapshot.get("summary") or f"Wallet sincronizzato: {account['label']}.",
                    "wallet_account": updated,
                    "snapshot": result.snapshot,
                }
            )
        except WalletSyncError as exc:
            storage.update_wallet_sync(
                account_key=account_key,
                sync_status="ERROR",
                snapshot=None,
                sync_error=str(exc),
            )
            storage.log_event(
                "WARNING",
                "dashboard",
                f"Sync wallet fallita: {account['label']}",
                {
                    "account_key": account_key,
                    "wallet_key": account["wallet_key"],
                    "venue_key": account["venue_key"],
                    "error": str(exc),
                },
            )
            return jsonify({"ok": False, "message": str(exc)}), 400
        except Exception as exc:
            storage.update_wallet_sync(
                account_key=account_key,
                sync_status="ERROR",
                snapshot=None,
                sync_error=str(exc),
            )
            storage.log_event(
                "ERROR",
                "dashboard",
                f"Errore imprevisto nella sync wallet: {account['label']}",
                {
                    "account_key": account_key,
                    "wallet_key": account["wallet_key"],
                    "venue_key": account["venue_key"],
                    "error": str(exc),
                },
            )
            return jsonify(
                {
                    "ok": False,
                    "message": "Sync wallet non riuscita. Controlla il browser wallet o la venue selezionata.",
                }
            ), 500

    @app.post("/api/import/manual")
    def manual_import():
        payload = request.get_json(silent=True) or {}
        account_label = str(payload.get("account_label", "")).strip()
        provider_key = str(payload.get("provider_key", "")).strip().upper()
        format_name = str(payload.get("format", "csv")).strip().lower()
        base_currency = str(payload.get("base_currency", "EUR")).strip().upper() or "EUR"
        notes = str(payload.get("notes", "")).strip()
        raw_text = str(payload.get("raw_text", ""))

        if not account_label:
            return jsonify({"ok": False, "message": "Inserisci un nome account."}), 400
        if provider_key not in PROVIDER_PROFILES:
            return jsonify({"ok": False, "message": "Provider import non riconosciuto."}), 400

        try:
            rows = _parse_manual_import(format_name, raw_text)
        except (ValueError, json.JSONDecodeError) as exc:
            return jsonify({"ok": False, "message": str(exc)}), 400

        account_key = _account_key(account_label, provider_key)
        result = storage.replace_external_account_events(
            account_key=account_key,
            label=account_label,
            provider_key=provider_key,
            base_currency=base_currency,
            import_mode=f"manual_{format_name}",
            notes=notes,
            rows=rows,
        )
        storage.log_event(
            "INFO",
            "dashboard",
            f"Import manuale completato per {account_label}",
            {
                "account_key": account_key,
                "provider_key": provider_key,
                "row_count": len(rows),
                "format": format_name,
            },
        )
        return jsonify(
            {
                "ok": True,
                "message": f"Import completato: {len(rows)} righe per {account_label}.",
                "account": result,
            }
        )

    @app.post("/api/wallet/delete")
    def delete_wallet():
        payload = request.get_json(silent=True) or {}
        account_key = str(payload.get("account_key", "")).strip()
        if not account_key:
            return jsonify({"ok": False, "message": "Account key wallet mancante."}), 400
        deleted = storage.delete_wallet_account(account_key)
        if not deleted:
            return jsonify({"ok": False, "message": "Wallet non trovato."}), 404
        storage.log_event(
            "INFO",
            "dashboard",
            f"Wallet rimosso: {deleted['label']}",
            {
                "account_key": deleted["account_key"],
                "wallet_key": deleted["wallet_key"],
                "venue_key": deleted["venue_key"],
            },
        )
        return jsonify(
            {
                "ok": True,
                "message": f"Wallet rimosso: {deleted['label']}.",
            }
        )

    @app.post("/api/import/delete")
    def delete_manual_import():
        payload = request.get_json(silent=True) or {}
        account_key = str(payload.get("account_key", "")).strip()
        if not account_key:
            return jsonify({"ok": False, "message": "Account key mancante."}), 400
        deleted = storage.delete_external_account(account_key)
        if not deleted:
            return jsonify({"ok": False, "message": "Account importato non trovato."}), 404
        storage.log_event(
            "INFO",
            "dashboard",
            f"Account importato rimosso: {deleted['label']}",
            {
                "account_key": deleted["account_key"],
                "provider_key": deleted["provider_key"],
            },
        )
        return jsonify(
            {
                "ok": True,
                "message": f"Account importato rimosso: {deleted['label']}.",
            }
        )

    return app
