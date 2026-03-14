"""Process monitoring utilities (CPU/memory + stdout/stderr)."""

import os
import queue
import subprocess
import threading
from dataclasses import dataclass
from typing import Tuple

try:
    import psutil  # type: ignore
except Exception:
    psutil = None


@dataclass
class ProcStats:
    pid: int
    cpu_percent: float
    mem_bytes: int
    status: str


class ProcessMonitor:
    """Run a command and periodically sample process stats."""

    def __init__(self, interval: float = 1.0):
        self.interval = interval
        self._stop = threading.Event()

    def stop(self) -> None:
        """Signal the monitor to stop."""
        self._stop.set()

    def run_command(self, cmd: str) -> Tuple[subprocess.Popen, queue.Queue]:
        """Start a subprocess and stream stdout/stderr into a queue."""
        q: queue.Queue = queue.Queue()
        proc = subprocess.Popen(
            cmd,
            shell=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
        )
        threading.Thread(target=self._stream, args=(proc.stdout, q, "stdout"), daemon=True).start()
        threading.Thread(target=self._stream, args=(proc.stderr, q, "stderr"), daemon=True).start()
        return proc, q

    def _stream(self, stream, q: queue.Queue, name: str) -> None:
        """Read stream line-by-line and push into queue."""
        if stream is None:
            return
        for line in stream:
            q.put((name, line.rstrip("\n")))

    def poll_stats(self, pid: int) -> ProcStats:
        """Return CPU/memory usage for a process ID."""
        if psutil:
            p = psutil.Process(pid)
            cpu = p.cpu_percent(interval=None)
            mem = p.memory_info().rss
            status = p.status()
            return ProcStats(pid, cpu, mem, status)
        # Fallback: best-effort on POSIX
        cpu, mem = self._posix_stats(pid)
        return ProcStats(pid, cpu, mem, "unknown")

    def _posix_stats(self, pid: int) -> Tuple[float, int]:
        """POSIX fallback stats collection using 'ps'."""
        if os.name != "posix":
            return 0.0, 0
        try:
            out = subprocess.check_output(["ps", "-o", "%cpu=,rss=", "-p", str(pid)], text=True).strip()
            if not out:
                return 0.0, 0
            parts = out.split()
            cpu = float(parts[0])
            rss_kb = int(parts[1])
            return cpu, rss_kb * 1024
        except Exception:
            return 0.0, 0
