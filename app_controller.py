import logging
import subprocess
import time


def open_application(app_name: str, wait: float = 3.0) -> None:
    """Open a macOS application by name."""
    app_name = app_name.strip()
    if not app_name:
        raise ValueError("app_name is required")
    logging.info("Opening %s", app_name)
    subprocess.run(["open", "-a", app_name], check=False)
    time.sleep(wait)


def focus_application(app_name: str, wait: float = 0.5) -> None:
    """Activate/focus an application (best-effort)."""
    subprocess.run([
        "osascript",
        "-e",
        f'tell application "{app_name}" to activate'
    ], check=False)
    time.sleep(wait)
