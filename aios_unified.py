import json
import os
import platform
import shlex
import shutil
import signal
import socket
import subprocess
import webbrowser
import time
from pathlib import Path
import os_actions


def _run(cmd):
    return subprocess.check_output(cmd, text=True, stderr=subprocess.STDOUT).strip()


def _is_linux():
    return platform.system().lower() == "linux"


def _is_macos():
    return platform.system().lower() == "darwin"


MEMORY_FILE = os.path.join(os.path.dirname(__file__), "memory.json")


def _load_memory():
    if os.path.exists(MEMORY_FILE):
        try:
            with open(MEMORY_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except (OSError, json.JSONDecodeError):
            return {}
    return {}


def _save_memory(memory):
    with open(MEMORY_FILE, "w", encoding="utf-8") as f:
        json.dump(memory, f, indent=2)


def _df_storage():
    entries = []
    try:
        output = _run(["df", "-kP"])  # POSIX-ish format
    except subprocess.CalledProcessError:
        return entries
    lines = output.splitlines()[1:]
    for line in lines:
        parts = line.split()
        if len(parts) < 6:
            continue
        filesystem, blocks_kb, used_kb, avail_kb, _cap, mount = parts[:6]
        try:
            total = int(blocks_kb) * 1024
            free = int(avail_kb) * 1024
        except ValueError:
            total = None
            free = None
        entries.append({
            "name": filesystem,
            "mount": mount,
            "total_bytes": total,
            "free_bytes": free,
        })
    return entries


def _mac_cpu_info():
    try:
        model = _run(["sysctl", "-n", "machdep.cpu.brand_string"])
    except subprocess.CalledProcessError:
        model = None
        try:
            model = _run(["sysctl", "-n", "hw.model"])
        except subprocess.CalledProcessError:
            model = None
    try:
        physical = int(_run(["sysctl", "-n", "hw.physicalcpu"]))
    except (ValueError, subprocess.CalledProcessError):
        physical = None
    try:
        logical = int(_run(["sysctl", "-n", "hw.logicalcpu"]))
    except (ValueError, subprocess.CalledProcessError):
        logical = None
    return {"model": model, "cores_physical": physical, "cores_logical": logical}


def _mac_memory_info():
    try:
        total = int(_run(["sysctl", "-n", "hw.memsize"]))
    except (ValueError, subprocess.CalledProcessError):
        total = None
    try:
        vm_stat = _run(["vm_stat"])
    except subprocess.CalledProcessError:
        vm_stat = ""
    lines = vm_stat.splitlines()
    page_size = 4096
    if lines:
        first = lines[0]
        if "page size of" in first:
            try:
                page_size = int(first.split("page size of")[1].split("bytes")[0].strip())
            except (ValueError, IndexError):
                page_size = 4096
    free_pages = 0
    for line in lines[1:]:
        if line.startswith("Pages free"):
            free_pages = int(line.split(":")[1].strip().strip("."))
            break
    free = free_pages * page_size
    return {"total_bytes": total, "free_bytes": free}


def _linux_cpu_info():
    model = None
    try:
        with open("/proc/cpuinfo", "r", encoding="utf-8") as f:
            for line in f:
                if line.lower().startswith("model name"):
                    model = line.split(":", 1)[1].strip()
                    break
    except OSError:
        model = None

    logical = os.cpu_count() or 0
    physical = None
    try:
        lscpu = _run(["lscpu", "-p=core"]).splitlines()
        core_ids = {line for line in lscpu if line and not line.startswith("#")}
        if core_ids:
            physical = len(core_ids)
    except (subprocess.CalledProcessError, FileNotFoundError):
        physical = None

    return {"model": model, "cores_physical": physical, "cores_logical": logical}


def _linux_memory_info():
    total = None
    free = None
    try:
        with open("/proc/meminfo", "r", encoding="utf-8") as f:
            for line in f:
                if line.startswith("MemTotal"):
                    total = int(line.split()[1]) * 1024
                elif line.startswith("MemAvailable"):
                    free = int(line.split()[1]) * 1024
    except OSError:
        total = None
        free = None
    return {"total_bytes": total, "free_bytes": free}


def get_system_info():
    system = platform.system()
    os_info = {
        "name": system,
        "release": platform.release(),
        "version": platform.version(),
    }

    if _is_macos():
        cpu = _mac_cpu_info()
        memory = _mac_memory_info()
    elif _is_linux():
        cpu = _linux_cpu_info()
        memory = _linux_memory_info()
    else:
        cpu = {"model": None, "cores_physical": None, "cores_logical": os.cpu_count()}
        memory = {"total_bytes": None, "free_bytes": None}

    storage = _df_storage()

    return {
        "os": os_info,
        "cpu": cpu,
        "memory": memory,
        "storage": storage,
    }


def list_processes():
    try:
        output = _run(["ps", "-e", "-o", "pid=,comm="])
    except subprocess.CalledProcessError:
        return []
    results = []
    for line in output.splitlines():
        line = line.strip()
        if not line:
            continue
        parts = line.split(None, 1)
        if len(parts) != 2:
            continue
        pid_str, cmd = parts
        try:
            pid = int(pid_str)
        except ValueError:
            continue
        results.append({"pid": pid, "command": cmd})
    return results


def kill_process(pid):
    try:
        os.kill(pid, signal.SIGTERM)
    except ProcessLookupError:
        raise ValueError("Process not found.")


def start_process(command):
    if isinstance(command, str):
        args = shlex.split(command)
    else:
        args = command
    proc = subprocess.Popen(args)
    return proc.pid


def fs_list(path="."):
    if not os.path.exists(path):
        raise ValueError("Path does not exist.")
    entries = []
    for name in os.listdir(path):
        full = os.path.join(path, name)
        try:
            stat = os.stat(full)
        except OSError:
            stat = None
        entries.append({
            "name": name,
            "path": full,
            "is_dir": os.path.isdir(full),
            "size_bytes": stat.st_size if stat else None,
        })
    return entries


def fs_mkdir(path):
    os.makedirs(path, exist_ok=True)


def fs_rm(path):
    if not os.path.exists(path):
        raise ValueError("Path does not exist.")
    if os.path.isdir(path):
        shutil.rmtree(path)
    else:
        os.remove(path)


def env_vars():
    return dict(os.environ)


def current_dir():
    return os.getcwd()


def change_dir(path):
    if not path:
        raise ValueError("Path is required.")
    if not os.path.exists(path):
        raise ValueError("Path does not exist.")
    os.chdir(path)
    return os.getcwd()


def make_dir(name):
    if not name:
        raise ValueError("Directory name is required.")
    os.mkdir(name)
    return name


def remove_dir(name):
    if not name:
        raise ValueError("Directory name is required.")
    if not os.path.isdir(name):
        raise ValueError("Directory not found.")
    os.rmdir(name)
    return name


def process_id():
    return os.getpid()


def fs_move(src, dst):
    if not os.path.exists(src):
        raise ValueError("Source path does not exist.")
    shutil.move(src, dst)


def fs_copy(src, dst):
    if not os.path.exists(src):
        raise ValueError("Source path does not exist.")
    if os.path.isdir(src):
        if os.path.exists(dst):
            raise ValueError("Destination already exists.")
        shutil.copytree(src, dst)
    else:
        shutil.copy2(src, dst)


def write_file(path, content):
    if not path:
        raise ValueError("File path is required.")
    with open(path, "w") as f:
        f.write(content or "")
    return path

def network_info():
    hostname = socket.gethostname()
    addresses = set()
    try:
        for info in socket.getaddrinfo(hostname, None):
            addresses.add(info[4][0])
    except socket.gaierror:
        pass

    ip_addresses = [addr for addr in addresses if not addr.startswith("127.")]
    return {
        "hostname": hostname,
        "ip_addresses": sorted(ip_addresses),
    }


def memory_warning(threshold_free_ratio=0.1):
    info = get_system_info()
    total = info["memory"].get("total_bytes")
    free = info["memory"].get("free_bytes")
    if not total or free is None:
        return {"status": "unknown", "message": "Memory info unavailable."}
    free_ratio = free / total
    if free_ratio <= threshold_free_ratio:
        return {
            "status": "warning",
            "message": "Low memory detected.",
            "free_ratio": round(free_ratio, 4),
        }
    return {
        "status": "ok",
        "message": "Memory level is healthy.",
        "free_ratio": round(free_ratio, 4),
    }


def list_usb_devices():
    if _is_macos():
        try:
            output = _run(["system_profiler", "SPUSBDataType"])
            return {"platform": "macos", "devices_raw": output}
        except subprocess.CalledProcessError:
            return {"platform": "macos", "devices_raw": ""}
    if _is_linux():
        try:
            output = _run(["lsusb"])
            return {"platform": "linux", "devices_raw": output}
        except (subprocess.CalledProcessError, FileNotFoundError):
            return {"platform": "linux", "devices_raw": ""}
    return {"platform": platform.system(), "devices_raw": "Not supported yet."}


def list_external_storage():
    if _is_macos():
        try:
            output = _run(["diskutil", "list", "external"])
            return {"platform": "macos", "storage_raw": output}
        except subprocess.CalledProcessError:
            return {"platform": "macos", "storage_raw": ""}
    if _is_linux():
        try:
            output = _run(["lsblk", "-o", "NAME,TRAN,SIZE,MOUNTPOINT"])
            return {"platform": "linux", "storage_raw": output}
        except (subprocess.CalledProcessError, FileNotFoundError):
            return {"platform": "linux", "storage_raw": ""}
    return {"platform": platform.system(), "storage_raw": "Not supported yet."}


def list_network_interfaces():
    if _is_macos() or _is_linux():
        try:
            output = _run(["ifconfig"])
            return {"platform": platform.system().lower(), "interfaces_raw": output}
        except subprocess.CalledProcessError:
            return {"platform": platform.system().lower(), "interfaces_raw": ""}
    return {"platform": platform.system(), "interfaces_raw": "Not supported yet."}


def _normalize_url(site):
    s = site.strip()
    if s.startswith("http://") or s.startswith("https://"):
        return s
    if "." in s and " " not in s:
        return f"https://{s}"
    return None


def open_website(site, preferred_browser=None):
    # Optional safety filter check (if config exists).
    try:
        import web_filter  # type: ignore
    except Exception:
        web_filter = None
    if web_filter is not None:
        try:
            cfg_path = os.path.join(os.path.dirname(__file__), "filter_config.yaml")
            if os.path.exists(cfg_path):
                url = _normalize_url(site) or f"https://www.google.com/search?q={site}"
                reason = web_filter.check_url(url, cfg_path)
                if reason:
                    return {"status": "blocked", "reason": "adult", "url": url}
        except Exception:
            pass

    memory = _load_memory()

    if preferred_browser:
        memory[site] = preferred_browser
        _save_memory(memory)
        browser_name = preferred_browser
    elif site in memory:
        browser_name = memory[site]
    else:
        browser_name = None

    url = _normalize_url(site)
    if url is None:
        url = f"https://www.google.com/search?q={site}"

    if browser_name:
        try:
            if _is_macos():
                subprocess.check_call(["open", "-a", browser_name, url])
                return {"site": site, "browser": browser_name, "url": url}
            browser = webbrowser.get(browser_name)
            browser.open_new_tab(url)
            return {"site": site, "browser": browser_name, "url": url}
        except (webbrowser.Error, subprocess.CalledProcessError):
            # Fall back to default browser if the named one isn't available.
            webbrowser.open_new_tab(url)
            return {"site": site, "browser": "default", "url": url}

    webbrowser.open_new_tab(url)
    return {"site": site, "browser": "default", "url": url}


def open_youtube_search(query, preferred_browser=None):
    query = (query or "").strip()
    if not query:
        raise ValueError("Query is required.")
    url = f"https://www.youtube.com/results?search_query={query.replace(' ', '+')}"
    return open_website(url, preferred_browser)


def open_app(app_name):
    app_name = app_name.strip()
    if not app_name:
        raise ValueError("App name is required.")

    system = platform.system().lower()
    if system == "darwin":
        subprocess.check_call(["open", "-a", app_name])
        try:
            subprocess.check_call(
                ["osascript", "-e", f'tell application "{app_name}" to activate']
            )
        except subprocess.CalledProcessError:
            pass
        return {"status": "opened", "app": app_name, "platform": "macos"}
    if system == "linux":
        try:
            subprocess.Popen([app_name])
            return {"status": "opened", "app": app_name, "platform": "linux"}
        except OSError:
            subprocess.check_call(["xdg-open", app_name])
            return {"status": "opened", "app": app_name, "platform": "linux"}
    if system == "windows":
        subprocess.check_call(["cmd", "/c", "start", "", app_name], shell=False)
        return {"status": "opened", "app": app_name, "platform": "windows"}

    raise ValueError(f"Unsupported platform: {platform.system()}")


def copy_to_clipboard(text):
    if not text:
        return False
    system = platform.system().lower()
    try:
        if system == "darwin":
            p = subprocess.Popen(["pbcopy"], stdin=subprocess.PIPE)
            p.communicate(input=text.encode("utf-8"))
            return True
        if system == "linux":
            p = subprocess.Popen(["xclip", "-selection", "clipboard"], stdin=subprocess.PIPE)
            p.communicate(input=text.encode("utf-8"))
            return True
        if system == "windows":
            p = subprocess.Popen(["clip"], stdin=subprocess.PIPE, shell=True)
            p.communicate(input=text.encode("utf-8"))
            return True
    except Exception:
        return False
    return False


def close_app(app_name):
    app_name = app_name.strip()
    if not app_name:
        raise ValueError("App name is required.")
    system = platform.system().lower()
    if system == "darwin":
        subprocess.check_call(["osascript", "-e", f'tell application "{app_name}" to quit'])
        return {"status": "closed", "app": app_name, "platform": "macos"}
    if system == "linux":
        subprocess.check_call(["pkill", "-f", app_name])
        return {"status": "closed", "app": app_name, "platform": "linux"}
    if system == "windows":
        subprocess.check_call(["taskkill", "/IM", app_name, "/F"])
        return {"status": "closed", "app": app_name, "platform": "windows"}
    raise ValueError(f"Unsupported platform: {platform.system()}")


def _escape_osascript(text):
    return text.replace("\\", "\\\\").replace("\"", "\\\"")


def type_text(text):
    text = (text or "").strip()
    if not text:
        raise ValueError("Text is required.")
    system = platform.system().lower()
    if system == "darwin":
        safe = _escape_osascript(text)
        subprocess.check_call(
            ["osascript", "-e", f'tell application "System Events" to keystroke "{safe}"']
        )
        return {"status": "typed", "platform": "macos"}
    if system == "linux":
        subprocess.check_call(["xdotool", "type", "--delay", "20", "--clearmodifiers", text])
        return {"status": "typed", "platform": "linux"}
    if system == "windows":
        safe = text.replace("^", "^^").replace("%", "%%").replace("~", "{ENTER}")
        cmd = [
            "powershell",
            "-NoProfile",
            "-Command",
            "Add-Type -AssemblyName System.Windows.Forms; "
            f"[System.Windows.Forms.SendKeys]::SendWait('{safe}')",
        ]
        subprocess.check_call(cmd)
        return {"status": "typed", "platform": "windows"}
    raise ValueError(f"Unsupported platform: {platform.system()}")


def activate_app(app_name):
    app_name = (app_name or "").strip()
    if not app_name:
        raise ValueError("App name is required.")
    system = platform.system().lower()
    if system == "darwin":
        subprocess.check_call(
            ["osascript", "-e", f'tell application "{app_name}" to activate']
        )
        return {"status": "activated", "app": app_name, "platform": "macos"}
    if system == "linux":
        # Best-effort; requires wmctrl installed.
        subprocess.check_call(["wmctrl", "-a", app_name])
        return {"status": "activated", "app": app_name, "platform": "linux"}
    if system == "windows":
        # Best-effort; requires PowerShell + AppActivate by window title.
        cmd = [
            "powershell",
            "-NoProfile",
            "-Command",
            f"$ws = New-Object -ComObject WScript.Shell; $ws.AppActivate('{app_name}')",
        ]
        subprocess.check_call(cmd)
        return {"status": "activated", "app": app_name, "platform": "windows"}
    raise ValueError(f"Unsupported platform: {platform.system()}")


def frontmost_app():
    system = platform.system().lower()
    if system == "darwin":
        try:
            name = _run([
                "osascript",
                "-e",
                'tell application "System Events" to get name of first application process whose frontmost is true',
            ])
            return name.strip()
        except Exception:
            return None
    return None


def ensure_app_frontmost(app_name, attempts=6, delay=0.4):
    system = platform.system().lower()
    if system != "darwin":
        return True
    target = (app_name or "").strip().lower()
    for _ in range(max(1, attempts)):
        try:
            activate_app(app_name)
        except Exception:
            pass
        current = frontmost_app()
        if current and target and target in current.lower():
            return True
        time.sleep(delay)
    return False


def click_menu(app_name, menu, item):
    app_name = (app_name or "").strip()
    menu = (menu or "").strip()
    item = (item or "").strip()
    if not app_name or not menu or not item:
        raise ValueError("App name, menu, and item are required.")
    system = platform.system().lower()
    if system == "darwin":
        script = (
            f'tell application "{app_name}" to activate\n'
            'tell application "System Events"\n'
            f'  tell process "{app_name}"\n'
            f'    click menu item "{item}" of menu "{menu}" of menu bar 1\n'
            "  end tell\n"
            "end tell"
        )
        subprocess.check_call(["osascript", "-e", script])
        return {"status": "clicked", "app": app_name, "menu": menu, "item": item, "platform": "macos"}
    raise ValueError(f"Menu click not supported on: {platform.system()}")


def press_key(key):
    key = (key or "").strip().lower()
    if not key:
        raise ValueError("Key is required.")
    system = platform.system().lower()
    if system == "darwin":
        if key in {"enter", "return"}:
            subprocess.check_call(["osascript", "-e", 'tell application "System Events" to keystroke return'])
        elif key in {"up", "down", "left", "right"}:
            key_codes = {"left": 123, "right": 124, "down": 125, "up": 126}
            code = key_codes[key]
            subprocess.check_call(["osascript", "-e", f'tell application "System Events" to key code {code}'])
        else:
            safe = _escape_osascript(key)
            subprocess.check_call(["osascript", "-e", f'tell application "System Events" to keystroke "{safe}"'])
        return {"status": "pressed", "platform": "macos", "key": key}
    if system == "linux":
        key_name = "Return" if key in {"enter", "return"} else key
        subprocess.check_call(["xdotool", "key", key_name])
        return {"status": "pressed", "platform": "linux", "key": key}
    if system == "windows":
        if key in {"enter", "return"}:
            send = "{ENTER}"
        else:
            send = key
        cmd = [
            "powershell",
            "-NoProfile",
            "-Command",
            "Add-Type -AssemblyName System.Windows.Forms; "
            f"[System.Windows.Forms.SendKeys]::SendWait('{send}')",
        ]
        subprocess.check_call(cmd)
        return {"status": "pressed", "platform": "windows", "key": key}
    raise ValueError(f"Unsupported platform: {platform.system()}")


def send_hotkey(mods, key):
    mods = mods or []
    key = (key or "").strip().lower()
    if not key:
        raise ValueError("Key is required.")
    system = platform.system().lower()
    if system == "darwin":
        mod_map = {
            "cmd": "command down",
            "command": "command down",
            "ctrl": "control down",
            "control": "control down",
            "alt": "option down",
            "option": "option down",
            "shift": "shift down",
        }
        modifiers = [mod_map[m] for m in mods if m in mod_map]
        if modifiers:
            mods_str = "{" + ", ".join(modifiers) + "}"
            subprocess.check_call(
                ["osascript", "-e", f'tell application "System Events" to keystroke "{_escape_osascript(key)}" using {mods_str}']
            )
        else:
            subprocess.check_call(
                ["osascript", "-e", f'tell application "System Events" to keystroke "{_escape_osascript(key)}"']
            )
        return {"status": "hotkey", "platform": "macos", "key": key, "mods": mods}
    if system == "linux":
        mod_map = {"cmd": "Super", "command": "Super", "ctrl": "ctrl", "control": "ctrl", "alt": "alt", "shift": "shift"}
        mods_seq = [mod_map.get(m, m) for m in mods]
        seq = "+".join(mods_seq + [key])
        subprocess.check_call(["xdotool", "key", seq])
        return {"status": "hotkey", "platform": "linux", "key": key, "mods": mods}
    if system == "windows":
        mod_map = {"cmd": "^", "command": "^", "ctrl": "^", "control": "^", "alt": "%", "shift": "+"}
        prefix = "".join(mod_map.get(m, "") for m in mods)
        send = f"{prefix}{key}"
        cmd = [
            "powershell",
            "-NoProfile",
            "-Command",
            "Add-Type -AssemblyName System.Windows.Forms; "
            f"[System.Windows.Forms.SendKeys]::SendWait('{send}')",
        ]
        subprocess.check_call(cmd)
        return {"status": "hotkey", "platform": "windows", "key": key, "mods": mods}
    raise ValueError(f"Unsupported platform: {platform.system()}")


def check_accessibility():
    system = platform.system().lower()
    if system != "darwin":
        return {"status": "unknown", "message": "Accessibility check only implemented on macOS."}
    try:
        out = _run(["osascript", "-e", 'tell application "System Events" to get UI elements enabled'])
        enabled = str(out).strip().lower() in {"true", "1", "yes"}
        if enabled:
            return {"status": "ok", "message": "Accessibility enabled."}
        return {"status": "error", "message": "Accessibility disabled for UI scripting."}
    except Exception:
        return {
            "status": "error",
            "message": "Accessibility/Automation permissions not granted for this app.",
        }


def open_folder(path):
    path = path.strip()
    if not path:
        raise ValueError("Path is required.")
    if not os.path.exists(path):
        raise ValueError("Path does not exist.")
    system = platform.system().lower()
    if system == "darwin":
        subprocess.check_call(["open", path])
    elif system == "linux":
        subprocess.check_call(["xdg-open", path])
    elif system == "windows":
        subprocess.check_call(["explorer", path])
    return {"status": "opened", "path": path}


def find_file(query, root="."):
    return os_actions.find_file(query, root=root)




def _find_app_paths(app_name):
    name = app_name.lower().strip()
    candidates = []
    for base in ["/Applications", str(Path.home() / "Applications")]:
        try:
            for entry in os.listdir(base):
                if entry.lower() == f"{name}.app":
                    candidates.append(os.path.join(base, entry))
        except OSError:
            continue
    return candidates


def uninstall_app_safe(app_name):
    system = platform.system().lower()
    if system != "darwin":
        raise ValueError("Uninstall is implemented for macOS only.")

    paths = _find_app_paths(app_name)
    if not paths:
        return {"status": "not_found", "app": app_name, "paths": []}

    trash_dir = Path.home() / ".Trash"
    removed = []
    for path in paths:
        dst = trash_dir / Path(path).name
        if dst.exists():
            dst = trash_dir / f"{Path(path).stem}-old.app"
        shutil.move(path, str(dst))
        removed.append(str(dst))

    return {
        "status": "moved_to_trash",
        "app": app_name,
        "paths": removed,
        "note": "Only the app bundle was removed. User data and caches are untouched.",
    }


def _brew_info(app_name):
    try:
        output = _run(["brew", "info", "--json=v2", app_name])
        data = json.loads(output)
        deps = []
        if data.get("formulae"):
            deps = data["formulae"][0].get("dependencies", [])
        if data.get("casks"):
            deps = data["casks"][0].get("depends_on", {}).get("formula", [])
        return {"available": True, "dependencies": deps}
    except (subprocess.CalledProcessError, FileNotFoundError, json.JSONDecodeError):
        return {"available": False, "dependencies": []}


def _brew_search_casks(app_name):
    try:
        output = _run(["brew", "search", "--cask", app_name])
        results = [line.strip() for line in output.splitlines() if line.strip()]
        return results
    except (subprocess.CalledProcessError, FileNotFoundError):
        return []


def install_app(method, app_name=None, installer_path=None, brew_cask=False):
    system = platform.system().lower()
    if system != "darwin":
        raise ValueError("Install is implemented for macOS only.")

    method = method.lower().strip()
    if method == "homebrew":
        if not app_name:
            raise ValueError("App name is required for Homebrew.")
        cmd = ["brew", "install"]
        if brew_cask:
            cmd.append("--cask")
        cmd.append(app_name)
        try:
            subprocess.check_call(cmd)
            return {"status": "installed", "method": "homebrew", "app": app_name}
        except subprocess.CalledProcessError as exc:
            suggestions = _brew_search_casks(app_name) if brew_cask else []
            return {
                "status": "error",
                "method": "homebrew",
                "app": app_name,
                "error": str(exc),
                "suggestions": suggestions,
            }

    if method in {"dmg", "pkg"}:
        if not installer_path:
            raise ValueError("Installer path is required.")
        if not os.path.exists(installer_path):
            raise ValueError("Installer path does not exist.")
        subprocess.check_call(["open", installer_path])
        return {
            "status": "opened_installer",
            "method": method,
            "path": installer_path,
            "note": "Complete the installer UI to finish installation.",
        }

    if method == "appstore":
        if not app_name:
            raise ValueError("App name is required for App Store.")
        url = f"macappstore://search.itunes.apple.com/WebObjects/MZSearch.woa/wa/search?term={app_name}"
        webbrowser.open(url)
        return {"status": "opened_app_store", "method": "appstore", "app": app_name}

    raise ValueError("Unsupported method. Use homebrew, dmg, pkg, or appstore.")


def to_json(data):
    return json.dumps(data, indent=2, sort_keys=False)
