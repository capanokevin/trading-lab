from __future__ import annotations

import shutil
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"

if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

load_dotenv(ROOT / ".env")

from trading_bot import AppConfig, TradingStorage  # noqa: E402


def main() -> int:
    config = AppConfig.from_env()
    storage = TradingStorage(config.db_path)
    storage.init_db()

    archive_dir = ROOT / "data" / "archive"
    archive_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().astimezone().strftime("%Y%m%d-%H%M%S")
    archive_path = archive_dir / f"{config.db_path.stem}-{timestamp}.sqlite3"
    shutil.copy2(config.db_path, archive_path)

    with storage.connect() as connection:
        connection.execute("DELETE FROM paper_positions")
        connection.execute("DELETE FROM signals")
        connection.execute("DELETE FROM strategy_analysis")
        connection.execute("DELETE FROM decision_replay")
        connection.execute("DELETE FROM analysis_daily_counters")
        connection.execute("DELETE FROM daily_reports")
        connection.execute("DELETE FROM review_annotations")
        connection.execute("DELETE FROM event_ledger")
        connection.execute("DELETE FROM events_log")
        connection.execute("DELETE FROM equity_snapshots")
        connection.execute("DELETE FROM bot_state")

    print(
        f"Sessione paper resettata. Backup creato in {archive_path}",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
