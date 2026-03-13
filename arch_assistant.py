import os
import platform
import shutil

try:
    import psutil
except Exception:
    psutil = None


class CacheSimulator:
    def __init__(self, lines=8):
        self.lines = lines
        self.cache = [None] * lines
        self.hits = 0
        self.misses = 0

    def access(self, address: int):
        index = address % self.lines
        if self.cache[index] == address:
            self.hits += 1
        else:
            self.misses += 1
            self.cache[index] = address

    def stats(self):
        total = self.hits + self.misses
        hit_rate = (self.hits / total) * 100 if total else 0
        return {"hits": self.hits, "misses": self.misses, "hit_rate": round(hit_rate, 2)}


class PipelineSimulator:
    def __init__(self):
        self.instructions = []

    def run(self, instr: str):
        self.instructions.append(instr)

    def stats(self):
        return {
            "executed": len(self.instructions),
            "last_instruction": self.instructions[-1] if self.instructions else None,
        }


_cache = CacheSimulator()
_pipeline = PipelineSimulator()


def cpu_info():
    if psutil:
        freq = psutil.cpu_freq().current if psutil.cpu_freq() else None
        return {
            "arch": platform.machine(),
            "cores": psutil.cpu_count(logical=False),
            "threads": psutil.cpu_count(logical=True),
            "freq_mhz": freq,
        }
    return {"arch": platform.machine(), "cores": os.cpu_count(), "threads": os.cpu_count(), "freq_mhz": None}


def memory_info():
    if psutil:
        mem = psutil.virtual_memory()
        return {"total": mem.total, "used": mem.used, "free": mem.available}
    total, used, free = shutil.disk_usage("/")
    return {"total": total, "used": used, "free": free}


def disk_info(path="/"):
    if psutil:
        disk = psutil.disk_usage(path)
        return {"total": disk.total, "used": disk.used, "free": disk.free}
    total, used, free = shutil.disk_usage(path)
    return {"total": total, "used": used, "free": free}


def simulate_cache():
    for addr in [1, 2, 3, 1, 5, 2, 8, 1]:
        _cache.access(addr)
    return _cache.stats()


def simulate_pipeline():
    _pipeline.run("NOP")
    return _pipeline.stats()


def run_instruction(instr: str):
    instr = instr.strip() or "NOP"
    _pipeline.run(instr)
    return {"executed": instr, **_pipeline.stats()}
