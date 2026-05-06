from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

from trading_bot.blockchain import (
    get_chain_profile,
    get_venue_profile,
    get_wallet_profile,
    list_chain_profiles,
    list_venue_profiles,
    list_wallet_profiles,
    recommend_onchain_stack,
)
from trading_bot.onchain_sync import describe_sync_capability
from trading_bot.providers import get_provider_profile, list_provider_profiles, serialize_provider


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def parse_iso8601(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def local_day_key(value: str | None = None) -> str:
    if value is None:
        return datetime.now().astimezone().date().isoformat()
    return parse_iso8601(value).astimezone().date().isoformat()


class TradingStorage:
    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.db_path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode = WAL")
        connection.execute("PRAGMA synchronous = NORMAL")
        try:
            yield connection
            connection.commit()
        finally:
            connection.close()

    def init_db(self) -> None:
        with self.connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS bot_state (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS order_book_snapshots (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    symbol TEXT NOT NULL,
                    fetched_at TEXT NOT NULL,
                    source_timestamp TEXT,
                    best_bid REAL,
                    best_ask REAL,
                    mid_price REAL,
                    spread REAL,
                    raw_json TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_order_book_snapshots_symbol_fetched_at
                ON order_book_snapshots(symbol, fetched_at DESC);

                CREATE TABLE IF NOT EXISTS order_book_levels (
                    snapshot_id INTEGER NOT NULL,
                    side TEXT NOT NULL,
                    level_no INTEGER NOT NULL,
                    price REAL NOT NULL,
                    quantity REAL NOT NULL,
                    raw_json TEXT NOT NULL,
                    PRIMARY KEY (snapshot_id, side, level_no),
                    FOREIGN KEY(snapshot_id) REFERENCES order_book_snapshots(id)
                );

                CREATE TABLE IF NOT EXISTS public_trades (
                    trade_id TEXT PRIMARY KEY,
                    symbol TEXT NOT NULL,
                    trade_timestamp TEXT NOT NULL,
                    fetched_at TEXT NOT NULL,
                    price REAL NOT NULL,
                    quantity REAL NOT NULL,
                    raw_json TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_public_trades_symbol_trade_timestamp
                ON public_trades(symbol, trade_timestamp DESC);

                CREATE TABLE IF NOT EXISTS market_candles (
                    symbol TEXT NOT NULL,
                    interval_minutes INTEGER NOT NULL,
                    start_ms INTEGER NOT NULL,
                    open REAL NOT NULL,
                    high REAL NOT NULL,
                    low REAL NOT NULL,
                    close REAL NOT NULL,
                    volume REAL NOT NULL,
                    fetched_at TEXT NOT NULL,
                    PRIMARY KEY (symbol, interval_minutes, start_ms)
                );

                CREATE INDEX IF NOT EXISTS idx_market_candles_symbol_interval_start
                ON market_candles(symbol, interval_minutes, start_ms DESC);

                CREATE TABLE IF NOT EXISTS signals (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    symbol TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    strategy TEXT NOT NULL,
                    action TEXT NOT NULL,
                    score REAL NOT NULL,
                    reason TEXT NOT NULL,
                    details_json TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS strategy_analysis (
                    symbol TEXT PRIMARY KEY,
                    updated_at TEXT NOT NULL,
                    strategy TEXT NOT NULL,
                    status TEXT NOT NULL,
                    action TEXT NOT NULL,
                    reason TEXT NOT NULL,
                    details_json TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS paper_positions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    symbol TEXT NOT NULL,
                    quote_currency TEXT NOT NULL,
                    status TEXT NOT NULL,
                    side TEXT NOT NULL,
                    strategy TEXT NOT NULL,
                    opened_at TEXT NOT NULL,
                    closed_at TEXT,
                    quantity REAL NOT NULL,
                    entry_price REAL NOT NULL,
                    entry_notional REAL NOT NULL,
                    entry_fee REAL NOT NULL,
                    exit_price REAL,
                    exit_notional REAL,
                    exit_fee REAL,
                    realized_pnl REAL,
                    open_reason TEXT NOT NULL,
                    close_reason TEXT
                );

                CREATE INDEX IF NOT EXISTS idx_paper_positions_symbol_status
                ON paper_positions(symbol, status);

                CREATE TABLE IF NOT EXISTS events_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    created_at TEXT NOT NULL,
                    level TEXT NOT NULL,
                    source TEXT NOT NULL,
                    message TEXT NOT NULL,
                    details_json TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS equity_snapshots (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    created_at TEXT NOT NULL,
                    cash REAL NOT NULL,
                    realized_pnl REAL NOT NULL,
                    unrealized_pnl REAL NOT NULL,
                    equity REAL NOT NULL,
                    open_positions INTEGER NOT NULL,
                    exposure_notional REAL NOT NULL,
                    exposure_pct REAL NOT NULL,
                    daily_realized_pnl REAL NOT NULL,
                    daily_fees REAL NOT NULL,
                    trading_enabled INTEGER NOT NULL,
                    guardrail_status TEXT NOT NULL,
                    kill_switch_reason TEXT,
                    cooldown_until TEXT
                );

                CREATE INDEX IF NOT EXISTS idx_equity_snapshots_created_at
                ON equity_snapshots(created_at DESC);

                CREATE TABLE IF NOT EXISTS daily_reports (
                    report_date TEXT PRIMARY KEY,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    summary_json TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS review_annotations (
                    review_date TEXT PRIMARY KEY,
                    verdict TEXT NOT NULL,
                    note TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS analysis_daily_counters (
                    report_date TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    filter_code TEXT NOT NULL,
                    count INTEGER NOT NULL,
                    last_status TEXT NOT NULL,
                    last_action TEXT NOT NULL,
                    last_reason TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY (report_date, symbol, filter_code)
                );

                CREATE TABLE IF NOT EXISTS event_ledger (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    created_at TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    level TEXT NOT NULL,
                    mode TEXT NOT NULL,
                    symbol TEXT,
                    title TEXT NOT NULL,
                    reference_type TEXT,
                    reference_id TEXT,
                    payload_json TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_event_ledger_created_at
                ON event_ledger(created_at DESC);

                CREATE INDEX IF NOT EXISTS idx_event_ledger_event_type
                ON event_ledger(event_type, created_at DESC);

                CREATE TABLE IF NOT EXISTS decision_replay (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    created_at TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    mode TEXT NOT NULL,
                    status TEXT NOT NULL,
                    action TEXT NOT NULL,
                    reason TEXT NOT NULL,
                    decisive_rule TEXT,
                    filter_code TEXT NOT NULL,
                    signal_present INTEGER NOT NULL,
                    payload_json TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_decision_replay_created_at
                ON decision_replay(created_at DESC);

                CREATE INDEX IF NOT EXISTS idx_decision_replay_symbol
                ON decision_replay(symbol, created_at DESC);

                CREATE TABLE IF NOT EXISTS external_accounts (
                    account_key TEXT PRIMARY KEY,
                    label TEXT NOT NULL,
                    provider_key TEXT NOT NULL,
                    base_currency TEXT NOT NULL,
                    import_mode TEXT NOT NULL,
                    status TEXT NOT NULL,
                    notes TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    last_import_at TEXT
                );

                CREATE TABLE IF NOT EXISTS external_account_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    account_key TEXT NOT NULL,
                    imported_at TEXT NOT NULL,
                    event_time TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    symbol TEXT,
                    side TEXT,
                    quantity REAL,
                    price REAL,
                    notional REAL,
                    fee REAL,
                    currency TEXT,
                    raw_json TEXT NOT NULL,
                    FOREIGN KEY(account_key) REFERENCES external_accounts(account_key)
                );

                CREATE INDEX IF NOT EXISTS idx_external_account_events_account_time
                ON external_account_events(account_key, event_time DESC);

                CREATE TABLE IF NOT EXISTS wallet_accounts (
                    account_key TEXT PRIMARY KEY,
                    label TEXT NOT NULL,
                    wallet_key TEXT NOT NULL,
                    address TEXT NOT NULL,
                    chain_key TEXT NOT NULL,
                    venue_key TEXT NOT NULL,
                    mode TEXT NOT NULL,
                    status TEXT NOT NULL,
                    notes TEXT NOT NULL,
                    source TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    last_connected_at TEXT
                );

                CREATE INDEX IF NOT EXISTS idx_wallet_accounts_updated_at
                ON wallet_accounts(updated_at DESC);
                """
            )
            self._ensure_column(connection, "paper_positions", "entry_context_json", "TEXT")
            self._ensure_column(connection, "paper_positions", "exit_context_json", "TEXT")
            self._ensure_column(connection, "wallet_accounts", "last_sync_at", "TEXT")
            self._ensure_column(connection, "wallet_accounts", "sync_status", "TEXT")
            self._ensure_column(connection, "wallet_accounts", "sync_error", "TEXT")
            self._ensure_column(connection, "wallet_accounts", "sync_snapshot_json", "TEXT")

    def _ensure_column(
        self, connection: sqlite3.Connection, table: str, column: str, definition: str
    ) -> None:
        existing = {
            row["name"]
            for row in connection.execute(f"PRAGMA table_info({table})").fetchall()
        }
        if column in existing:
            return
        try:
            connection.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")
        except sqlite3.OperationalError as exc:
            if "duplicate column name" not in str(exc).lower():
                raise

    def set_state(self, key: str, value: str) -> None:
        now = utc_now_iso()
        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO bot_state(key, value, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(key) DO UPDATE SET
                    value = excluded.value,
                    updated_at = excluded.updated_at
                """,
                (key, value, now),
            )

    def get_state(self, key: str, default: str | None = None) -> str | None:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT value FROM bot_state WHERE key = ?",
                (key,),
            ).fetchone()
        return row["value"] if row else default

    def get_all_state(self) -> dict[str, str]:
        with self.connect() as connection:
            rows = connection.execute("SELECT key, value FROM bot_state").fetchall()
        return {row["key"]: row["value"] for row in rows}

    def log_event(
        self,
        level: str,
        source: str,
        message: str,
        details: dict[str, Any] | None = None,
    ) -> None:
        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO events_log(created_at, level, source, message, details_json)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    utc_now_iso(),
                    level.upper(),
                    source,
                    message,
                    json.dumps(details or {}, ensure_ascii=True),
                ),
            )

    def log_ledger_event(
        self,
        *,
        event_type: str,
        title: str,
        mode: str = "PAPER",
        level: str = "INFO",
        symbol: str | None = None,
        reference_type: str | None = None,
        reference_id: str | int | None = None,
        payload: dict[str, Any] | None = None,
    ) -> None:
        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO event_ledger(
                    created_at, event_type, level, mode, symbol, title,
                    reference_type, reference_id, payload_json
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    utc_now_iso(),
                    event_type,
                    level.upper(),
                    mode.upper(),
                    symbol,
                    title,
                    reference_type,
                    str(reference_id) if reference_id is not None else None,
                    json.dumps(payload or {}, ensure_ascii=True),
                ),
            )

    def get_recent_ledger_events(self, limit: int = 50) -> list[dict[str, Any]]:
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT *
                FROM event_ledger
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [
            {
                **dict(row),
                "payload": self._parse_json(row["payload_json"]),
            }
            for row in rows
        ]

    def get_recent_review_ledger_events(self, limit: int = 30) -> list[dict[str, Any]]:
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT *
                FROM event_ledger
                WHERE event_type != 'replay_snapshot_reference'
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [
            {
                **dict(row),
                "payload": self._parse_json(row["payload_json"]),
            }
            for row in rows
        ]

    def record_decision_replay(
        self,
        *,
        symbol: str,
        mode: str,
        status: str,
        action: str,
        reason: str,
        decisive_rule: str | None,
        filter_code: str,
        signal_present: bool,
        payload: dict[str, Any] | None = None,
    ) -> None:
        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO decision_replay(
                    created_at, symbol, mode, status, action, reason,
                    decisive_rule, filter_code, signal_present, payload_json
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    utc_now_iso(),
                    symbol,
                    mode.upper(),
                    status,
                    action,
                    reason,
                    decisive_rule,
                    filter_code,
                    1 if signal_present else 0,
                    json.dumps(payload or {}, ensure_ascii=True),
                ),
            )

    def get_recent_decision_replay(self, limit: int = 40) -> list[dict[str, Any]]:
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT *
                FROM decision_replay
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [
            {
                **dict(row),
                "signal_present": bool(row["signal_present"]),
                "payload": self._parse_json(row["payload_json"]),
            }
            for row in rows
        ]

    def replace_external_account_events(
        self,
        *,
        account_key: str,
        label: str,
        provider_key: str,
        base_currency: str,
        import_mode: str,
        notes: str,
        rows: list[dict[str, Any]],
    ) -> dict[str, Any]:
        now = utc_now_iso()
        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO external_accounts(
                    account_key, label, provider_key, base_currency, import_mode, status,
                    notes, created_at, updated_at, last_import_at
                )
                VALUES (?, ?, ?, ?, ?, 'ACTIVE', ?, ?, ?, ?)
                ON CONFLICT(account_key) DO UPDATE SET
                    label = excluded.label,
                    provider_key = excluded.provider_key,
                    base_currency = excluded.base_currency,
                    import_mode = excluded.import_mode,
                    status = 'ACTIVE',
                    notes = excluded.notes,
                    updated_at = excluded.updated_at,
                    last_import_at = excluded.last_import_at
                """,
                (
                    account_key,
                    label,
                    provider_key,
                    base_currency,
                    import_mode,
                    notes,
                    now,
                    now,
                    now,
                ),
            )
            connection.execute(
                "DELETE FROM external_account_events WHERE account_key = ?",
                (account_key,),
            )
            for item in rows:
                connection.execute(
                    """
                    INSERT INTO external_account_events(
                        account_key, imported_at, event_time, event_type, symbol, side,
                        quantity, price, notional, fee, currency, raw_json
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        account_key,
                        now,
                        item["event_time"],
                        item["event_type"],
                        item.get("symbol"),
                        item.get("side"),
                        item.get("quantity"),
                        item.get("price"),
                        item.get("notional"),
                        item.get("fee"),
                        item.get("currency"),
                        json.dumps(item, ensure_ascii=True),
                    ),
                )
        self.log_ledger_event(
            event_type="manual_import",
            title=f"Import manuale aggiornato per {label}",
            mode="SHADOW",
            reference_type="external_account",
            reference_id=account_key,
            payload={
                "provider_key": provider_key,
                "row_count": len(rows),
                "import_mode": import_mode,
            },
        )
        return {
            "account_key": account_key,
            "label": label,
            "provider_key": provider_key,
            "row_count": len(rows),
            "last_import_at": now,
        }

    def get_external_accounts_summary(self) -> list[dict[str, Any]]:
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT
                    a.account_key,
                    a.label,
                    a.provider_key,
                    a.base_currency,
                    a.import_mode,
                    a.status,
                    a.notes,
                    a.created_at,
                    a.updated_at,
                    a.last_import_at,
                    COUNT(e.id) AS event_count,
                    SUM(CASE WHEN e.event_type = 'trade' THEN 1 ELSE 0 END) AS trade_count,
                    SUM(CASE WHEN e.event_type = 'deposit' THEN 1 ELSE 0 END) AS deposit_count,
                    SUM(CASE WHEN e.event_type = 'withdrawal' THEN 1 ELSE 0 END) AS withdrawal_count,
                    SUM(CASE WHEN e.event_type = 'fee' THEN 1 ELSE 0 END) AS fee_event_count,
                    COALESCE(SUM(CASE WHEN e.event_type = 'trade' THEN ABS(COALESCE(e.notional, 0.0)) ELSE 0.0 END), 0.0) AS trade_notional_total,
                    COALESCE(SUM(CASE WHEN e.event_type = 'deposit' THEN COALESCE(e.notional, 0.0) ELSE 0.0 END), 0.0) AS deposit_total,
                    COALESCE(SUM(CASE WHEN e.event_type = 'withdrawal' THEN COALESCE(e.notional, 0.0) ELSE 0.0 END), 0.0) AS withdrawal_total,
                    COALESCE(SUM(CASE WHEN e.event_type = 'trade' AND e.side = 'BUY' THEN COALESCE(e.notional, 0.0) ELSE 0.0 END), 0.0) AS buy_notional_total,
                    COALESCE(SUM(CASE WHEN e.event_type = 'trade' AND e.side = 'SELL' THEN COALESCE(e.notional, 0.0) ELSE 0.0 END), 0.0) AS sell_notional_total,
                    COALESCE(SUM(COALESCE(e.fee, 0.0)), 0.0) AS fee_total,
                    MAX(e.event_time) AS last_event_time
                FROM external_accounts a
                LEFT JOIN external_account_events e ON e.account_key = a.account_key
                GROUP BY
                    a.account_key, a.label, a.provider_key, a.base_currency,
                    a.import_mode, a.status, a.notes, a.created_at, a.updated_at, a.last_import_at
                ORDER BY a.updated_at DESC
                """
            ).fetchall()
        summary: list[dict[str, Any]] = []
        for row in rows:
            provider_key = str(row["provider_key"])
            try:
                provider_label = get_provider_profile(provider_key).label
            except KeyError:
                provider_label = provider_key
            summary.append(
                {
                    **dict(row),
                    "provider_label": provider_label,
                    "event_count": int(row["event_count"] or 0),
                    "trade_count": int(row["trade_count"] or 0),
                    "deposit_count": int(row["deposit_count"] or 0),
                    "withdrawal_count": int(row["withdrawal_count"] or 0),
                    "fee_event_count": int(row["fee_event_count"] or 0),
                    "trade_notional_total": float(row["trade_notional_total"] or 0.0),
                    "deposit_total": float(row["deposit_total"] or 0.0),
                    "withdrawal_total": float(row["withdrawal_total"] or 0.0),
                    "buy_notional_total": float(row["buy_notional_total"] or 0.0),
                    "sell_notional_total": float(row["sell_notional_total"] or 0.0),
                    "net_transfer_total": float(row["deposit_total"] or 0.0)
                    - float(row["withdrawal_total"] or 0.0),
                    "net_trade_flow_total": float(row["sell_notional_total"] or 0.0)
                    - float(row["buy_notional_total"] or 0.0),
                    "fee_total": float(row["fee_total"] or 0.0),
                }
            )
        return summary

    def get_external_account_recent_events(self, limit: int = 20) -> list[dict[str, Any]]:
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT
                    e.id,
                    e.account_key,
                    e.imported_at,
                    e.event_time,
                    e.event_type,
                    e.symbol,
                    e.side,
                    e.quantity,
                    e.price,
                    e.notional,
                    e.fee,
                    e.currency,
                    e.raw_json,
                    a.label,
                    a.provider_key
                FROM external_account_events e
                JOIN external_accounts a ON a.account_key = e.account_key
                ORDER BY e.event_time DESC, e.id DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        events: list[dict[str, Any]] = []
        for row in rows:
            provider_key = str(row["provider_key"])
            try:
                provider_label = get_provider_profile(provider_key).label
            except KeyError:
                provider_label = provider_key
            events.append(
                {
                    **dict(row),
                    "provider_label": provider_label,
                    "raw": self._parse_json(row["raw_json"]),
                }
            )
        return events

    def delete_external_account(self, account_key: str) -> dict[str, Any] | None:
        with self.connect() as connection:
            existing = connection.execute(
                """
                SELECT account_key, label, provider_key
                FROM external_accounts
                WHERE account_key = ?
                """,
                (account_key,),
            ).fetchone()
            if not existing:
                return None
            connection.execute(
                "DELETE FROM external_account_events WHERE account_key = ?",
                (account_key,),
            )
            connection.execute(
                "DELETE FROM external_accounts WHERE account_key = ?",
                (account_key,),
            )
        payload = dict(existing)
        self.log_ledger_event(
            event_type="manual_import_delete",
            title=f"Account importato rimosso: {payload['label']}",
            mode="SHADOW",
            reference_type="external_account",
            reference_id=account_key,
            payload=payload,
        )
        return payload

    def upsert_wallet_account(
        self,
        *,
        account_key: str,
        label: str,
        wallet_key: str,
        address: str,
        chain_key: str,
        venue_key: str,
        mode: str,
        notes: str,
        source: str,
    ) -> dict[str, Any]:
        now = utc_now_iso()
        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO wallet_accounts(
                    account_key, label, wallet_key, address, chain_key, venue_key,
                    mode, status, notes, source, created_at, updated_at, last_connected_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, 'ACTIVE', ?, ?, ?, ?, ?)
                ON CONFLICT(account_key) DO UPDATE SET
                    label = excluded.label,
                    wallet_key = excluded.wallet_key,
                    address = excluded.address,
                    chain_key = excluded.chain_key,
                    venue_key = excluded.venue_key,
                    mode = excluded.mode,
                    status = 'ACTIVE',
                    notes = excluded.notes,
                    source = excluded.source,
                    updated_at = excluded.updated_at,
                    last_connected_at = excluded.last_connected_at
                """,
                (
                    account_key,
                    label,
                    wallet_key,
                    address,
                    chain_key,
                    venue_key,
                    mode,
                    notes,
                    source,
                    now,
                    now,
                    now,
                ),
            )
        self.log_ledger_event(
            event_type="wallet_register",
            title=f"Wallet registrato: {label}",
            mode="SHADOW",
            reference_type="wallet_account",
            reference_id=account_key,
            payload={
                "wallet_key": wallet_key,
                "chain_key": chain_key,
                "venue_key": venue_key,
                "mode": mode,
                "source": source,
            },
        )
        return {
            "account_key": account_key,
            "label": label,
            "wallet_key": wallet_key,
            "address": address,
            "chain_key": chain_key,
            "venue_key": venue_key,
            "mode": mode,
            "last_connected_at": now,
        }

    def get_wallet_accounts_summary(self) -> list[dict[str, Any]]:
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT *
                FROM wallet_accounts
                ORDER BY updated_at DESC
                """
            ).fetchall()
        summary: list[dict[str, Any]] = []
        for row in rows:
            wallet = get_wallet_profile(str(row["wallet_key"]))
            chain = get_chain_profile(str(row["chain_key"]))
            venue = get_venue_profile(str(row["venue_key"]))
            mode = str(row["mode"])
            snapshot = self._parse_json(row["sync_snapshot_json"])
            sync_capability = describe_sync_capability(
                {
                    **dict(row),
                    "chain_is_evm": chain.is_evm,
                }
            )
            execution_ready = (
                venue.live_supported
                and wallet.api_wallet_supported
                and mode in {"API_PREP", "LIVE_PREP"}
            )
            shadow_ready = venue.shadow_supported and mode in {
                "WATCH",
                "SHADOW_PREP",
                "LIVE_PREP",
                "API_PREP",
            }
            summary.append(
                {
                    **dict(row),
                    "wallet_label": wallet.label,
                    "wallet_type": wallet.wallet_type,
                    "wallet_browser_injected": wallet.browser_injected,
                    "wallet_api_supported": wallet.api_wallet_supported,
                    "chain_label": chain.label,
                    "chain_ecosystem": chain.ecosystem,
                    "chain_is_evm": chain.is_evm,
                    "venue_label": venue.label,
                    "venue_type": venue.venue_type,
                    "venue_execution_style": venue.execution_style,
                    "venue_short_supported": venue.short_supported,
                    "venue_live_supported": venue.live_supported,
                    "venue_shadow_supported": venue.shadow_supported,
                    "venue_gasless_trading": venue.gasless_trading,
                    "venue_fee_hint": venue.fee_hint,
                    "execution_ready": execution_ready,
                    "shadow_ready": shadow_ready,
                    "last_sync_at": row["last_sync_at"],
                    "sync_status": row["sync_status"] or "PENDING",
                    "sync_error": row["sync_error"] or "",
                    "sync_snapshot": snapshot,
                    "sync_capability": sync_capability["key"],
                    "sync_capability_label": sync_capability["label"],
                    "sync_capability_note": sync_capability["note"],
                    "sync_summary": snapshot.get("summary") or "Ancora nessuno snapshot wallet.",
                    "sync_headline": snapshot.get("headline") or "Snapshot assente",
                }
            )
        return summary

    def get_wallet_account(self, account_key: str) -> dict[str, Any] | None:
        with self.connect() as connection:
            row = connection.execute(
                """
                SELECT *
                FROM wallet_accounts
                WHERE account_key = ?
                """,
                (account_key,),
            ).fetchone()
        if not row:
            return None
        wallet = get_wallet_profile(str(row["wallet_key"]))
        chain = get_chain_profile(str(row["chain_key"]))
        venue = get_venue_profile(str(row["venue_key"]))
        return {
            **dict(row),
            "wallet_label": wallet.label,
            "chain_label": chain.label,
            "chain_is_evm": chain.is_evm,
            "chain_id": chain.chain_id,
            "venue_label": venue.label,
        }

    def update_wallet_sync(
        self,
        *,
        account_key: str,
        sync_status: str,
        snapshot: dict[str, Any] | None = None,
        sync_error: str = "",
    ) -> dict[str, Any] | None:
        existing = self.get_wallet_account(account_key)
        if not existing:
            return None
        now = utc_now_iso()
        with self.connect() as connection:
            if snapshot is None:
                connection.execute(
                    """
                    UPDATE wallet_accounts
                    SET sync_status = ?, sync_error = ?, last_sync_at = ?, updated_at = ?
                    WHERE account_key = ?
                    """,
                    (
                        sync_status,
                        sync_error,
                        now,
                        now,
                        account_key,
                    ),
                )
            else:
                connection.execute(
                    """
                    UPDATE wallet_accounts
                    SET sync_status = ?, sync_error = ?, sync_snapshot_json = ?, last_sync_at = ?, updated_at = ?
                    WHERE account_key = ?
                    """,
                    (
                        sync_status,
                        sync_error,
                        json.dumps(snapshot, ensure_ascii=True),
                        now,
                        now,
                        account_key,
                    ),
                )
        return self.get_wallet_account(account_key)

    def delete_wallet_account(self, account_key: str) -> dict[str, Any] | None:
        with self.connect() as connection:
            existing = connection.execute(
                """
                SELECT account_key, label, wallet_key, venue_key, chain_key
                FROM wallet_accounts
                WHERE account_key = ?
                """,
                (account_key,),
            ).fetchone()
            if not existing:
                return None
            connection.execute(
                "DELETE FROM wallet_accounts WHERE account_key = ?",
                (account_key,),
            )
        payload = dict(existing)
        self.log_ledger_event(
            event_type="wallet_delete",
            title=f"Wallet rimosso: {payload['label']}",
            mode="SHADOW",
            reference_type="wallet_account",
            reference_id=account_key,
            payload=payload,
        )
        return payload

    def insert_order_book_snapshot(self, symbol: str, payload: dict[str, Any]) -> int:
        fetched_at = utc_now_iso()
        data = payload.get("data", {})
        asks = data.get("asks", [])
        bids = data.get("bids", [])
        best_ask = float(asks[0]["p"]) if asks else None
        best_bid = float(bids[0]["p"]) if bids else None
        mid_price = (
            (best_bid + best_ask) / 2
            if best_bid is not None and best_ask is not None
            else None
        )
        spread = (
            best_ask - best_bid
            if best_bid is not None and best_ask is not None
            else None
        )
        source_timestamp = None
        if asks:
            source_timestamp = asks[0].get("pdt")
        elif bids:
            source_timestamp = bids[0].get("pdt")

        with self.connect() as connection:
            cursor = connection.execute(
                """
                INSERT INTO order_book_snapshots(
                    symbol, fetched_at, source_timestamp, best_bid, best_ask, mid_price, spread, raw_json
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    symbol,
                    fetched_at,
                    source_timestamp,
                    best_bid,
                    best_ask,
                    mid_price,
                    spread,
                    json.dumps(payload, ensure_ascii=True),
                ),
            )
            snapshot_id = int(cursor.lastrowid)
            for side, levels in (("bid", bids), ("ask", asks)):
                for index, level in enumerate(levels, start=1):
                    connection.execute(
                        """
                        INSERT INTO order_book_levels(snapshot_id, side, level_no, price, quantity, raw_json)
                        VALUES (?, ?, ?, ?, ?, ?)
                        """,
                        (
                            snapshot_id,
                            side,
                            index,
                            float(level["p"]),
                            float(level["q"]),
                            json.dumps(level, ensure_ascii=True),
                        ),
                    )
        return snapshot_id

    def insert_public_trades(self, payload: dict[str, Any]) -> int:
        fetched_at = utc_now_iso()
        trades = payload.get("data", [])
        inserted = 0
        with self.connect() as connection:
            for trade in trades:
                symbol = f"{trade['aid']}-{trade['pc']}"
                cursor = connection.execute(
                    """
                    INSERT OR IGNORE INTO public_trades(
                        trade_id, symbol, trade_timestamp, fetched_at, price, quantity, raw_json
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        trade["tid"],
                        symbol,
                        trade.get("tdt") or trade.get("pdt") or fetched_at,
                        fetched_at,
                        float(trade["p"]),
                        float(trade["q"]),
                        json.dumps(trade, ensure_ascii=True),
                    ),
                )
                inserted += cursor.rowcount
        return inserted

    def insert_candles(
        self,
        *,
        symbol: str,
        interval_minutes: int,
        payload: dict[str, Any],
    ) -> int:
        fetched_at = utc_now_iso()
        inserted = 0
        with self.connect() as connection:
            for candle in payload.get("data", []):
                cursor = connection.execute(
                    """
                    INSERT INTO market_candles(
                        symbol, interval_minutes, start_ms, open, high, low, close, volume, fetched_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(symbol, interval_minutes, start_ms) DO UPDATE SET
                        open = excluded.open,
                        high = excluded.high,
                        low = excluded.low,
                        close = excluded.close,
                        volume = excluded.volume,
                        fetched_at = excluded.fetched_at
                    """,
                    (
                        symbol,
                        interval_minutes,
                        int(candle["start"]),
                        float(candle["open"]),
                        float(candle["high"]),
                        float(candle["low"]),
                        float(candle["close"]),
                        float(candle["volume"]),
                        fetched_at,
                    ),
                )
                inserted += cursor.rowcount
        return inserted

    def get_recent_candles(
        self,
        symbol: str,
        interval_minutes: int,
        limit: int = 48,
    ) -> list[sqlite3.Row]:
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT *
                FROM market_candles
                WHERE symbol = ? AND interval_minutes = ?
                ORDER BY start_ms DESC
                LIMIT ?
                """,
                (symbol, interval_minutes, limit),
            ).fetchall()
        return rows

    def upsert_strategy_analysis(
        self,
        symbol: str,
        *,
        strategy: str,
        status: str,
        action: str,
        reason: str,
        details: dict[str, Any],
    ) -> None:
        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO strategy_analysis(symbol, updated_at, strategy, status, action, reason, details_json)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(symbol) DO UPDATE SET
                    updated_at = excluded.updated_at,
                    strategy = excluded.strategy,
                    status = excluded.status,
                    action = excluded.action,
                    reason = excluded.reason,
                    details_json = excluded.details_json
                """,
                (
                    symbol,
                    utc_now_iso(),
                    strategy,
                    status,
                    action,
                    reason,
                    json.dumps(details, ensure_ascii=True),
                ),
            )

    def get_strategy_analysis(self, symbol: str) -> dict[str, Any] | None:
        with self.connect() as connection:
            row = connection.execute(
                """
                SELECT *
                FROM strategy_analysis
                WHERE symbol = ?
                """,
                (symbol,),
            ).fetchone()
        if not row:
            return None
        details = json.loads(row["details_json"])
        return {
            "updated_at": row["updated_at"],
            "strategy": row["strategy"],
            "status": row["status"],
            "action": row["action"],
            "reason": row["reason"],
            "details": details,
        }

    def get_recent_snapshots(self, symbol: str, limit: int = 10) -> list[sqlite3.Row]:
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT *
                FROM order_book_snapshots
                WHERE symbol = ?
                ORDER BY fetched_at DESC
                LIMIT ?
                """,
                (symbol, limit),
            ).fetchall()
        return rows

    def get_latest_snapshot(self, symbol: str) -> sqlite3.Row | None:
        rows = self.get_recent_snapshots(symbol, limit=1)
        return rows[0] if rows else None

    def get_order_book_levels(
        self,
        snapshot_id: int,
        side: str,
        limit: int = 10,
    ) -> list[sqlite3.Row]:
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT *
                FROM order_book_levels
                WHERE snapshot_id = ? AND side = ?
                ORDER BY level_no ASC
                LIMIT ?
                """,
                (snapshot_id, side, limit),
            ).fetchall()
        return rows

    def get_trade_activity(self, symbol: str, limit: int = 20) -> dict[str, Any]:
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT trade_timestamp, price, quantity
                FROM public_trades
                WHERE symbol = ?
                ORDER BY trade_timestamp DESC
                LIMIT ?
                """,
                (symbol, limit),
            ).fetchall()
        if not rows:
            return {
                "count": 0,
                "last_trade_at": None,
                "last_price": None,
                "recent_volume": 0.0,
            }
        return {
            "count": len(rows),
            "last_trade_at": rows[0]["trade_timestamp"],
            "last_price": rows[0]["price"],
            "recent_volume": sum(float(row["quantity"]) for row in rows),
        }

    def record_signal(
        self,
        symbol: str,
        strategy: str,
        action: str,
        score: float,
        reason: str,
        details: dict[str, Any] | None = None,
    ) -> None:
        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO signals(symbol, created_at, strategy, action, score, reason, details_json)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    symbol,
                    utc_now_iso(),
                    strategy,
                    action,
                    score,
                    reason,
                    json.dumps(details or {}, ensure_ascii=True),
                ),
            )

    def get_open_position(self, symbol: str) -> sqlite3.Row | None:
        with self.connect() as connection:
            row = connection.execute(
                """
                SELECT *
                FROM paper_positions
                WHERE symbol = ? AND status = 'OPEN'
                ORDER BY opened_at DESC
                LIMIT 1
                """,
                (symbol,),
            ).fetchone()
        return row

    def get_open_positions(self) -> list[sqlite3.Row]:
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT *
                FROM paper_positions
                WHERE status = 'OPEN'
                ORDER BY opened_at DESC
                """
            ).fetchall()
        return rows

    def open_position(
        self,
        *,
        symbol: str,
        quote_currency: str,
        side: str,
        strategy: str,
        quantity: float,
        entry_price: float,
        entry_notional: float,
        entry_fee: float,
        open_reason: str,
        entry_context: dict[str, Any] | None = None,
    ) -> int:
        with self.connect() as connection:
            cursor = connection.execute(
                """
                INSERT INTO paper_positions(
                    symbol, quote_currency, status, side, strategy, opened_at,
                    quantity, entry_price, entry_notional, entry_fee, open_reason, entry_context_json
                )
                VALUES (?, ?, 'OPEN', ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    symbol,
                    quote_currency,
                    side,
                    strategy,
                    utc_now_iso(),
                    quantity,
                    entry_price,
                    entry_notional,
                    entry_fee,
                    open_reason,
                    json.dumps(entry_context or {}, ensure_ascii=True),
                ),
            )
            return int(cursor.lastrowid)

    def close_position(
        self,
        *,
        position_id: int,
        exit_price: float,
        exit_notional: float,
        exit_fee: float,
        realized_pnl: float,
        close_reason: str,
        exit_context: dict[str, Any] | None = None,
    ) -> None:
        with self.connect() as connection:
            connection.execute(
                """
                UPDATE paper_positions
                SET status = 'CLOSED',
                    closed_at = ?,
                    exit_price = ?,
                    exit_notional = ?,
                    exit_fee = ?,
                    realized_pnl = ?,
                    close_reason = ?,
                    exit_context_json = ?
                WHERE id = ?
                """,
                (
                    utc_now_iso(),
                    exit_price,
                    exit_notional,
                    exit_fee,
                    realized_pnl,
                    close_reason,
                    json.dumps(exit_context or {}, ensure_ascii=True),
                    position_id,
                ),
            )

    def get_recent_signals(self, limit: int = 20) -> list[sqlite3.Row]:
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT *
                FROM signals
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return rows

    def get_recent_events(self, limit: int = 20) -> list[sqlite3.Row]:
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT *
                FROM events_log
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return rows

    def get_recent_operational_events(self, limit: int = 20) -> list[sqlite3.Row]:
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT *
                FROM events_log
                WHERE NOT (
                    source = 'public_bot'
                    AND level = 'INFO'
                    AND message = 'Ciclo bot completato'
                )
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return rows

    def upsert_review_annotation(
        self,
        *,
        review_date: str,
        verdict: str,
        note: str,
    ) -> None:
        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO review_annotations(review_date, verdict, note, updated_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(review_date) DO UPDATE SET
                    verdict = excluded.verdict,
                    note = excluded.note,
                    updated_at = excluded.updated_at
                """,
                (review_date, verdict, note, utc_now_iso()),
            )

    def get_review_annotation(self, review_date: str | None = None) -> dict[str, Any] | None:
        target_date = review_date or local_day_key()
        with self.connect() as connection:
            row = connection.execute(
                """
                SELECT review_date, verdict, note, updated_at
                FROM review_annotations
                WHERE review_date = ?
                """,
                (target_date,),
            ).fetchone()
        return dict(row) if row else None

    def get_recent_positions(self, limit: int = 20) -> list[sqlite3.Row]:
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT *
                FROM paper_positions
                ORDER BY opened_at DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return rows

    def get_closed_pnl_sum(self) -> float:
        with self.connect() as connection:
            row = connection.execute(
                """
                SELECT COALESCE(SUM(realized_pnl), 0.0) AS total
                FROM paper_positions
                WHERE status = 'CLOSED'
                """
            ).fetchone()
        return float(row["total"])

    def get_open_position_count(self) -> int:
        with self.connect() as connection:
            row = connection.execute(
                """
                SELECT COUNT(*) AS total
                FROM paper_positions
                WHERE status = 'OPEN'
                """
            ).fetchone()
        return int(row["total"])

    def get_fee_totals(self) -> dict[str, float]:
        with self.connect() as connection:
            row = connection.execute(
                """
                SELECT
                    COALESCE(SUM(entry_fee), 0.0) AS entry_total,
                    COALESCE(SUM(COALESCE(exit_fee, 0.0)), 0.0) AS exit_total,
                    COALESCE(SUM(entry_fee + COALESCE(exit_fee, 0.0)), 0.0) AS grand_total
                FROM paper_positions
                """
            ).fetchone()
        return {
            "entry_total": float(row["entry_total"]),
            "exit_total": float(row["exit_total"]),
            "grand_total": float(row["grand_total"]),
        }

    def get_recent_equity_snapshots(self, limit: int = 240) -> list[sqlite3.Row]:
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT *
                FROM equity_snapshots
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return rows

    def upsert_daily_report(self, report_date: str, summary: dict[str, Any]) -> None:
        now = utc_now_iso()
        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO daily_reports(report_date, created_at, updated_at, summary_json)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(report_date) DO UPDATE SET
                    updated_at = excluded.updated_at,
                    summary_json = excluded.summary_json
                """,
                (
                    report_date,
                    now,
                    now,
                    json.dumps(summary, ensure_ascii=True),
                ),
            )

    def get_recent_daily_reports(self, limit: int = 60) -> list[dict[str, Any]]:
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT report_date, created_at, updated_at, summary_json
                FROM daily_reports
                ORDER BY report_date DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        reports: list[dict[str, Any]] = []
        for row in rows:
            try:
                summary = json.loads(row["summary_json"])
            except json.JSONDecodeError:
                summary = {}
            reports.append(
                {
                    "report_date": row["report_date"],
                    "created_at": row["created_at"],
                    "updated_at": row["updated_at"],
                    "summary": summary,
                }
            )
        return reports

    def increment_analysis_counter(
        self,
        *,
        symbol: str,
        filter_code: str,
        status: str,
        action: str,
        reason: str,
    ) -> None:
        report_date = local_day_key()
        now = utc_now_iso()
        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO analysis_daily_counters(
                    report_date, symbol, filter_code, count, last_status, last_action, last_reason, updated_at
                )
                VALUES (?, ?, ?, 1, ?, ?, ?, ?)
                ON CONFLICT(report_date, symbol, filter_code) DO UPDATE SET
                    count = analysis_daily_counters.count + 1,
                    last_status = excluded.last_status,
                    last_action = excluded.last_action,
                    last_reason = excluded.last_reason,
                    updated_at = excluded.updated_at
                """,
                (report_date, symbol, filter_code, status, action, reason, now),
            )

    def get_analysis_filter_summary(self, days: int = 7) -> dict[str, Any]:
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT
                    filter_code,
                    SUM(count) AS total_count,
                    COUNT(DISTINCT symbol) AS symbol_count,
                    MAX(updated_at) AS last_seen_at
                FROM analysis_daily_counters
                WHERE report_date >= date('now', ?)
                GROUP BY filter_code
                ORDER BY total_count DESC, filter_code ASC
                """,
                (f"-{max(days - 1, 0)} day",),
            ).fetchall()
            today_rows = connection.execute(
                """
                SELECT symbol, filter_code, count, last_status, last_action, last_reason, updated_at
                FROM analysis_daily_counters
                WHERE report_date = date('now')
                ORDER BY count DESC, symbol ASC, filter_code ASC
                """
            ).fetchall()
        return {
            "window_days": days,
            "aggregate": [
                {
                    "filter_code": row["filter_code"],
                    "total_count": int(row["total_count"]),
                    "symbol_count": int(row["symbol_count"]),
                    "last_seen_at": row["last_seen_at"],
                }
                for row in rows
            ],
            "today_by_symbol": [dict(row) for row in today_rows],
        }

    def record_equity_snapshot(
        self,
        *,
        symbols: list[str],
        paper_start_balance: float,
    ) -> dict[str, Any]:
        metrics = self.build_runtime_metrics(
            symbols=symbols,
            paper_start_balance=paper_start_balance,
        )
        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO equity_snapshots(
                    created_at, cash, realized_pnl, unrealized_pnl, equity,
                    open_positions, exposure_notional, exposure_pct, daily_realized_pnl,
                    daily_fees, trading_enabled, guardrail_status, kill_switch_reason,
                    cooldown_until
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    utc_now_iso(),
                    metrics["cash"],
                    metrics["realized_pnl"],
                    metrics["unrealized_pnl"],
                    metrics["equity"],
                    metrics["open_positions"],
                    metrics["current_exposure_eur"],
                    metrics["current_exposure_pct"],
                    metrics["today_realized_pnl"],
                    metrics["today_fees_total"],
                    1 if metrics["trading_enabled"] else 0,
                    metrics["guardrail_status"],
                    metrics["kill_reason"],
                    metrics["cooldown_until"],
                ),
            )
        return metrics

    def _parse_position_context(self, value: Any) -> dict[str, Any]:
        if value in (None, ""):
            return {}
        try:
            return json.loads(value)
        except (TypeError, json.JSONDecodeError):
            return {}

    def _parse_json(self, value: Any) -> dict[str, Any]:
        if value in (None, ""):
            return {}
        try:
            return json.loads(value)
        except (TypeError, json.JSONDecodeError):
            return {}

    def _hydrate_position_row(self, row: sqlite3.Row) -> dict[str, Any]:
        item = dict(row)
        item["entry_context"] = self._parse_position_context(item.get("entry_context_json"))
        item["exit_context"] = self._parse_position_context(item.get("exit_context_json"))
        return item

    def get_hydrated_positions(self, limit: int = 5000) -> list[dict[str, Any]]:
        return [self._hydrate_position_row(row) for row in self.get_recent_positions(limit=limit)]

    def _build_account_live_metrics(
        self,
        *,
        state: dict[str, str],
        symbols: list[str],
        starting_balance: float,
    ) -> dict[str, Any]:
        cash = float(state.get("paper_cash", str(starting_balance)))
        realized_pnl = self.get_closed_pnl_sum()
        provider = get_provider_profile(state.get("paper_provider_key"))
        current_exposure_eur = 0.0
        unrealized_total = 0.0
        reserved_margin_total = 0.0

        for position in self.get_open_positions():
            entry_context = self._parse_position_context(position["entry_context_json"])
            side = str(position["side"] or "LONG").upper()
            reserved_margin = float(
                entry_context.get("margin_reserved")
                or entry_context.get("margin_reserved_eur")
                or position["entry_notional"]
            )
            reserved_margin_total += reserved_margin
            snapshot = self.get_latest_snapshot(position["symbol"])
            if not snapshot:
                current_exposure_eur += float(position["entry_notional"])
                continue
            mark_price = snapshot["best_ask"] if side == "SHORT" else snapshot["best_bid"]
            if mark_price is None:
                current_exposure_eur += float(position["entry_notional"])
                continue
            mark_value = float(position["quantity"]) * float(mark_price)
            exit_fee = mark_value * provider.taker_fee_rate
            current_exposure_eur += mark_value
            if side == "SHORT":
                unrealized_total += (
                    float(position["entry_notional"])
                    - mark_value
                    - exit_fee
                )
            else:
                unrealized_total += (
                    mark_value
                    - float(position["entry_notional"])
                    - exit_fee
                )

        equity = cash + reserved_margin_total + unrealized_total
        exposure_pct = (current_exposure_eur / equity * 100.0) if equity > 0 else 0.0
        return {
            "starting_balance": starting_balance,
            "contributed_capital": float(
                state.get("paper_contributed_capital_total", str(starting_balance))
            ),
            "cash": cash,
            "realized_pnl": realized_pnl,
            "unrealized_pnl": unrealized_total,
            "equity": equity,
            "open_positions": self.get_open_position_count(),
            "current_exposure_eur": current_exposure_eur,
            "current_exposure_pct": exposure_pct,
            "reserved_margin_eur": reserved_margin_total,
            "provider_key": provider.key,
            "provider_label": provider.label,
            "portfolio_currency": state.get("portfolio_currency", symbols[0].split("-")[1]),
        }

    def _calculate_drawdown_metrics(
        self,
        *,
        starting_balance: float,
        current_equity: float,
    ) -> dict[str, float]:
        snapshots = list(reversed(self.get_recent_equity_snapshots(limit=1000)))
        peak = starting_balance
        max_drawdown_pct = 0.0
        current_drawdown_pct = 0.0
        today = local_day_key()
        today_peak = starting_balance
        today_max_drawdown_pct = 0.0

        for row in snapshots:
            equity = float(row["equity"])
            peak = max(peak, equity)
            drawdown_pct = ((equity - peak) / peak * 100.0) if peak > 0 else 0.0
            max_drawdown_pct = min(max_drawdown_pct, drawdown_pct)
            if local_day_key(row["created_at"]) == today:
                today_peak = max(today_peak, equity)
                today_drawdown = (
                    (equity - today_peak) / today_peak * 100.0 if today_peak > 0 else 0.0
                )
                today_max_drawdown_pct = min(today_max_drawdown_pct, today_drawdown)

        if peak > 0:
            current_drawdown_pct = ((current_equity - peak) / peak) * 100.0

        return {
            "current_drawdown_pct": current_drawdown_pct,
            "max_drawdown_pct": max_drawdown_pct,
            "today_max_drawdown_pct": today_max_drawdown_pct,
        }

    def _build_trade_statistics(self, positions: list[dict[str, Any]]) -> dict[str, Any]:
        closed = [
            item
            for item in positions
            if item["status"] == "CLOSED" and item.get("realized_pnl") is not None
        ]
        closed.sort(key=lambda item: item["closed_at"] or item["opened_at"])
        wins = [item for item in closed if float(item["realized_pnl"]) > 0]
        losses = [item for item in closed if float(item["realized_pnl"]) < 0]
        flat = [item for item in closed if float(item["realized_pnl"]) == 0]
        long_trades = [item for item in closed if str(item.get("side") or "").upper() == "LONG"]
        short_trades = [item for item in closed if str(item.get("side") or "").upper() == "SHORT"]
        gross_profit = sum(float(item["realized_pnl"]) for item in wins)
        gross_loss = abs(sum(float(item["realized_pnl"]) for item in losses))
        average_win = gross_profit / len(wins) if wins else 0.0
        average_loss = gross_loss / len(losses) if losses else 0.0
        expectancy = (
            sum(float(item["realized_pnl"]) for item in closed) / len(closed)
            if closed
            else 0.0
        )
        profit_factor = (gross_profit / gross_loss) if gross_loss > 0 else None
        total_hold_minutes = 0.0
        best_trade = None
        worst_trade = None
        entry_slippages: list[float] = []
        exit_slippages: list[float] = []
        rolling_loss_streak = 0

        for item in closed:
            if item["closed_at"]:
                total_hold_minutes += (
                    parse_iso8601(item["closed_at"]) - parse_iso8601(item["opened_at"])
                ).total_seconds() / 60.0
            pnl = float(item["realized_pnl"])
            best_trade = pnl if best_trade is None else max(best_trade, pnl)
            worst_trade = pnl if worst_trade is None else min(worst_trade, pnl)
            if pnl < 0:
                rolling_loss_streak += 1
            else:
                rolling_loss_streak = 0
            entry_context = item.get("entry_context", {})
            exit_context = item.get("exit_context", {})
            if isinstance(entry_context.get("slippage_pct"), (int, float)):
                entry_slippages.append(float(entry_context["slippage_pct"]))
            if isinstance(exit_context.get("slippage_pct"), (int, float)):
                exit_slippages.append(float(exit_context["slippage_pct"]))

        today_key = local_day_key()
        today_opened = [
            item for item in positions if local_day_key(item["opened_at"]) == today_key
        ]
        today_closed = [
            item
            for item in closed
            if item["closed_at"] and local_day_key(item["closed_at"]) == today_key
        ]
        today_closed.sort(key=lambda item: item["closed_at"] or item["opened_at"])
        today_consecutive_losses = 0
        for item in today_closed:
            if float(item["realized_pnl"]) < 0:
                today_consecutive_losses += 1
            else:
                today_consecutive_losses = 0
        today_realized_pnl = sum(float(item["realized_pnl"]) for item in today_closed)
        today_fees_total = (
            sum(float(item["entry_fee"]) for item in today_opened)
            + sum(float(item["exit_fee"] or 0.0) for item in today_closed)
        )

        return {
            "closed_trades": len(closed),
            "long_trades": len(long_trades),
            "short_trades": len(short_trades),
            "wins": len(wins),
            "losses": len(losses),
            "flat": len(flat),
            "win_rate_pct": (len(wins) / len(closed) * 100.0) if closed else 0.0,
            "gross_profit": gross_profit,
            "gross_loss": gross_loss,
            "average_win": average_win,
            "average_loss": average_loss,
            "expectancy": expectancy,
            "profit_factor": profit_factor,
            "best_trade": best_trade,
            "worst_trade": worst_trade,
            "average_hold_minutes": (total_hold_minutes / len(closed)) if closed else 0.0,
            "average_entry_slippage_pct": (
                sum(entry_slippages) / len(entry_slippages) if entry_slippages else 0.0
            ),
            "average_exit_slippage_pct": (
                sum(exit_slippages) / len(exit_slippages) if exit_slippages else 0.0
            ),
            "consecutive_losses": today_consecutive_losses,
            "rolling_loss_streak": rolling_loss_streak,
            "today_trade_count": len(today_opened),
            "today_realized_pnl": today_realized_pnl,
            "today_fees_total": today_fees_total,
        }

    def build_runtime_metrics(
        self,
        *,
        symbols: list[str],
        paper_start_balance: float,
    ) -> dict[str, Any]:
        state = self.get_all_state()
        starting_balance = float(state.get("paper_start_balance", str(paper_start_balance)))
        account = self._build_account_live_metrics(
            state=state,
            symbols=symbols,
            starting_balance=starting_balance,
        )
        positions = self.get_hydrated_positions(limit=5000)
        trade_stats = self._build_trade_statistics(positions)
        drawdowns = self._calculate_drawdown_metrics(
            starting_balance=starting_balance,
            current_equity=account["equity"],
        )
        kill_reason = state.get("paper_kill_switch_reason", "") or ""
        cooldown_until = state.get("paper_cooldown_until")
        trading_enabled = state.get("paper_trading_enabled", "true") == "true"
        guardrail_status = state.get(
            "paper_guardrail_status",
            "HARD_STOP" if kill_reason else "ATTIVO",
        )
        return {
            **account,
            **trade_stats,
            **drawdowns,
            "net_profit_after_contributions": account["equity"] - account["contributed_capital"],
            "return_on_contributed_capital_pct": (
                (
                    (account["equity"] - account["contributed_capital"])
                    / account["contributed_capital"]
                    * 100.0
                )
                if account["contributed_capital"] > 0
                else 0.0
            ),
            "kill_reason": kill_reason,
            "cooldown_until": cooldown_until if cooldown_until else None,
            "trading_enabled": trading_enabled,
            "guardrail_status": guardrail_status,
        }

    def _build_cost_attribution(self, positions: list[dict[str, Any]]) -> dict[str, Any]:
        fee_total = 0.0
        spread_cost_estimate = 0.0
        slippage_cost_estimate = 0.0

        for item in positions:
            entry_fee = float(item.get("entry_fee") or 0.0)
            exit_fee = float(item.get("exit_fee") or 0.0)
            fee_total += entry_fee + exit_fee

            quantity = float(item.get("quantity") or 0.0)
            entry_context = item.get("entry_context", {})
            exit_context = item.get("exit_context", {})
            side = str(item.get("side") or "LONG").upper()

            entry_reference = float(entry_context.get("reference_price") or 0.0)
            entry_average = float(entry_context.get("average_price") or 0.0)
            entry_mid = float(entry_context.get("mid_price") or 0.0)
            exit_reference = float(exit_context.get("reference_price") or 0.0)
            exit_average = float(exit_context.get("average_price") or 0.0)
            exit_mid = float(exit_context.get("mid_price") or 0.0)

            if quantity > 0 and entry_average > 0 and entry_reference > 0:
                if side == "SHORT":
                    slippage_cost_estimate += max(entry_reference - entry_average, 0.0) * quantity
                else:
                    slippage_cost_estimate += max(entry_average - entry_reference, 0.0) * quantity
            if quantity > 0 and exit_average > 0 and exit_reference > 0:
                if side == "SHORT":
                    slippage_cost_estimate += max(exit_average - exit_reference, 0.0) * quantity
                else:
                    slippage_cost_estimate += max(exit_reference - exit_average, 0.0) * quantity
            if quantity > 0 and entry_reference > 0 and entry_mid > 0:
                if side == "SHORT":
                    spread_cost_estimate += max(entry_mid - entry_reference, 0.0) * quantity
                else:
                    spread_cost_estimate += max(entry_reference - entry_mid, 0.0) * quantity
            if quantity > 0 and exit_reference > 0 and exit_mid > 0:
                if side == "SHORT":
                    spread_cost_estimate += max(exit_reference - exit_mid, 0.0) * quantity
                else:
                    spread_cost_estimate += max(exit_mid - exit_reference, 0.0) * quantity

        return {
            "fee_total_eur": fee_total,
            "spread_cost_estimate_eur": spread_cost_estimate,
            "slippage_cost_estimate_eur": slippage_cost_estimate,
            "estimated_total_cost_eur": fee_total + spread_cost_estimate + slippage_cost_estimate,
        }

    def _build_blockchain_summary(self, state: dict[str, str]) -> dict[str, Any]:
        wallet_accounts = self.get_wallet_accounts_summary()
        synced_count = sum(1 for item in wallet_accounts if item["sync_status"] == "SYNCED")
        sync_error_count = sum(1 for item in wallet_accounts if item["sync_status"] == "ERROR")
        sync_pending_count = sum(
            1 for item in wallet_accounts if item["sync_status"] not in {"SYNCED", "ERROR"}
        )
        required_inputs: list[dict[str, str]] = []
        if not wallet_accounts:
            required_inputs.append(
                {
                    "label": "Collega un wallet",
                    "detail": "Serve almeno un wallet MetaMask o un signer dedicato per attivare il layer blockchain del control plane.",
                }
            )
        if not any(item["wallet_key"] == "METAMASK_EXTENSION" for item in wallet_accounts):
            required_inputs.append(
                {
                    "label": "Aggiungi MetaMask",
                    "detail": "MetaMask e il punto di partenza migliore per wallet UX, watch account e conferme manuali EVM.",
                }
            )
        if not any(item["venue_key"] == "HYPERLIQUID" for item in wallet_accounts):
            required_inputs.append(
                {
                    "label": "Prepara la venue on-chain primaria",
                    "detail": "Per automazione seria, short e perps il primo venue consigliato resta Hyperliquid con API wallet.",
                }
            )
        if not any(item["execution_ready"] for item in wallet_accounts):
            required_inputs.append(
                {
                    "label": "Manca un signer automation-ready",
                    "detail": "Nessun wallet registrato e ancora pronto per live execution: per ora il layer blockchain resta in watch/shadow.",
                }
            )
        if wallet_accounts and synced_count == 0:
            required_inputs.append(
                {
                    "label": "Sincronizza almeno un wallet",
                    "detail": "Per trasformare il layer blockchain in qualcosa di utile serve almeno uno snapshot MetaMask o una sync venue-public completata.",
                }
            )

        return {
            "headline": (
                "Wallet connect e venue on-chain attivi in modalita control plane"
                if wallet_accounts
                else "Layer blockchain pronto, in attesa del primo wallet"
            ),
            "summary": (
                "MetaMask entra come wallet layer e UX EVM; la venue on-chain consigliata per automazione seria resta Hyperliquid. "
                "GMX e dYdX restano i candidati naturali per la fase successiva."
            ),
            "chains": list_chain_profiles(),
            "wallets": list_wallet_profiles(),
            "venues": list_venue_profiles(),
            "accounts": wallet_accounts,
            "recommended_stack": recommend_onchain_stack(),
            "required_inputs": required_inputs,
            "mode_note": (
                "Wallet browser e wallet API sono separati volutamente: il primo aiuta onboarding e controllo, il secondo serve quando vorremo execution vera."
            ),
            "primary_venue_key": "HYPERLIQUID",
            "wallet_watch_count": sum(1 for item in wallet_accounts if item["mode"] == "WATCH"),
            "execution_ready_count": sum(1 for item in wallet_accounts if item["execution_ready"]),
            "synced_count": synced_count,
            "sync_error_count": sync_error_count,
            "sync_pending_count": sync_pending_count,
        }

    def _build_supported_workflows(self, state: dict[str, str]) -> list[dict[str, str]]:
        provider_label = state.get("paper_provider_label", "Hyperliquid")
        return [
            {
                "title": f"{provider_label} paper e shadow",
                "description": (
                    f"{provider_label} e il venue operativo della alpha per market data, paper trading e decisioni shadow."
                ),
                "status": "ATTIVO",
            },
            {
                "title": "MetaMask watch e browser sync",
                "description": (
                    "Il browser puo collegare MetaMask, salvare snapshot EVM locali e usarli per capire saldo, chain e attivita del wallet."
                ),
                "status": "ATTIVO",
            },
            {
                "title": "Hyperliquid watch e API-wallet prep",
                "description": (
                    "Wallet o signer Hyperliquid possono essere sincronizzati via endpoint pubblici per watch, shadow e preparazione all'automazione."
                ),
                "status": "ATTIVO",
            },
            {
                "title": "Import manuale account esterni",
                "description": (
                    "Gli altri provider entrano solo via import manuale o supporto concierge per review e confronto."
                ),
                "status": "MANUALE",
            },
            {
                "title": "Review locale giornaliera",
                "description": (
                    "Ogni giornata produce una review locale con costi, regole intervenute e target da rivedere."
                ),
                "status": "ATTIVO",
            },
            {
                "title": "Decision replay locale",
                "description": (
                    "Le decisioni rilevanti vengono salvate per ricostruire cosa e successo e quale regola ha pesato."
                ),
                "status": "ATTIVO",
            },
            {
                "title": "Wallet blockchain e venue on-chain",
                "description": (
                    "MetaMask, signer dedicati e venue on-chain vengono registrati nell'account center per watch, shadow e preparazione al live."
                ),
                "status": "ATTIVO",
            },
        ]

    def _build_known_limitations(self) -> list[str]:
        return [
            "La live execution resta disabilitata in alpha: nessun ordine reale viene inviato dalla piattaforma.",
            "Il venue di default supporta short e perps; nella baseline corrente la alpha arma gia long e short in modalita paper, mentre il live resta spento.",
            "Niente multi-provider live reali: gli account esterni restano manuali/import.",
            "MetaMask e integrato come wallet layer e watch account, non come executor primario del bot.",
            "La sync MetaMask richiede che la dashboard sia aperta in un browser con estensione disponibile e permessi approvati.",
            "Il prodotto non salva private key o seed phrase: registriamo wallet, signer id e snapshot di stato, non segreti custodial.",
            "Venue on-chain come Hyperliquid, GMX e dYdX sono modellate nel control plane, ma oggi la venue operativa reale di default e Hyperliquid.",
            "Niente mobile app o app store in questa fase.",
            "Il prodotto non promette auto-execution o rendimento.",
        ]

    def _build_operating_modes(self, state: dict[str, str]) -> list[dict[str, Any]]:
        bot_mode = state.get("bot_mode", "PUBLIC_SIM")
        return [
            {
                "key": "PAPER",
                "label": "Paper",
                "enabled": True,
                "active": bot_mode == "PUBLIC_SIM",
                "description": "Il sistema simula ingressi e uscite con fee e slippage credibili.",
            },
            {
                "key": "SHADOW",
                "label": "Live Shadow",
                "enabled": True,
                "active": False,
                "description": "Le decisioni non eseguite vengono spiegate sul mercato live come modalita di controllo.",
            },
            {
                "key": "LIVE",
                "label": "Live",
                "enabled": False,
                "active": False,
                "description": "Disabilitato in alpha: nessun ordine reale viene inviato dalla piattaforma.",
            },
        ]

    def _build_alpha_onboarding_summary(
        self,
        *,
        state: dict[str, str],
        runtime: dict[str, Any],
        account_center: dict[str, Any],
        daily_review: dict[str, Any],
    ) -> dict[str, Any]:
        operational = account_center["operational_account"]
        replay_count = len(self.get_recent_decision_replay(limit=8))
        imported_accounts = account_center.get("imported_accounts", [])
        wallet_accounts = account_center.get("wallet_accounts", [])
        data_ready = (
            int(operational.get("order_book_records") or 0) > 50
            and int(operational.get("public_trade_records") or 0) > 100
        )
        checklist = [
            {
                "label": "Desk operativo locale",
                "status": "DONE" if state.get("bot_status") == "running" else "WAIT",
                "detail": (
                    f"Bot {state.get('bot_status', 'idle')} | ultimo ciclo {operational.get('last_cycle_at') or 'n/d'}."
                ),
            },
            {
                "label": "Raccolta dati minima",
                "status": "DONE" if data_ready else "WAIT",
                "detail": (
                    f"Snapshot book {operational.get('order_book_records', 0)} | trade pubblici {operational.get('public_trade_records', 0)}."
                ),
            },
            {
                "label": "Daily review disponibile",
                "status": "DONE" if daily_review.get("highlights") else "WAIT",
                "detail": daily_review.get("summary", "La review apparira dopo i primi cicli."),
            },
            {
                "label": "Decision replay popolato",
                "status": "DONE" if replay_count > 0 else "NEXT",
                "detail": (
                    f"{replay_count} eventi replay disponibili per spiegare perche il sistema ha agito o no."
                ),
            },
            {
                "label": "Import account esterni",
                "status": "DONE" if imported_accounts else "NEXT",
                "detail": (
                    f"{len(imported_accounts)} account importati per review/comparison."
                    if imported_accounts
                    else "Nessun account esterno importato ancora: pronto il flusso CSV/JSON."
                ),
            },
            {
                "label": "Wallet blockchain registrati",
                "status": "DONE" if wallet_accounts else "NEXT",
                "detail": (
                    f"{len(wallet_accounts)} wallet o signer registrati per il layer on-chain."
                    if wallet_accounts
                    else "Nessun wallet registrato ancora: puoi partire collegando MetaMask o preparando un signer dedicato."
                ),
            },
            {
                "label": "Trust layer dichiarato",
                "status": "DONE",
                "detail": "Paper, Live Shadow e Live sono separati e le limitazioni della alpha sono esplicite.",
            },
        ]
        completed = sum(1 for item in checklist if item["status"] == "DONE")
        readiness = "PRONTA PER DEMO INTERNA"
        if completed >= 5 and data_ready and replay_count > 0:
            readiness = "PRONTA PER DESIGN PARTNER ASSISTITI"
        next_steps = [
            {
                "title": "Apri Panoramica e leggi la Daily Review",
                "detail": "Il partner deve capire la giornata in meno di 3 minuti.",
            },
            {
                "title": "Mostra un Decision Replay",
                "detail": "Serve a far vedere che il sistema spiega chiaramente perche ha atteso o bloccato.",
            },
            {
                "title": "Conferma limiti e modalita operative",
                "detail": "Paper, Shadow e Live devono essere distinguibili a colpo d'occhio.",
            },
        ]
        if not imported_accounts:
            next_steps.append(
                {
                    "title": "Importa un account esterno demo",
                    "detail": "Usa il template CSV/JSON per mostrare review e confronto multi-account senza integrazione live.",
                }
            )
        else:
            next_steps.append(
                {
                    "title": "Rivedi un account importato",
                    "detail": "Confronta costi, fee e attivita recente dell'account esterno con il desk operativo.",
                }
            )
        if not wallet_accounts:
            next_steps.append(
                {
                    "title": "Collega MetaMask o registra un signer",
                    "detail": "Serve per mostrare il nuovo layer blockchain e preparare la venue on-chain primaria.",
                }
            )
        return {
            "headline": "Onboarding alpha",
            "summary": (
                "Questa alpha e pensata per spiegare cosa succede, perche succede e quanto costa, "
                "prima di parlare di automazione live."
            ),
            "readiness_label": readiness,
            "completed_steps": completed,
            "total_steps": len(checklist),
            "checklist": checklist,
            "next_steps": next_steps,
        }

    def _build_account_center_summary(
        self,
        *,
        state: dict[str, str],
        symbols: list[str],
        blockchain: dict[str, Any],
    ) -> dict[str, Any]:
        latest_order_book = 0
        latest_public_trades = 0
        with self.connect() as connection:
            latest_order_book = int(
                connection.execute(
                    "SELECT COUNT(*) AS total FROM order_book_snapshots"
                ).fetchone()["total"]
            )
            latest_public_trades = int(
                connection.execute(
                    "SELECT COUNT(*) AS total FROM public_trades"
                ).fetchone()["total"]
            )
        imported_accounts = self.get_external_accounts_summary()
        return {
            "operational_account": {
                "label": "Desk operativo locale",
                "provider_key": state.get(
                    "bot_market_data_provider_key",
                    state.get("paper_provider_key", "HYPERLIQUID"),
                ),
                "provider_label": state.get(
                    "bot_market_data_provider_label",
                    state.get("paper_provider_label", "Hyperliquid"),
                ),
                "status": state.get("bot_status", "idle"),
                "mode": state.get("bot_mode", "PUBLIC_SIM"),
                "last_cycle_at": state.get("bot_last_cycle_at"),
                "symbols": symbols,
                "order_book_records": latest_order_book,
                "public_trade_records": latest_public_trades,
            },
            "imported_accounts": imported_accounts,
            "wallet_accounts": blockchain["accounts"],
            "blockchain_recommended_stack": blockchain["recommended_stack"],
            "blockchain_required_inputs": blockchain["required_inputs"],
            "recent_import_events": self.get_external_account_recent_events(limit=18),
            "supported_import_formats": ["csv", "json"],
            "manual_import_schema": [
                "timestamp",
                "event_type",
                "symbol",
                "side",
                "quantity",
                "price",
                "notional",
                "fee",
                "currency",
                "notes",
            ],
        }

    def _build_daily_review(
        self,
        *,
        symbols: list[str],
        runtime: dict[str, Any],
        state: dict[str, str],
    ) -> dict[str, Any]:
        annotation = self.get_review_annotation() or {
            "review_date": local_day_key(),
            "verdict": "da_rivedere",
            "note": "",
            "updated_at": None,
        }
        filter_audit = self.get_analysis_filter_summary(days=1)
        top_filter = filter_audit["aggregate"][0] if filter_audit["aggregate"] else None
        review_targets: list[dict[str, Any]] = []
        rule_checks: list[dict[str, Any]] = []

        for symbol in symbols:
            analysis = self.get_strategy_analysis(symbol)
            if not analysis:
                continue
            details = analysis.get("details", {})
            review_targets.append(
                {
                    "symbol": symbol,
                    "status": analysis["status"],
                    "reason": analysis["reason"],
                    "next_condition": details.get("prossima_condizione"),
                }
            )

        review_targets = review_targets[:3]

        rule_checks.append(
            {
                "label": "Guard rail",
                "value": state.get("paper_guardrail_status", runtime["guardrail_status"]),
                "tone": "ok"
                if state.get("paper_guardrail_status", runtime["guardrail_status"]) == "ATTIVO"
                else "watch",
            }
        )
        rule_checks.append(
            {
                "label": "Posizioni aperte",
                "value": f"{runtime['open_positions']} / {state.get('risk_max_open_positions', '0')}",
                "tone": "ok" if runtime["open_positions"] == 0 else "watch",
            }
        )
        rule_checks.append(
            {
                "label": "Perdite consecutive",
                "value": str(runtime["consecutive_losses"]),
                "tone": "ok" if runtime["consecutive_losses"] == 0 else "watch",
            }
        )

        highlights = [
            {
                "title": "Stato desk",
                "body": (
                    "Il desk e operativo e puo continuare a osservare i setup."
                    if runtime["guardrail_status"] == "ATTIVO"
                    else (runtime["kill_reason"] or "Il desk sta applicando una pausa di sicurezza.")
                ),
                "tone": "ok" if runtime["guardrail_status"] == "ATTIVO" else "bad",
            },
            {
                "title": "Costo di giornata",
                "body": (
                    f"Fee registrate oggi {runtime['today_fees_total']:.2f} {runtime['portfolio_currency']} e "
                    f"PnL realizzato {runtime['today_realized_pnl']:.2f} {runtime['portfolio_currency']}."
                ),
                "tone": "watch"
                if runtime["today_fees_total"] > abs(runtime["today_realized_pnl"])
                else "ok",
            },
        ]
        if top_filter:
            highlights.append(
                {
                    "title": "Blocco dominante",
                    "body": (
                        f"Oggi il filtro dominante e {top_filter['filter_code']}, rilevato {top_filter['total_count']} volte su {top_filter['symbol_count']} simboli."
                    ),
                    "tone": "watch",
                }
            )

        return {
            "headline": "Review rapida della sessione",
            "summary": (
                "Chiudi la giornata guardando cosa e successo, quale regola ha contato di piu e quanto ti e costato il desk."
            ),
            "highlights": highlights[:3],
            "review_targets": review_targets,
            "rule_checks": rule_checks,
            "annotation": annotation,
            "closing_prompt": (
                "La giornata di oggi ti dice piu cose sul rischio, sui costi o sulla qualita dei setup?"
            ),
        }

    def _build_failure_analysis(
        self,
        *,
        runtime: dict[str, Any],
        positions: list[dict[str, Any]],
    ) -> dict[str, Any]:
        audit = self.get_analysis_filter_summary(days=7)
        blocked = [item for item in audit["today_by_symbol"] if item["last_status"] == "BLOCCATO"]
        low_conviction = [
            item for item in audit["today_by_symbol"] if item["last_status"] == "OSSERVAZIONE"
        ]
        anomalies = []
        for item in positions:
            exit_context = item.get("exit_context", {})
            entry_context = item.get("entry_context", {})
            if exit_context.get("fallback_used"):
                anomalies.append(
                    {
                        "symbol": item["symbol"],
                        "title": "Fallback di uscita",
                        "detail": "La profondita bid non bastava e l'uscita ha usato un prezzo di emergenza.",
                    }
                )
            elif float(exit_context.get("slippage_pct") or 0.0) > 0.12:
                anomalies.append(
                    {
                        "symbol": item["symbol"],
                        "title": "Slippage uscita elevato",
                        "detail": f"Uscita con slippage {float(exit_context.get('slippage_pct')):.3f}%.",
                    }
                )
            elif float(entry_context.get("slippage_pct") or 0.0) > 0.12:
                anomalies.append(
                    {
                        "symbol": item["symbol"],
                        "title": "Slippage ingresso elevato",
                        "detail": f"Ingresso con slippage {float(entry_context.get('slippage_pct')):.3f}%.",
                    }
                )

        discipline = []
        if runtime["consecutive_losses"] > 0:
            discipline.append(
                f"Perdite consecutive oggi: {runtime['consecutive_losses']}."
            )
        if runtime["guardrail_status"] != "ATTIVO":
            discipline.append(runtime["kill_reason"] or "Guard rail non attivo.")

        return {
            "blocked_trades": blocked[:5],
            "low_conviction_states": low_conviction[:5],
            "discipline_violations": discipline,
            "execution_anomalies": anomalies[:5],
            "shadow_live_divergence": {
                "available": False,
                "message": "La divergenza shadow/live vera arrivera quando attiveremo workflow live controllati.",
            },
        }

    def _build_journal_digest(
        self,
        *,
        signals: list[dict[str, Any]],
        events: list[dict[str, Any]],
        decision_replay: list[dict[str, Any]],
        ledger: list[dict[str, Any]],
        daily_review: dict[str, Any],
        failure_analysis: dict[str, Any],
    ) -> dict[str, Any]:
        verdict = str(daily_review.get("annotation", {}).get("verdict") or "da_rivedere")
        verdict_labels = {
            "setup_chiari": "Setup chiari",
            "bot_troppo_cauto": "Bot troppo cauto",
            "costi_pesanti": "Costi troppo pesanti",
            "da_rivedere": "Da rivedere",
        }
        verdict_summary = {
            "setup_chiari": "La sessione sembra leggibile: i blocchi e i setup sono comprensibili senza rumore eccessivo.",
            "bot_troppo_cauto": "Il Journal racconta una sessione prudente: utile per capire se i filtri stanno tagliando troppo.",
            "costi_pesanti": "La review va letta prima con la lente dei costi: fee, spread e slippage sono la priorita.",
            "da_rivedere": "Questa sessione richiede ancora lettura guidata prima di trarre conclusioni forti.",
        }
        note = str(daily_review.get("annotation", {}).get("note") or "").strip()
        blocked = failure_analysis.get("blocked_trades", [])
        low_conviction = failure_analysis.get("low_conviction_states", [])
        next_reads = [
            {
                "title": "Parti dalla nota di giornata",
                "detail": note if note else "Nessuna nota salvata ancora: usa il campo in Daily Review per fissare il contesto.",
            },
            {
                "title": "Apri il blocco principale",
                "detail": (
                    f"{blocked[0]['symbol']}: {blocked[0]['last_reason']}"
                    if blocked
                    else "Nessun blocco dominante: passa subito al replay decisionale."
                ),
            },
            {
                "title": "Controlla il replay piu recente",
                "detail": (
                    f"{decision_replay[0]['symbol']}: {decision_replay[0]['reason']}"
                    if decision_replay
                    else "Ancora nessun replay disponibile nella finestra recente."
                ),
            },
        ]
        if low_conviction:
            next_reads.append(
                {
                    "title": "Conferma la bassa convinzione",
                    "detail": f"{low_conviction[0]['symbol']}: {low_conviction[0]['last_reason']}",
                }
            )
        return {
            "headline": "Journal digest",
            "summary": verdict_summary.get(verdict, verdict_summary["da_rivedere"]),
            "scorecards": [
                {
                    "label": "Verdetto giornata",
                    "value": verdict_labels.get(verdict, "Da rivedere"),
                    "sub": daily_review.get("annotation", {}).get("updated_at") or "non salvato",
                    "tone": "watch" if verdict != "setup_chiari" else "ok",
                },
                {
                    "label": "Segnali recenti",
                    "value": str(len(signals)),
                    "sub": "letti nel journal",
                    "tone": "ok" if signals else "watch",
                },
                {
                    "label": "Replay disponibili",
                    "value": str(len(decision_replay)),
                    "sub": "decisioni spiegabili",
                    "tone": "ok" if decision_replay else "watch",
                },
                {
                    "label": "Eventi utili",
                    "value": str(len(events)),
                    "sub": "timeline operativa filtrata",
                    "tone": "ok" if events else "watch",
                },
                {
                    "label": "Ledger review",
                    "value": str(len(ledger)),
                    "sub": "eventi strutturati",
                    "tone": "ok" if ledger else "watch",
                },
                {
                    "label": "Failure focus",
                    "value": str(len(blocked) + len(low_conviction)),
                    "sub": "blocchi e stati deboli",
                    "tone": "watch" if blocked or low_conviction else "ok",
                },
            ],
            "next_reads": next_reads,
        }

    def build_daily_report_snapshot(
        self,
        *,
        symbols: list[str],
        paper_start_balance: float,
        candles_interval_minutes: int,
    ) -> dict[str, Any]:
        state = self.get_all_state()
        runtime = self.build_runtime_metrics(
            symbols=symbols,
            paper_start_balance=paper_start_balance,
        )
        positions = self.get_hydrated_positions(limit=5000)
        cost_attribution = self._build_cost_attribution(positions)
        blockchain = self._build_blockchain_summary(state)
        snapshot: dict[str, Any] = {
            "date": local_day_key(),
            "bot_status": state.get("bot_status", "idle"),
            "guardrail_status": state.get("paper_guardrail_status", runtime["guardrail_status"]),
            "equity_eur": runtime["equity"],
            "cash_eur": runtime["cash"],
            "contributed_capital_eur": runtime["contributed_capital"],
            "net_profit_after_contributions_eur": runtime["net_profit_after_contributions"],
            "return_on_contributed_capital_pct": runtime["return_on_contributed_capital_pct"],
            "realized_pnl_total_eur": runtime["realized_pnl"],
            "unrealized_pnl_eur": runtime["unrealized_pnl"],
            "daily_realized_pnl_eur": runtime["today_realized_pnl"],
            "daily_fees_eur": runtime["today_fees_total"],
            "open_positions": runtime["open_positions"],
            "closed_trades": runtime["closed_trades"],
            "win_rate_pct": runtime["win_rate_pct"],
            "expectancy_eur": runtime["expectancy"],
            "profit_factor": runtime["profit_factor"],
            "current_drawdown_pct": abs(min(runtime["current_drawdown_pct"], 0.0)),
            "today_max_drawdown_pct": abs(min(runtime["today_max_drawdown_pct"], 0.0)),
            "provider": state.get("paper_provider_label", "Hyperliquid"),
            "experiment": {
                "name": state.get("experiment_name", ""),
                "freeze_enabled": state.get("experiment_freeze_enabled", "false") == "true",
                "baseline_fingerprint": state.get("experiment_baseline_fingerprint"),
                "current_fingerprint": state.get("experiment_current_fingerprint"),
                "drift_detected": state.get("experiment_drift_detected", "false") == "true",
            },
            "capital_plan": {
                "recurring_enabled": state.get("paper_recurring_contribution_enabled", "false") == "true",
                "amount_eur": float(state.get("paper_recurring_contribution_amount", "0")),
                "frequency": state.get("paper_recurring_contribution_frequency", "monthly"),
                "start_mode": state.get("paper_recurring_contribution_start_mode", "next_period"),
                "last_contribution_at": state.get("paper_recurring_contribution_last_at"),
                "last_contribution_period": state.get("paper_last_contribution_period"),
            },
            "blockchain": blockchain,
            "account_center": self._build_account_center_summary(
                state=state,
                symbols=symbols,
                blockchain=blockchain,
            ),
            "cost_attribution": cost_attribution,
            "daily_review": self._build_daily_review(
                symbols=symbols,
                runtime=runtime,
                state=state,
            ),
            "filter_audit": self.get_analysis_filter_summary(days=1),
            "symbols": [],
        }
        for symbol in symbols:
            latest = self.get_latest_snapshot(symbol)
            analysis = self.get_strategy_analysis(symbol)
            snapshot["symbols"].append(
                {
                    "symbol": symbol,
                    "mid_price": latest["mid_price"] if latest else None,
                    "spread_bps": (
                        (latest["spread"] / latest["mid_price"]) * 10000
                        if latest and latest["spread"] is not None and latest["mid_price"]
                        else None
                    ),
                    "analysis_status": analysis["status"] if analysis else None,
                    "analysis_reason": analysis["reason"] if analysis else None,
                    "candle_count": len(
                        self.get_recent_candles(
                            symbol,
                            interval_minutes=candles_interval_minutes,
                            limit=48,
                        )
                    ),
                }
            )
        return snapshot

    def build_dashboard_summary(
        self,
        *,
        symbols: list[str],
        paper_start_balance: float,
        candles_interval_minutes: int,
    ) -> dict[str, Any]:
        state = self.get_all_state()
        runtime = self.build_runtime_metrics(
            symbols=symbols,
            paper_start_balance=paper_start_balance,
        )
        starting_balance = float(state.get("paper_start_balance", str(paper_start_balance)))
        fee_totals = self.get_fee_totals()
        provider = get_provider_profile(state.get("paper_provider_key"))
        hydrated_positions = self.get_hydrated_positions(limit=200)
        cost_attribution = self._build_cost_attribution(hydrated_positions)
        blockchain = self._build_blockchain_summary(state)
        account_center = self._build_account_center_summary(
            state=state,
            symbols=symbols,
            blockchain=blockchain,
        )
        daily_review = self._build_daily_review(
            symbols=symbols,
            runtime=runtime,
            state=state,
        )
        symbols_summary: list[dict[str, Any]] = []

        for symbol in symbols:
            snapshot = self.get_latest_snapshot(symbol)
            snapshots = list(reversed(self.get_recent_snapshots(symbol, limit=24)))
            candles = list(
                reversed(
                    self.get_recent_candles(
                        symbol,
                        interval_minutes=candles_interval_minutes,
                        limit=48,
                    )
                )
            )
            position = next(
                (item for item in hydrated_positions if item["symbol"] == symbol and item["status"] == "OPEN"),
                None,
            )
            analysis = self.get_strategy_analysis(symbol)
            trade_activity = self.get_trade_activity(symbol)
            latest = {
                "symbol": symbol,
                "snapshot_count": len(snapshots),
                "candle_count": len(candles),
                "best_bid": snapshot["best_bid"] if snapshot else None,
                "best_ask": snapshot["best_ask"] if snapshot else None,
                "mid_price": snapshot["mid_price"] if snapshot else None,
                "spread": snapshot["spread"] if snapshot else None,
                "spread_bps": (
                    (snapshot["spread"] / snapshot["mid_price"]) * 10000
                    if snapshot and snapshot["spread"] is not None and snapshot["mid_price"]
                    else None
                ),
                "updated_at": snapshot["fetched_at"] if snapshot else None,
                "mid_history": [
                    {
                        "ts": item["fetched_at"],
                        "mid": item["mid_price"],
                    }
                    for item in snapshots
                    if item["mid_price"] is not None
                ],
                "candle_history": [
                    {
                        "start_ms": item["start_ms"],
                        "open": item["open"],
                        "high": item["high"],
                        "low": item["low"],
                        "close": item["close"],
                        "volume": item["volume"],
                    }
                    for item in candles
                ],
                "trade_activity": trade_activity,
                "analysis": analysis,
                "position": None,
            }
            if position and snapshot:
                side = str(position["side"] or "LONG").upper()
                mark_price_value = snapshot["best_ask"] if side == "SHORT" else snapshot["best_bid"]
                if mark_price_value is None:
                    symbols_summary.append(latest)
                    continue
                entry_context = position.get("entry_context", {})
                reserved_margin = float(
                    entry_context.get("margin_reserved")
                    or entry_context.get("margin_reserved_eur")
                    or position["entry_notional"]
                )
                mark_value = float(position["quantity"]) * float(mark_price_value)
                exit_fee = mark_value * provider.taker_fee_rate
                if side == "SHORT":
                    unrealized_pnl = float(position["entry_notional"]) - mark_value - exit_fee
                else:
                    unrealized_pnl = mark_value - float(position["entry_notional"]) - exit_fee
                latest["position"] = {
                    "id": position["id"],
                    "opened_at": position["opened_at"],
                    "side": side,
                    "entry_price": position["entry_price"],
                    "quantity": position["quantity"],
                    "entry_notional": position["entry_notional"],
                    "entry_fee": position["entry_fee"],
                    "margin_reserved": reserved_margin,
                    "unrealized_pnl": unrealized_pnl,
                    "entry_context": entry_context,
                }
            symbols_summary.append(latest)

        max_exposure_eur = runtime["equity"] * (
            float(state.get("risk_max_total_exposure_pct", "0")) / 100.0
        )
        daily_loss_limit_eur = float(state.get("paper_daily_loss_limit_eur", "0"))
        daily_loss_limit_base_eur = float(state.get("paper_daily_loss_limit_base_eur", "0"))
        equity_history_rows = list(reversed(self.get_recent_equity_snapshots(limit=160)))
        equity_history = [
            {
                "created_at": row["created_at"],
                "equity": row["equity"],
                "cash": row["cash"],
                "exposure_pct": row["exposure_pct"],
            }
            for row in equity_history_rows
        ]
        risk_summary = {
            "guardrail_status": state.get("paper_guardrail_status", "ATTIVO"),
            "trading_enabled": state.get("paper_trading_enabled", "true") == "true",
            "kill_switch_reason": state.get("paper_kill_switch_reason", ""),
            "cooldown_until": state.get("paper_cooldown_until") or None,
            "daily_trade_count": runtime["today_trade_count"],
            "daily_trade_limit": int(state.get("risk_daily_trade_limit", "0")),
            "daily_realized_pnl": runtime["today_realized_pnl"],
            "daily_loss_limit_eur": daily_loss_limit_eur,
            "daily_loss_limit_base_eur": daily_loss_limit_base_eur,
            "daily_loss_limit_pct": float(state.get("risk_daily_loss_limit_pct", "0")),
            "current_exposure_eur": runtime["current_exposure_eur"],
            "current_exposure_pct": runtime["current_exposure_pct"],
            "reserved_margin_eur": runtime.get("reserved_margin_eur", 0.0),
            "max_exposure_eur": max_exposure_eur,
            "max_exposure_pct": float(state.get("risk_max_total_exposure_pct", "0")),
            "max_open_positions": int(state.get("risk_max_open_positions", "0")),
            "open_positions": runtime["open_positions"],
            "max_trade_allocation_pct": float(
                state.get("risk_max_trade_allocation_pct", "0")
            ),
            "min_cash_reserve_pct": float(state.get("risk_min_cash_reserve_pct", "0")),
            "max_risk_per_trade_pct": float(
                state.get("risk_max_risk_per_trade_pct", "0")
            ),
            "min_order_notional_eur": float(
                state.get("risk_min_order_notional_eur", "0")
            ),
            "consecutive_losses": runtime["consecutive_losses"],
            "max_consecutive_losses": int(state.get("risk_max_consecutive_losses", "0")),
            "current_drawdown_pct": abs(min(runtime["current_drawdown_pct"], 0.0)),
            "max_drawdown_limit_pct": float(state.get("risk_max_drawdown_pct", "0")),
            "max_drawdown_observed_pct": abs(min(runtime["max_drawdown_pct"], 0.0)),
            "today_max_drawdown_pct": abs(min(runtime["today_max_drawdown_pct"], 0.0)),
            "cycle_error_count": int(state.get("bot_cycle_error_count", "0")),
            "max_cycle_errors": int(state.get("risk_max_consecutive_cycle_errors", "0")),
        }
        performance_summary = {
            "closed_trades": runtime["closed_trades"],
            "long_trades": runtime["long_trades"],
            "short_trades": runtime["short_trades"],
            "wins": runtime["wins"],
            "losses": runtime["losses"],
            "flat": runtime["flat"],
            "win_rate_pct": runtime["win_rate_pct"],
            "expectancy_eur": runtime["expectancy"],
            "profit_factor": runtime["profit_factor"],
            "gross_profit_eur": runtime["gross_profit"],
            "gross_loss_eur": runtime["gross_loss"],
            "average_win_eur": runtime["average_win"],
            "average_loss_eur": runtime["average_loss"],
            "best_trade_eur": runtime["best_trade"],
            "worst_trade_eur": runtime["worst_trade"],
            "average_hold_minutes": runtime["average_hold_minutes"],
            "average_entry_slippage_pct": runtime["average_entry_slippage_pct"],
            "average_exit_slippage_pct": runtime["average_exit_slippage_pct"],
            "today_fees_eur": runtime["today_fees_total"],
            "equity_history": equity_history,
        }
        failure_analysis = self._build_failure_analysis(
            runtime=runtime,
            positions=hydrated_positions,
        )
        signals = [dict(row) for row in self.get_recent_signals(limit=20)]
        events = [
            {
                **dict(row),
                "details": self._parse_json(row["details_json"]),
            }
            for row in self.get_recent_operational_events(limit=24)
        ]
        decision_replay = self.get_recent_decision_replay(limit=24)
        ledger = self.get_recent_review_ledger_events(limit=24)
        return {
            "bot": {
                "status": state.get("bot_status", "idle"),
                "mode": state.get("bot_mode", "PUBLIC_SIM"),
                "last_cycle_at": state.get("bot_last_cycle_at"),
                "last_error": state.get("bot_last_error"),
                "symbols": symbols,
                "data_mode": state.get("bot_data_mode", "public"),
            },
            "account": {
                "starting_balance": starting_balance,
                "contributed_capital": runtime["contributed_capital"],
                "cash": runtime["cash"],
                "realized_pnl": runtime["realized_pnl"],
                "unrealized_pnl": runtime["unrealized_pnl"],
                "equity": runtime["equity"],
                "net_profit_after_contributions": runtime["net_profit_after_contributions"],
                "return_on_contributed_capital_pct": runtime["return_on_contributed_capital_pct"],
                "fees_entry_total": fee_totals["entry_total"],
                "fees_exit_total": fee_totals["exit_total"],
                "fees_total": fee_totals["grand_total"],
                "open_positions": runtime["open_positions"],
            "current_exposure_eur": runtime["current_exposure_eur"],
            "current_exposure_pct": runtime["current_exposure_pct"],
            "reserved_margin_eur": runtime.get("reserved_margin_eur", 0.0),
            "portfolio_currency": runtime["portfolio_currency"],
        },
            "provider": {
                "current": serialize_provider(provider),
                "available": list_provider_profiles(),
            },
            "blockchain": blockchain,
            "modes": self._build_operating_modes(state),
            "supported_workflows": self._build_supported_workflows(state),
                "known_limitations": self._build_known_limitations(),
            "strategy": {
                "name": state.get("strategy_name", "momentum_v1"),
                "description": state.get(
                    "strategy_description",
                    "Usa momentum order book, trade recenti e candele del venue operativo per decidere gli ingressi paper.",
                ),
                "monitored_symbols": [
                    item.strip()
                    for item in state.get("monitored_symbols", "").split(",")
                    if item.strip()
                ],
                "entry_enabled_symbols": [
                    item.strip()
                    for item in state.get("entry_enabled_symbols", "").split(",")
                    if item.strip()
                ],
                "candles_interval_minutes": candles_interval_minutes,
                "entry_momentum_threshold_pct": float(
                    state.get("entry_momentum_threshold_pct", "0")
                ),
                "candle_trend_threshold_pct": float(
                    state.get("candle_trend_threshold_pct", "0")
                ),
                "spread_limit_bps": float(state.get("spread_limit_bps", "0")),
                "take_profit_pct": float(state.get("take_profit_pct", "0")),
                "stop_loss_pct": float(state.get("stop_loss_pct", "0")),
                "max_hold_minutes": float(state.get("max_hold_minutes", "0")),
                "auth_context_enabled": state.get("auth_context_enabled", "false") == "true",
                "paper_trade_size": float(state.get("paper_trade_size", "0")),
                "reward_to_risk_ratio": float(state.get("reward_to_risk_ratio", "0")),
                "exit_reverse_threshold_pct": float(
                    state.get("exit_reverse_threshold_pct", "0")
                ),
                "imbalance_reverse_threshold_pct": float(
                    state.get("imbalance_reverse_threshold_pct", "0")
                ),
                "book_imbalance_threshold_pct": float(
                    state.get("book_imbalance_threshold_pct", "0")
                ),
                "long_book_imbalance_threshold_pct": float(
                    state.get(
                        "book_imbalance_long_threshold_pct",
                        state.get("book_imbalance_threshold_pct", "0"),
                    )
                ),
                "short_book_imbalance_threshold_pct": float(
                    state.get("book_imbalance_short_threshold_pct", "0")
                ),
                "volatility_floor_pct": float(state.get("volatility_floor_pct", "0")),
                "volatility_ceiling_pct": float(state.get("volatility_ceiling_pct", "0")),
                "minimum_recent_trade_count": int(
                    state.get("minimum_recent_trade_count", "0")
                ),
                "perps_default_leverage": float(
                    state.get("perps_default_leverage", "1")
                ),
                "perps_margin_mode": state.get("perps_margin_mode", "ISOLATED"),
                "perps_execution_policy": state.get("perps_execution_policy", "IOC"),
                "short_entries_enabled": state.get("short_entries_enabled", "false")
                == "true",
                "reduce_only_exits_enabled": state.get(
                    "reduce_only_exits_enabled", "false"
                )
                == "true",
            },
            "experiment": {
                "name": state.get("experiment_name", ""),
                "notes": state.get("experiment_notes", ""),
                "freeze_enabled": state.get("experiment_freeze_enabled", "false") == "true",
                "baseline_fingerprint": state.get("experiment_baseline_fingerprint"),
                "current_fingerprint": state.get("experiment_current_fingerprint"),
                "drift_detected": state.get("experiment_drift_detected", "false") == "true",
                "drift_detected_at": state.get("experiment_drift_detected_at"),
            },
            "capital_plan": {
                "recurring_enabled": state.get("paper_recurring_contribution_enabled", "false") == "true",
                "amount_eur": float(state.get("paper_recurring_contribution_amount", "0")),
                "frequency": state.get("paper_recurring_contribution_frequency", "monthly"),
                "month_day": int(state.get("paper_recurring_contribution_month_day", "0")),
                "weekday": int(state.get("paper_recurring_contribution_weekday", "0")),
                "start_mode": state.get("paper_recurring_contribution_start_mode", "next_period"),
                "last_contribution_at": state.get("paper_recurring_contribution_last_at"),
                "last_contribution_period": state.get("paper_last_contribution_period"),
            },
            "account_center": account_center,
            "alpha_onboarding": self._build_alpha_onboarding_summary(
                state=state,
                runtime=runtime,
                account_center=account_center,
                daily_review=daily_review,
            ),
            "cost_attribution": cost_attribution,
            "daily_review": daily_review,
            "failure_analysis": failure_analysis,
            "journal_digest": self._build_journal_digest(
                signals=signals,
                events=events,
                decision_replay=decision_replay,
                ledger=ledger,
                daily_review=daily_review,
                failure_analysis=failure_analysis,
            ),
            "filter_audit": self.get_analysis_filter_summary(days=7),
            "daily_reports": self.get_recent_daily_reports(limit=45),
            "risk": risk_summary,
            "performance": performance_summary,
            "symbols": symbols_summary,
            "signals": signals,
            "positions": hydrated_positions[:20],
            "events": events,
            "decision_replay": decision_replay,
            "ledger": ledger,
        }
