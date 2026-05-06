from __future__ import annotations

import os
import subprocess
from pathlib import Path


HOME = Path.home()
LAUNCH_AGENTS = HOME / "Library" / "LaunchAgents"

LABELS = [
    "com.tradingcontrolplane.bot",
    "com.tradingcontrolplane.dashboard",
    "com.tradingcontrolplane.companion",
]


def main() -> int:
    uid = str(os.getuid())
    for label in LABELS:
        plist_path = LAUNCH_AGENTS / f"{label}.plist"
        subprocess.run(
            ["launchctl", "bootout", f"gui/{uid}", str(plist_path)],
            check=False,
            capture_output=True,
            text=True,
        )
        if plist_path.exists():
            plist_path.unlink()
        print(f"Disattivato {label}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
