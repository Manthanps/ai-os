import json
import os
import time
import traceback
from typing import Any, Callable, Dict, Optional, Tuple

LOG_PATH = os.path.join(os.path.dirname(__file__), "aios_error.log")
REPORT_PATH = os.path.join(os.path.dirname(__file__), "debug_report.json")


def _now() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S")


def log_error(
    context: str,
    err: BaseException,
    intent: Optional[str] = None,
    payload: Optional[Dict[str, Any]] = None,
    command: Optional[str] = None,
) -> None:
    entry = {
        "timestamp": _now(),
        "context": context,
        "intent": intent,
        "payload": payload,
        "command": command,
        "error_type": type(err).__name__,
        "error": str(err),
        "traceback": traceback.format_exc(limit=5),
    }
    try:
        with open(LOG_PATH, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry) + "\n")
    except Exception:
        pass


def run_with_retry(
    fn: Callable[[], Any],
    retries: int = 1,
    delay: float = 0.5,
    on_error: Optional[Callable[[BaseException, int], None]] = None,
) -> Tuple[bool, Any, Optional[BaseException]]:
    attempt = 0
    while True:
        try:
            return True, fn(), None
        except Exception as exc:
            attempt += 1
            if on_error:
                on_error(exc, attempt)
            if attempt > retries:
                return False, None, exc
            time.sleep(delay)


def generate_report(max_entries: int = 200) -> Dict[str, Any]:
    if not os.path.exists(LOG_PATH):
        report = {"status": "no_logs", "total_errors": 0, "errors": []}
        _write_report(report)
        return report

    entries = []
    try:
        with open(LOG_PATH, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entries.append(json.loads(line))
                except Exception:
                    continue
    except Exception:
        report = {"status": "unreadable_logs", "total_errors": 0, "errors": []}
        _write_report(report)
        return report

    entries = entries[-max_entries:]
    counts = {}
    for e in entries:
        key = f"{e.get('intent','unknown')}::{e.get('error_type','Error')}"
        counts[key] = counts.get(key, 0) + 1

    report = {
        "status": "ok",
        "total_errors": len(entries),
        "counts": counts,
        "latest": entries[-10:],
    }
    _write_report(report)
    return report


def _write_report(report: Dict[str, Any]) -> None:
    try:
        with open(REPORT_PATH, "w", encoding="utf-8") as f:
            json.dump(report, f, indent=2)
    except Exception:
        pass


def watch_logs() -> None:
    if not os.path.exists(LOG_PATH):
        print("No error log found.")
        return
    print(f"Watching {LOG_PATH} (Ctrl+C to stop)")
    with open(LOG_PATH, "r", encoding="utf-8") as f:
        f.seek(0, os.SEEK_END)
        try:
            while True:
                line = f.readline()
                if not line:
                    time.sleep(0.5)
                    continue
                try:
                    entry = json.loads(line)
                    msg = f"[{entry.get('timestamp')}] {entry.get('intent')} {entry.get('error_type')}: {entry.get('error')}"
                    print(msg)
                except Exception:
                    print(line.strip())
        except KeyboardInterrupt:
            print("Stopped watching logs.")
