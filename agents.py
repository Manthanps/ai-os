"""Agent-based architecture for the AI debugger."""

import queue
import time
from dataclasses import dataclass
from typing import Dict, List, Optional

from analyzer import FeedbackAnalyzer
from brain import AIBrain
from encoder_decoder import EncoderDecoderAnomaly
from logger import SessionLogger
from llm_root_cause import generate_root_cause
from monitor import ProcessMonitor
from rules import DEFAULT_RULES


@dataclass
class Event:
    type: str
    data: Dict


class EventBus:
    """In-process event bus for agent communication."""

    def __init__(self, agents: List["BaseAgent"], context: Dict):
        self.agents = agents
        self.context = context

    def publish(self, event: Event) -> None:
        for agent in self.agents:
            new_events = agent.handle(event, self.context)
            for ev in new_events:
                self.publish(ev)


class BaseAgent:
    """Base class for all agents."""

    def handle(self, event: Event, context: Dict) -> List[Event]:
        return []


class MonitorAgent:
    """Runs a command, streams logs, and emits metrics events."""

    def __init__(self, cmd: str, interval: float, duration: float):
        self.cmd = cmd
        self.interval = interval
        self.duration = duration
        self._monitor = ProcessMonitor(interval=interval)
        self._proc = None
        self._queue: Optional[queue.Queue] = None
        self._start_time = 0.0
        self.done = False
        self.exit_code: Optional[int] = None

    def start(self) -> None:
        self._proc, self._queue = self._monitor.run_command(self.cmd)
        self._start_time = time.time()

    def terminate(self) -> None:
        if self._proc and self._proc.poll() is None:
            self._proc.terminate()

    def tick(self) -> List[Event]:
        events: List[Event] = []
        if not self._proc or not self._queue:
            return events

        # Drain log queue
        events.extend(self._drain_logs())

        # Check for process exit
        if self._proc.poll() is not None:
            self.done = True
            self.exit_code = self._proc.poll()
            events.append(Event("process_exit", {"exit_code": self.exit_code}))
            return events

        # Duration check
        if self.duration and (time.time() - self._start_time) >= self.duration:
            self._proc.terminate()
            self.done = True
            self.exit_code = self._proc.poll()
            events.append(Event("process_exit", {"exit_code": self.exit_code}))
            return events

        # Metrics
        stats = self._monitor.poll_stats(self._proc.pid)
        metrics = {
            "pid": stats.pid,
            "cpu_percent": stats.cpu_percent,
            "mem_bytes": stats.mem_bytes,
            "status": stats.status,
        }
        events.append(Event("metrics", metrics))

        return events

    def drain_remaining_logs(self) -> List[Event]:
        return self._drain_logs()

    def _drain_logs(self) -> List[Event]:
        events: List[Event] = []
        if not self._queue:
            return events
        while True:
            try:
                stream, message = self._queue.get_nowait()
                events.append(Event("log", {"stream": stream, "message": message}))
            except queue.Empty:
                break
        return events


class AnalyzerAgent(BaseAgent):
    """Analyzes metrics/logs and emits findings."""

    def __init__(self, ae_enabled: bool, ae_window: int, ae_min_train: int, ae_components: int, ae_z: float):
        self.analyzer = FeedbackAnalyzer(DEFAULT_RULES)
        self.log_buffer: List[Dict] = []
        self.ae = None
        if ae_enabled:
            self.ae = EncoderDecoderAnomaly(
                window=ae_window,
                min_train=ae_min_train,
                components=ae_components,
                z_threshold=ae_z,
            )
            if not self.ae.available:
                self.ae = None

    def handle(self, event: Event, context: Dict) -> List[Event]:
        if event.type == "log":
            self.log_buffer.append(event.data)
            return []

        if event.type == "metrics":
            findings = self.analyzer.analyze(event.data, self.log_buffer)

            # Encoder/decoder anomaly detection
            if self.ae:
                feature_vec = [
                    float(event.data["cpu_percent"]),
                    float(event.data["mem_bytes"]) / (1024 * 1024),
                    float(len(self.log_buffer)),
                ]
                is_anom, score, thresh = self.ae.update_and_check(feature_vec)
                if is_anom:
                    detail = f"AE anomaly score={score:.4f} threshold={thresh:.4f}"
                    findings.append({"code": "ae_anomaly", "severity": "error", "detail": detail})

            self.log_buffer = []
            return [Event("finding", f) for f in findings]

        return []


class BrainAgent(BaseAgent):
    """Consumes findings and produces workflow adjustments."""

    def __init__(self, logger=None):
        self.brain = AIBrain(logger=logger)

    def handle(self, event: Event, context: Dict) -> List[Event]:
        if event.type == "finding":
            self.brain.accept_feedback([event.data])
            context["throttle_seconds"] = self.brain.state.throttle_seconds
            return [Event("adjustment", {"last_action": self.brain.state.last_action})]
        return []


class RootCauseAgent(BaseAgent):
    """Derive root-cause hypotheses from logs and findings."""

    def __init__(self, max_logs: int = 200):
        self.max_logs = max_logs
        self.logs: List[str] = []
        self.findings: List[Dict] = []

    def handle(self, event: Event, context: Dict) -> List[Event]:
        if event.type == "log":
            msg = event.data.get("message", "")
            if msg:
                self.logs.append(msg)
                if len(self.logs) > self.max_logs:
                    self.logs = self.logs[-self.max_logs :]
            return []
        if event.type == "finding":
            self.findings.append(event.data)
            return []
        if event.type == "process_exit":
            hypotheses = self._hypothesize()
            if hypotheses:
                return [Event("root_cause", {"hypotheses": hypotheses})]
        return []

    def _hypothesize(self) -> List[Dict]:
        text = "\n".join(self.logs).lower()
        codes = {f.get("code") for f in self.findings}
        out: List[Dict] = []

        def add(reason: str, confidence: float):
            out.append({"reason": reason, "confidence": round(confidence, 2)})

        if "modulenotfounderror" in text or "no module named" in text:
            add("Missing Python dependency or module not installed.", 0.78)
        if "importerror" in text:
            add("Import failure (version mismatch or missing package).", 0.65)
        if "no such file or directory" in text or "filenotfounderror" in text:
            add("File/path not found or incorrect working directory.", 0.7)
        if "permission denied" in text:
            add("Permission error (insufficient access).", 0.7)
        if "timeout" in text or "timed out" in text:
            add("Timeout or external dependency not responding.", 0.6)
        if "connection refused" in text or "connection reset" in text:
            add("Network/service connection failure.", 0.6)
        if "syntaxerror" in text:
            add("Syntax error in code.", 0.75)
        if "keyerror" in text or "indexerror" in text:
            add("Data shape mismatch (missing key/index).", 0.55)
        if "segmentation fault" in text or "bus error" in text:
            add("Native crash (binary incompatibility or system-level fault).", 0.5)
        if "out of memory" in text or "killed" in text:
            add("Memory exhaustion.", 0.6)

        if "high_memory" in codes:
            add("Memory usage exceeded expected limits.", 0.6)
        if "high_cpu" in codes:
            add("CPU saturation likely caused slowdowns or timeouts.", 0.5)
        if "ae_anomaly" in codes:
            add("Behavior deviated from baseline metrics.", 0.5)

        # De-duplicate reasons
        seen = set()
        unique = []
        for item in out:
            if item["reason"] in seen:
                continue
            seen.add(item["reason"])
            unique.append(item)
        return unique


class LLMRootCauseAgent(BaseAgent):
    """LLM-based root-cause hypotheses using local Ollama model."""

    def __init__(self, model: str = None, max_logs: int = 80, enabled: bool = True):
        self.model = model
        self.max_logs = max_logs
        self.enabled = enabled
        self.logs: List[str] = []
        self.findings: List[Dict] = []

    def handle(self, event: Event, context: Dict) -> List[Event]:
        if not self.enabled:
            return []
        if event.type == "log":
            msg = event.data.get("message", "")
            if msg:
                self.logs.append(msg)
                if len(self.logs) > self.max_logs:
                    self.logs = self.logs[-self.max_logs :]
            return []
        if event.type == "finding":
            self.findings.append(event.data)
            return []
        if event.type == "process_exit":
            hypotheses = generate_root_cause(self.logs, self.findings, model=self.model)
            if hypotheses:
                return [Event("root_cause_llm", {"hypotheses": hypotheses})]
        return []


class ReporterAgent(BaseAgent):
    """Logs events, prints output, and prepares summary data."""

    def __init__(self, log_dir: str, csv_metrics: bool, show_logs: bool, show_metrics: bool):
        self.logger = SessionLogger(log_dir, csv_metrics=csv_metrics)
        self.show_logs = show_logs
        self.show_metrics = show_metrics
        self.metrics_samples: List[Dict] = []
        self.findings_total = 0
        self.exit_code: Optional[int] = None
        self.root_causes: List[Dict] = []
        self.root_causes_llm: List[Dict] = []

    def handle(self, event: Event, context: Dict) -> List[Event]:
        if event.type == "log":
            self.logger.log_event("logs", event.data)
            if self.show_logs:
                print(f"[LOG:{event.data['stream']}] {event.data['message']}")

        elif event.type == "metrics":
            self.metrics_samples.append(event.data)
            self.logger.log_event("metrics", event.data)
            self.logger.log_metrics_csv(event.data)
            if self.show_metrics:
                mem_mb = event.data["mem_bytes"] / (1024 * 1024) if event.data["mem_bytes"] else 0
                print(
                    f"[METRIC] cpu={event.data['cpu_percent']:.1f}% mem={mem_mb:.1f}MB status={event.data['status']}"
                )

        elif event.type == "finding":
            self.findings_total += 1
            self.logger.log_event("findings", event.data)
            print(f"[ISSUE] {event.data['severity']}: {event.data['code']} - {event.data['detail']}")
            if event.data.get("code") == "ae_anomaly" and event.data.get("severity") == "error":
                context["anomaly_error"] = True

        elif event.type == "adjustment":
            self.logger.log_event("adjustments", event.data)

        elif event.type == "process_exit":
            self.exit_code = event.data.get("exit_code")
        elif event.type == "root_cause":
            self.root_causes = event.data.get("hypotheses", [])
            self.logger.log_event("root_cause", {"hypotheses": self.root_causes})
            if self.root_causes:
                print("[ROOT-CAUSE]")
                for h in self.root_causes:
                    print(f"- {h['reason']} (conf {h['confidence']})")
        elif event.type == "root_cause_llm":
            self.root_causes_llm = event.data.get("hypotheses", [])
            self.logger.log_event("root_cause_llm", {"hypotheses": self.root_causes_llm})
            if self.root_causes_llm:
                print("[ROOT-CAUSE LLM]")
                for h in self.root_causes_llm:
                    print(f"- {h['reason']} (conf {h['confidence']})")

        return []

    def summary(self, cmd: str, duration: float, ae_enabled: bool, anomaly_error: bool) -> Dict:
        cpu_avg = 0.0
        mem_peak = 0
        if self.metrics_samples:
            cpu_avg = sum(m.get("cpu_percent", 0) for m in self.metrics_samples) / len(self.metrics_samples)
            mem_peak = max(m.get("mem_bytes", 0) for m in self.metrics_samples)

        summary = {
            "command": cmd,
            "exit_code": self.exit_code,
            "duration_sec": round(duration, 2),
            "cpu_avg": round(cpu_avg, 2),
            "mem_peak_bytes": mem_peak,
            "ae_enabled": ae_enabled,
            "anomaly_error": anomaly_error,
            "events": self.logger.counts,
            "findings_total": self.findings_total,
            "root_cause": self.root_causes,
            "root_cause_llm": self.root_causes_llm,
        }
        return summary

    def close(self, summary: Dict) -> None:
        self.logger.write_summary(summary)
        self.logger.close()
