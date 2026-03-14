"""Analyze metrics/logs and produce structured feedback findings."""

import re
from typing import Dict, List


class FeedbackAnalyzer:
    """Rule-based analyzer for system metrics and log output."""

    def __init__(self, rules: List[Dict]):
        """Create analyzer with a list of rule dictionaries."""
        self.rules = rules

    def analyze(self, metrics: Dict, logs: List[Dict]) -> List[Dict]:
        """Return findings based on metrics and recent logs."""
        findings: List[Dict] = []
        cpu = float(metrics.get("cpu_percent", 0) or 0)
        mem = int(metrics.get("mem_bytes", 0) or 0)

        for rule in self.rules:
            kind = rule.get("kind")
            if kind == "cpu" and cpu >= rule.get("threshold", 80):
                findings.append(self._make(rule.get("code", "high_cpu"), rule.get("severity", "warn"), f"CPU {cpu:.1f}%"))
            if kind == "memory" and mem >= rule.get("threshold", 1_000_000_000):
                findings.append(self._make(rule.get("code", "high_memory"), rule.get("severity", "warn"), f"Mem {mem} bytes"))
            if kind == "log_regex":
                pattern = rule.get("pattern")
                if not pattern:
                    continue
                for entry in logs:
                    msg = entry.get("message", "")
                    if re.search(pattern, msg, re.I):
                        findings.append(self._make(rule.get("code", "log_match"), rule.get("severity", "warn"), msg[:200]))

        for entry in logs:
            msg = entry.get("message", "")
            if re.search(r"error|exception|traceback", msg, re.I):
                findings.append(self._make("error_output", "error", msg[:200]))

        return findings

    def _make(self, code: str, severity: str, detail: str) -> Dict:
        """Create a normalized finding record."""
        return {"code": code, "severity": severity, "detail": detail}
