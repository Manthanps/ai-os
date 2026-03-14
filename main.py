"""Terminal entrypoint for AI debugging monitor and log replay."""

import argparse
import json
import os
import signal
import sys
import time
from typing import Dict

# Allow running as a script without package install
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
if SCRIPT_DIR not in sys.path:
    sys.path.append(SCRIPT_DIR)

from agents import AnalyzerAgent, BrainAgent, EventBus, MonitorAgent, ReporterAgent, RootCauseAgent, LLMRootCauseAgent


def run_monitor(args: argparse.Namespace) -> int:
    """Run monitoring loop for a command and emit structured logs."""
    print(f"[INFO] Starting monitor (PID: {os.getpid()})")
    print(f"[INFO] Command: {args.cmd}")

    context: Dict = {"throttle_seconds": 0.0, "anomaly_error": False}

    reporter = ReporterAgent(
        log_dir=args.log_dir,
        csv_metrics=args.csv,
        show_logs=args.show_logs,
        show_metrics=args.show_metrics,
    )
    analyzer = AnalyzerAgent(
        ae_enabled=args.ae,
        ae_window=args.ae_window,
        ae_min_train=args.ae_min_train,
        ae_components=args.ae_components,
        ae_z=args.ae_z,
    )
    brain = BrainAgent(logger=reporter.logger)

    root_cause = RootCauseAgent()
    llm_root = LLMRootCauseAgent(model=args.llm_model, enabled=args.llm_root_cause)
    bus = EventBus([reporter, analyzer, brain, root_cause, llm_root], context)
    monitor = MonitorAgent(args.cmd, interval=args.interval, duration=args.duration)
    monitor.start()

    start = time.time()
    try:
        while True:
            events = monitor.tick()
            for ev in events:
                bus.publish(ev)

            if monitor.done:
                # Drain any remaining logs after process exit
                for ev in monitor.drain_remaining_logs():
                    bus.publish(ev)
                break

            sleep_for = args.interval + float(context.get("throttle_seconds", 0.0))
            time.sleep(max(0.1, sleep_for))

    except KeyboardInterrupt:
        print("[INFO] Interrupted by user. Terminating process.")
        monitor.terminate()

    duration = time.time() - start
    summary = reporter.summary(
        cmd=args.cmd,
        duration=duration,
        ae_enabled=bool(args.ae),
        anomaly_error=bool(context.get("anomaly_error")),
    )
    reporter.close(summary)

    print("[INFO] Monitoring complete.")
    print(json.dumps(summary, indent=2))
    return int(summary.get("exit_code") or 0)


def run_replay(args: argparse.Namespace) -> int:
    """Replay a JSONL session log to the terminal."""
    if not os.path.exists(args.log):
        print(f"[ERROR] Log file not found: {args.log}")
        return 1
    with open(args.log, "r", encoding="utf-8") as fh:
        for line in fh:
            try:
                record = json.loads(line)
            except Exception:
                continue
            ts = record.get("ts")
            etype = record.get("type")
            data = record.get("data")
            print(f"[{etype}] {ts}: {data}")
    return 0


def run_stop(args: argparse.Namespace) -> int:
    """Stop a running monitor process by PID."""
    try:
        os.kill(args.pid, signal.SIGTERM)
        print(f"[INFO] Sent SIGTERM to PID {args.pid}")
        return 0
    except Exception as e:
        print(f"[ERROR] Failed to stop PID {args.pid}: {e}")
        return 1


def build_parser() -> argparse.ArgumentParser:
    """Build CLI argument parser."""
    parser = argparse.ArgumentParser(description="Terminal AI Debugger")
    sub = parser.add_subparsers(dest="command")

    p_monitor = sub.add_parser("monitor", help="Start monitoring a command")
    p_monitor.add_argument("--cmd", required=True, help="Command to run and monitor")
    p_monitor.add_argument("--interval", type=float, default=1.0, help="Polling interval seconds")
    p_monitor.add_argument("--duration", type=float, default=0, help="Auto-stop after N seconds")
    p_monitor.add_argument("--log-dir", default=os.path.join(SCRIPT_DIR, "logs"), help="Log output directory")
    p_monitor.add_argument("--csv", action="store_true", help="Write metrics CSV")
    p_monitor.add_argument("--show-logs", action="store_true", help="Print stdout/stderr lines")
    p_monitor.add_argument("--show-metrics", action="store_true", help="Print metrics to terminal")
    p_monitor.add_argument("--ae", action="store_true", help="Enable encoder/decoder anomaly detection")
    p_monitor.add_argument("--ae-window", type=int, default=60, help="AE training window size")
    p_monitor.add_argument("--ae-min-train", type=int, default=30, help="AE minimum samples before training")
    p_monitor.add_argument("--ae-components", type=int, default=2, help="AE PCA components")
    p_monitor.add_argument("--ae-z", type=float, default=3.0, help="AE z-score threshold")
    p_monitor.add_argument("--llm-root-cause", action="store_true", help="Enable LLM root-cause analysis")
    p_monitor.add_argument("--llm-model", default=None, help="Ollama model name for LLM root-cause")
    p_monitor.set_defaults(func=run_monitor)

    p_replay = sub.add_parser("replay", help="Replay a JSONL log")
    p_replay.add_argument("--log", required=True, help="Path to session_*.jsonl")
    p_replay.set_defaults(func=run_replay)

    p_stop = sub.add_parser("stop", help="Stop a running monitor by PID")
    p_stop.add_argument("--pid", type=int, required=True, help="PID of monitor process")
    p_stop.set_defaults(func=run_stop)

    return parser


def main() -> int:
    """CLI main entrypoint."""
    parser = build_parser()
    args = parser.parse_args()
    if not args.command:
        parser.print_help()
        return 1
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
