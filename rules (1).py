"""Default detection rules for the feedback analyzer."""

DEFAULT_RULES = [
    {"kind": "cpu", "threshold": 85.0, "severity": "warn", "code": "high_cpu"},
    {"kind": "memory", "threshold": 1_500_000_000, "severity": "warn", "code": "high_memory"},
    {"kind": "log_regex", "pattern": r"timeout|timed out", "severity": "warn", "code": "timeout"},
    {"kind": "log_regex", "pattern": r"error|exception|traceback", "severity": "error", "code": "error_output"},
]
