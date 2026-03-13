import json
import os
import re
import subprocess
import time
import sys
import shutil
from typing import Dict, List, Optional, Tuple
from urllib.parse import urlsplit

import web_filter


CONFIG_PATH = os.path.join(os.path.dirname(__file__), "filter_config.yaml")
STATE_PATH = os.path.join(os.path.dirname(__file__), "parental_state.json")
SLEEP_REENABLE_SECONDS = 60

EXTERNAL_LISTS = [
    "/Users/manthan/Library/Containers/net.whatsapp.WhatsApp/Data/tmp/documents/1FADAE72-2AB9-4335-9789-56B59AF71FCB/fraud websites.txt",
    "/Users/manthan/Library/Containers/net.whatsapp.WhatsApp/Data/tmp/documents/A69372E3-890F-418D-8D37-C8D20AAD7DC2/banned.txt",
    "/Users/manthan/Library/Containers/net.whatsapp.WhatsApp/Data/tmp/documents/E4A8C665-6535-4EA7-8890-EDBD210E19BC/adult content.txt",
]

DEFAULT_BLOCKED_KEYWORDS = [
    "nuclearbomb",
    "bomb making",
    "bomb making process",
    "hacking websites",
    "extortion",
    "rape",
    "violence",
    "sexual violence",
    "sexual violance",
]

_CACHE: Optional[Tuple[List[str], List[str]]] = None


def _boot_id() -> Optional[str]:
    try:
        if os.name == "posix":
            if sys_platform() == "darwin":
                out = subprocess.check_output(["sysctl", "-n", "kern.boottime"], text=True).strip()
                m = re.search(r"sec\\s*=\\s*(\\d+)", out)
                return m.group(1) if m else None
            # Linux: /proc/stat btime
            if os.path.exists("/proc/stat"):
                with open("/proc/stat", "r", encoding="utf-8") as f:
                    for line in f:
                        if line.startswith("btime"):
                            return line.split()[1]
    except Exception:
        return None
    return None


def sys_platform() -> str:
    return "darwin" if sys.platform.startswith("darwin") else sys.platform


def _load_state() -> Dict[str, object]:
    if not os.path.exists(STATE_PATH):
        return {"enabled": True, "last_active": time.time(), "boot_id": _boot_id()}
    try:
        with open(STATE_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data
    except Exception:
        return {"enabled": True, "last_active": time.time(), "boot_id": _boot_id()}


def _save_state(state: Dict[str, object]) -> None:
    try:
        with open(STATE_PATH, "w", encoding="utf-8") as f:
            json.dump(state, f)
    except Exception:
        pass


def ensure_enabled() -> None:
    state = _load_state()
    boot = _boot_id()
    last = float(state.get("last_active", 0) or 0)
    enabled = bool(state.get("enabled", True))
    if boot and state.get("boot_id") != boot:
        enabled = True
    if time.time() - last > SLEEP_REENABLE_SECONDS:
        enabled = True
    state["enabled"] = enabled
    state["last_active"] = time.time()
    state["boot_id"] = boot
    _save_state(state)


def is_enabled() -> bool:
    state = _load_state()
    return bool(state.get("enabled", True))


def _require_login_password() -> bool:
    if os.name == "posix" and shutil.which("sudo"):
        subprocess.run(["sudo", "-k"], check=False)
        res = subprocess.run(["sudo", "-v"])
        return res.returncode == 0
    return False


def disable_with_password() -> bool:
    if not _require_login_password():
        return False
    state = _load_state()
    state["enabled"] = False
    state["last_active"] = time.time()
    state["boot_id"] = _boot_id()
    _save_state(state)
    return True


def enable_now() -> None:
    state = _load_state()
    state["enabled"] = True
    state["last_active"] = time.time()
    state["boot_id"] = _boot_id()
    _save_state(state)


def _normalize_host(host: str) -> str:
    h = host.lower().strip()
    if h.startswith("www."):
        h = h[4:]
    return h


def _is_url(text: str) -> bool:
    return text.startswith("http://") or text.startswith("https://")


def _load_lines(path: str) -> List[str]:
    if not os.path.exists(path):
        return []
    try:
        with open(path, "r", encoding="utf-8") as f:
            return [line.strip() for line in f.read().splitlines() if line.strip()]
    except Exception:
        return []


def _classify_line(line: str) -> Tuple[List[str], List[str]]:
    sites: List[str] = []
    keywords: List[str] = []
    raw = line.strip()
    if not raw:
        return sites, keywords

    compact = raw.replace(" ", "")
    lower = raw.lower()

    if _is_url(lower):
        host = urlsplit(lower).hostname
        if host:
            sites.append(_normalize_host(host))
            return sites, keywords

    # Domain-like tokens (with dots) become site blocks.
    if "." in compact and " " not in raw:
        sites.append(_normalize_host(compact))
        return sites, keywords

    # Otherwise treat as keyword.
    keywords.append(lower)
    # Also add compact form to catch spaced domains like "h anime.com"
    if "." in compact:
        sites.append(_normalize_host(compact))
    return sites, keywords


def _load_rules() -> Tuple[List[str], List[str]]:
    global _CACHE
    if _CACHE is not None:
        return _CACHE

    sites: List[str] = []
    keywords: List[str] = []

    # Config rules
    try:
        cfg = web_filter._load_config(CONFIG_PATH)
        sites += [_normalize_host(x) for x in cfg.get("blocked_sites", [])]
        keywords += [x.lower() for x in cfg.get("blocked_keywords", [])]
    except Exception:
        pass

    # External lists
    for path in EXTERNAL_LISTS:
        for line in _load_lines(path):
            s, k = _classify_line(line)
            sites += s
            keywords += k

    # Default safety keywords
    keywords += [k.lower() for k in DEFAULT_BLOCKED_KEYWORDS]

    # Dedup
    sites = sorted(set(sites))
    keywords = sorted(set(keywords))
    _CACHE = (sites, keywords)
    return _CACHE


def should_block_text(text: str) -> Optional[str]:
    if not text:
        return None
    ensure_enabled()
    if not is_enabled():
        return None
    sites, keywords = _load_rules()
    t = text.lower()

    for kw in keywords:
        if kw and kw in t:
            return f"keyword:{kw}"

    for url in re.findall(r"https?://\\S+", text, flags=re.I):
        host = urlsplit(url).hostname or ""
        host = _normalize_host(host)
        if host and host in sites:
            return f"domain:{host}"

    # Domain-like tokens inside text
    tokens = re.findall(r"[a-zA-Z0-9.-]+\\.[a-zA-Z]{2,}", text)
    for tok in tokens:
        host = _normalize_host(tok)
        if host in sites:
            return f"domain:{host}"

    return None


def should_block_url(url: str) -> Optional[str]:
    ensure_enabled()
    if not is_enabled():
        return None
    sites, keywords = _load_rules()
    parts = urlsplit(url)
    host = _normalize_host(parts.hostname or url)
    if host in sites:
        return f"domain:{host}"
    lower = url.lower()
    for kw in keywords:
        if kw and kw in lower:
            return f"keyword:{kw}"
    return None
