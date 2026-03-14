"""Structured logging for monitoring sessions (JSONL + optional CSV)."""

import csv
import json
import os
import time
from typing import Dict


class SessionLogger:
    """Session logger for metrics, findings, and adjustments."""

    def __init__(self, log_dir: str, csv_metrics: bool = False):
        """Create a new session logger under log_dir."""
        os.makedirs(log_dir, exist_ok=True)
        ts = time.strftime("%Y%m%d_%H%M%S")
        self.log_path = os.path.join(log_dir, f"session_{ts}.jsonl")
        self.summary_path = os.path.join(log_dir, f"summary_{ts}.json")
        self.csv_path = os.path.join(log_dir, f"metrics_{ts}.csv") if csv_metrics else None
        self._fh = open(self.log_path, "a", encoding="utf-8")
        self._csv_fh = None
        self._csv_writer = None
        if self.csv_path:
            self._csv_fh = open(self.csv_path, "a", newline="", encoding="utf-8")
            self._csv_writer = csv.DictWriter(self._csv_fh, fieldnames=["ts", "cpu_percent", "mem_bytes", "status", "pid"])
            self._csv_writer.writeheader()

        self.counts = {"metrics": 0, "logs": 0, "findings": 0, "adjustments": 0}

    def log_event(self, event_type: str, data: Dict) -> None:
        """Append a structured JSONL event to the session log."""
        record = {"ts": time.time(), "type": event_type, "data": data}
        self._fh.write(json.dumps(record) + "\n")
        self._fh.flush()
        if event_type in self.counts:
            self.counts[event_type] += 1

    def log_metrics_csv(self, metrics: Dict) -> None:
        """Write metrics to CSV if enabled."""
        if not self._csv_writer:
            return
        row = {
            "ts": time.time(),
            "cpu_percent": metrics.get("cpu_percent"),
            "mem_bytes": metrics.get("mem_bytes"),
            "status": metrics.get("status"),
            "pid": metrics.get("pid"),
        }
        self._csv_writer.writerow(row)
        self._csv_fh.flush()

    def write_summary(self, summary: Dict) -> None:
        """Persist summary JSON for the session."""
        with open(self.summary_path, "w", encoding="utf-8") as fh:
            json.dump(summary, fh, indent=2)

    def close(self) -> None:
        """Close any open log files."""
        try:
            self._fh.close()
        finally:
            if self._csv_fh:
                self._csv_fh.close()
