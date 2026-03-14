"""Simple AI brain interface for applying feedback-driven adjustments."""

import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional


@dataclass
class BrainState:
    throttle_seconds: float = 0.0
    last_action: str = ""
    adjustments: List[Dict] = field(default_factory=list)


class AIBrain:
    """Simple brain interface that accepts feedback and adjusts workflow state."""

    def __init__(self, logger=None):
        """Initialize with optional logger for adjustment tracking."""
        self.state = BrainState()
        self.logger = logger

    def accept_feedback(self, feedback: List[Dict]) -> BrainState:
        """Apply feedback list and update brain state."""
        for item in feedback:
            action = self._decide_action(item)
            if action:
                self.state.last_action = action["action"]
                self.state.adjustments.append(action)
                if self.logger:
                    self.logger.log_event("adjustments", action)
        return self.state

    def accept_feedback_api(self, payload: Dict) -> BrainState:
        """API-friendly entrypoint. Expects {"feedback": [...]}"""
        feedback = payload.get("feedback", [])
        return self.accept_feedback(feedback)

    def _decide_action(self, item: Dict) -> Optional[Dict]:
        """Map a finding into an adjustment action."""
        code = item.get("code")
        severity = item.get("severity", "info")
        now = time.time()

        if code == "high_cpu":
            self.state.throttle_seconds = max(self.state.throttle_seconds, 1.0)
            return {"ts": now, "action": "throttle", "reason": "cpu_high", "severity": severity}
        if code == "high_memory":
            return {"ts": now, "action": "reduce_load", "reason": "memory_high", "severity": severity}
        if code == "error_output":
            return {"ts": now, "action": "flag_error", "reason": "error_output", "severity": severity}
        if code == "timeout":
            return {"ts": now, "action": "increase_timeout", "reason": "timeout", "severity": severity}

        return None
