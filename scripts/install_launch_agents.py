from __future__ import annotations

import os
import plistlib
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
HOME = Path.home()
LAUNCH_AGENTS = HOME / "Library" / "LaunchAgents"
LOG_DIR = HOME / "Library" / "Logs" / "trading-control-plane"
APP_SUPPORT_DIR = HOME / "Library" / "Application Support" / "trading-control-plane"

LABELS = {
    "bot": "com.tradingcontrolplane.bot",
    "dashboard": "com.tradingcontrolplane.dashboard",
    "companion": "com.tradingcontrolplane.companion",
}


def build_plist(label: str, program_arguments: list[str]) -> dict:
    return {
        "Label": label,
        "ProgramArguments": program_arguments,
        "WorkingDirectory": str(ROOT),
        "RunAtLoad": True,
        "KeepAlive": True,
        "StandardOutPath": str(LOG_DIR / f"{label}.log"),
        "StandardErrorPath": str(LOG_DIR / f"{label}.log"),
        "EnvironmentVariables": {
            "PATH": os.environ.get("PATH", ""),
            "PYTHONUNBUFFERED": "1",
        },
        "ProcessType": "Interactive",
        "LimitLoadToSessionType": "Aqua",
    }


def write_plist(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("wb") as handle:
        plistlib.dump(payload, handle, sort_keys=False)


def ensure_swift_companion_binary() -> Path:
    source_path = ROOT / "macos" / "TradingDeskCompanion.swift"
    output_path = APP_SUPPORT_DIR / "TradingDeskCompanion"
    APP_SUPPORT_DIR.mkdir(parents=True, exist_ok=True)
    if not output_path.exists() or source_path.stat().st_mtime > output_path.stat().st_mtime:
        subprocess.run(
            [
                "swiftc",
                str(source_path),
                "-framework",
                "AppKit",
                "-framework",
                "SwiftUI",
                "-o",
                str(output_path),
            ],
            check=True,
        )
    return output_path


def bootout_if_loaded(uid: str, plist_path: Path) -> None:
    subprocess.run(
        ["launchctl", "bootout", f"gui/{uid}", str(plist_path)],
        check=False,
        capture_output=True,
        text=True,
    )


def bootstrap(uid: str, plist_path: Path) -> None:
    subprocess.run(
        ["launchctl", "bootstrap", f"gui/{uid}", str(plist_path)],
        check=True,
    )


def main() -> int:
    LAUNCH_AGENTS.mkdir(parents=True, exist_ok=True)
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    uid = str(os.getuid())
    companion_binary = ensure_swift_companion_binary()

    python_bin = sys.executable
    services = {
        LABELS["bot"]: [python_bin, str(ROOT / "scripts" / "run_public_bot.py")],
        LABELS["dashboard"]: [python_bin, str(ROOT / "scripts" / "run_dashboard.py")],
        LABELS["companion"]: [str(companion_binary)],
    }

    for label, program_arguments in services.items():
        plist_path = LAUNCH_AGENTS / f"{label}.plist"
        write_plist(plist_path, build_plist(label, program_arguments))
        bootout_if_loaded(uid, plist_path)
        bootstrap(uid, plist_path)
        print(f"Attivato {label}")

    print("LaunchAgents installati e avviati.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
