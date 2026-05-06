from __future__ import annotations

import sys
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"

if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

load_dotenv(ROOT / ".env")

from trading_bot import AppConfig, TradingStorage  # noqa: E402
from trading_bot.desktop_widget import run_desk_companion  # noqa: E402


def main() -> int:
    config = AppConfig.from_env()
    storage = TradingStorage(config.db_path)
    run_desk_companion(config, storage)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
