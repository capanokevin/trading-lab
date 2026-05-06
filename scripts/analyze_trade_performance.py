from __future__ import annotations

import json
import sqlite3
import statistics
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

load_dotenv(ROOT / ".env")

from trading_bot.config import AppConfig
from trading_bot.storage import TradingStorage


def parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def mean_or_zero(values: list[float]) -> float:
    return statistics.mean(values) if values else 0.0


def row_pnl(row: sqlite3.Row) -> float:
    return float(row["realized_pnl"] or 0.0)


def row_fees(row: sqlite3.Row) -> float:
    return float(row["entry_fee"] or 0.0) + float(row["exit_fee"] or 0.0)


def hold_minutes_for(row: sqlite3.Row) -> float | None:
    opened_at = parse_iso(row["opened_at"])
    closed_at = parse_iso(row["closed_at"])
    if not opened_at or not closed_at:
        return None
    return (closed_at - opened_at).total_seconds() / 60.0


def win_rate(values: list[float]) -> float:
    if not values:
        return 0.0
    return sum(1 for item in values if item > 0) / len(values) * 100


def format_range(rows: list[sqlite3.Row]) -> str:
    opened_values = [parse_iso(str(row["opened_at"])) for row in rows if row["opened_at"]]
    closed_values = [
        parse_iso(str(row["closed_at"] or row["opened_at"])) for row in rows if row["opened_at"]
    ]
    opened_values = [value for value in opened_values if value is not None]
    closed_values = [value for value in closed_values if value is not None]
    if not opened_values or not closed_values:
        return "n/d"
    return f"{min(opened_values).date().isoformat()} -> {max(closed_values).date().isoformat()}"


def main() -> int:
    config = AppConfig.from_env()
    storage = TradingStorage(config.db_path)
    storage.init_db()
    currency = config.quote_currency
    max_hold_minutes = float(storage.get_state("max_hold_minutes", "0") or 0)

    connection = sqlite3.connect(config.db_path)
    connection.row_factory = sqlite3.Row
    rows = connection.execute(
        """
        SELECT *
        FROM paper_positions
        WHERE status = 'CLOSED'
        ORDER BY opened_at
        """
    ).fetchall()

    print("Analisi trade chiusi")
    print()
    print(f"- trade chiusi: {len(rows)}")
    print(f"- simboli monitorati: {', '.join(config.monitored_symbols)}")
    print(f"- simboli abilitati alle entrate: {', '.join(config.entry_enabled_symbols)}")

    if not rows:
        return 0

    pnls: list[float] = []
    hold_minutes: list[float] = []
    by_symbol: dict[str, list[float]] = defaultdict(list)
    by_reason: dict[str, list[float]] = defaultdict(list)
    by_strategy: dict[str, list[sqlite3.Row]] = defaultdict(list)
    by_side: dict[str, list[float]] = defaultdict(list)
    by_symbol_side: dict[tuple[str, str], list[sqlite3.Row]] = defaultdict(list)
    winners: list[sqlite3.Row] = []

    metric_pairs: dict[str, list[tuple[float, float]]] = defaultdict(list)
    watched_metrics = [
        "spread_bps",
        "momentum_pct",
        "candle_trend_pct",
        "book_imbalance_pct",
        "candle_volatility_pct",
        "recent_trade_count",
    ]

    for row in rows:
        pnl = row_pnl(row)
        pnls.append(pnl)
        by_symbol[str(row["symbol"])].append(pnl)
        by_reason[str(row["close_reason"] or "N/A")].append(pnl)
        by_strategy[str(row["strategy"] or "unknown")].append(row)
        side = str(row["side"] or "UNKNOWN")
        by_side[side].append(pnl)
        by_symbol_side[(str(row["symbol"]), side)].append(row)
        if pnl > 0:
            winners.append(row)

        hold_minutes_value = hold_minutes_for(row)
        if hold_minutes_value is not None:
            hold_minutes.append(hold_minutes_value)

        entry_context = json.loads(row["entry_context_json"] or "{}")
        for key in watched_metrics:
            value = entry_context.get(key)
            if value is not None:
                metric_pairs[key].append((pnl, float(value)))

    print()
    print("Quadro generale")
    print(f"- pnl netto: {sum(pnls):.2f} {currency}")
    print(f"- fee totali: {sum(row_fees(row) for row in rows):.2f} {currency}")
    print(f"- win rate: {win_rate(pnls):.2f}%")
    print(f"- pnl medio per trade: {mean_or_zero(pnls):.2f} {currency}")
    print(f"- hold medio: {mean_or_zero(hold_minutes):.2f} minuti")

    print()
    print("Per versione strategica")
    for strategy, strategy_rows in sorted(by_strategy.items()):
        strategy_pnls = [float(row["realized_pnl"] or 0.0) for row in strategy_rows]
        print(
            f"- {strategy}: {len(strategy_rows)} trade | pnl {sum(strategy_pnls):.2f} {currency} | "
            f"media {mean_or_zero(strategy_pnls):.2f} {currency} | "
            f"win rate {win_rate(strategy_pnls):.1f}% | "
            f"periodo {format_range(strategy_rows)}"
        )
    current_strategy = storage.get_state("strategy_name") or config.experiment_name
    if current_strategy and current_strategy not in by_strategy:
        print(f"- {current_strategy}: nessun trade chiuso ancora registrato")

    print()
    print("Per simbolo")
    for symbol, values in sorted(by_symbol.items()):
        print(
            f"- {symbol}: {len(values)} trade | pnl {sum(values):.2f} {currency} | "
            f"media {mean_or_zero(values):.2f} {currency} | "
            f"win rate {win_rate(values):.1f}%"
        )

    print()
    print("Per lato")
    for side, values in sorted(by_side.items()):
        print(
            f"- {side}: {len(values)} trade | pnl {sum(values):.2f} {currency} | "
            f"media {mean_or_zero(values):.2f} {currency} | "
            f"win rate {win_rate(values):.1f}%"
        )

    print()
    print("Per simbolo e lato")
    for (symbol, side), symbol_side_rows in sorted(
        by_symbol_side.items(), key=lambda item: sum(row_pnl(row) for row in item[1])
    ):
        values = [row_pnl(row) for row in symbol_side_rows]
        fees = [row_fees(row) for row in symbol_side_rows]
        holds = [
            value
            for value in (hold_minutes_for(row) for row in symbol_side_rows)
            if value is not None
        ]
        print(
            f"- {symbol} {side}: {len(values)} trade | pnl {sum(values):.2f} {currency} | "
            f"media {mean_or_zero(values):.2f} {currency} | fee {sum(fees):.2f} {currency} | "
            f"win rate {win_rate(values):.1f}% | hold medio {mean_or_zero(holds):.2f}m"
        )

    print()
    print("Per motivo di uscita")
    for reason, values in sorted(by_reason.items(), key=lambda item: sum(item[1])):
        print(
            f"- {reason}: {len(values)} trade | pnl {sum(values):.2f} {currency} | "
            f"media {mean_or_zero(values):.2f} {currency}"
        )

    stale_rows: list[sqlite3.Row] = []
    if max_hold_minutes > 0:
        stale_rows = [
            row
            for row in rows
            if (hold_minutes_for(row) or 0.0) > max_hold_minutes + 5
        ]
    best_trade = max(rows, key=row_pnl)

    print()
    print("Controllo robustezza")
    if stale_rows:
        stale_ids = {row["id"] for row in stale_rows}
        clean_rows = [row for row in rows if row["id"] not in stale_ids]
        clean_pnls = [row_pnl(row) for row in clean_rows]
        stale_pnls = [row_pnl(row) for row in stale_rows]
        print(
            f"- trade oltre tempo massimo operativo: {len(stale_rows)} | "
            f"pnl {sum(stale_pnls):.2f} {currency}"
        )
        print(
            f"- senza trade oltre tempo massimo: {len(clean_rows)} trade | "
            f"pnl {sum(clean_pnls):.2f} {currency} | win rate {win_rate(clean_pnls):.1f}%"
        )
    if row_pnl(best_trade) > 0:
        rows_without_best = [row for row in rows if row["id"] != best_trade["id"]]
        pnls_without_best = [row_pnl(row) for row in rows_without_best]
        print(
            f"- senza il miglior trade singolo ({best_trade['symbol']} {best_trade['side']} "
            f"{row_pnl(best_trade):.2f} {currency}): pnl {sum(pnls_without_best):.2f} {currency} | "
            f"win rate {win_rate(pnls_without_best):.1f}%"
        )

    print()
    print("Metriche di ingresso: vincitori vs perdenti")
    for key, pairs in metric_pairs.items():
        win_values = [value for pnl, value in pairs if pnl > 0]
        loss_values = [value for pnl, value in pairs if pnl <= 0]
        if not win_values and not loss_values:
            continue
        print(f"- {key}:")
        if win_values:
            print(
                f"  vincitori media {mean_or_zero(win_values):.4f} | "
                f"min {min(win_values):.4f} | max {max(win_values):.4f} | n {len(win_values)}"
            )
        if loss_values:
            print(
                f"  perdenti media {mean_or_zero(loss_values):.4f} | "
                f"min {min(loss_values):.4f} | max {max(loss_values):.4f} | n {len(loss_values)}"
            )

    print()
    print("Trade vincenti")
    for row in winners:
        print(
            f"- {row['symbol']} {row['side']} | pnl {float(row['realized_pnl']):.2f} {currency} | "
            f"open {row['opened_at']} | close {row['closed_at']} | {row['close_reason']}"
        )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
