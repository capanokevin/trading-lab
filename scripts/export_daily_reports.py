from __future__ import annotations

import json
from pathlib import Path
import sys

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

load_dotenv(ROOT / ".env")

from trading_bot.config import AppConfig
from trading_bot.storage import TradingStorage


def main() -> int:
    config = AppConfig.from_env()
    storage = TradingStorage(config.db_path)
    storage.init_db()
    reports = storage.get_recent_daily_reports(limit=365)
    output_dir = Path("data/exports")
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / "daily_reports.json"
    output_path.write_text(json.dumps(reports, ensure_ascii=True, indent=2))
    print(output_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
