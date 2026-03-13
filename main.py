import argparse
import json
import sys
import re
import shlex
import threading
import time
import os
import subprocess
import signal

import aios_unified as unified
import llm
import memory_manager
import intent_classifier
import automation_modes
import medical_interface
import feedback_engine
import arch_assistant
import workflow_engine
import os_actions
import secure_storage
import parental_control
import debug_agent


def _print_json(data):
    print(json.dumps(data, indent=2, sort_keys=False))


def _normalize_space(text):
    return re.sub(r"\s+", " ", text).strip()


def _normalize_open_compound(text):
    t = text.strip()
    if t.lower().startswith("opwn "):
        return "open " + t[5:].strip()
    if t.lower().startswith("open") and not t.lower().startswith("open "):
        # Handle inputs like "OpenChatGPT" -> "open chatgpt"
        return "open " + t[4:].strip()
    return t


def _split_commands(text):
    t = _normalize_open_compound(text.strip())
    parallel = False
    if " simultaneously" in t.lower() or " at the same time" in t.lower():
        parallel = True
        t = re.sub(r"\s+(simultaneously|at the same time)\s*", " ", t, flags=re.I).strip()

    if ";" in t:
        parts = [p.strip() for p in t.split(";") if p.strip()]
        return parts, parallel

    if " then " in t.lower():
        parts = [p.strip() for p in re.split(r"\s+then\s+", t, flags=re.I) if p.strip()]
        if len(parts) > 1:
            return parts, parallel

    if " and " in t.lower():
        # Only split on "and" if it looks like multiple commands (multiple verbs)
        verb_hits = sum(1 for v in ["open", "list", "show", "start", "kill", "copy", "move", "create", "remove"] if v in t.lower())
        if verb_hits >= 2:
            parts = [p.strip() for p in re.split(r"\s+and\s+", t, flags=re.I) if p.strip()]
            if len(parts) > 1:
                return parts, parallel

    return [t], parallel


RETRY_INTENTS = {
    "open-website",
    "search-web",
    "youtube-play",
    "workflow",
    "fs-list",
    "fs-mkdir",
    "fs-rm",
    "fs-mv",
    "fs-cp",
}


def _execute_intent(intent, payload, command=None):
    def _run():
        return _handle_intent(intent, payload)

    retries = 1 if intent in RETRY_INTENTS else 0

    def _on_error(exc, attempt):
        debug_agent.log_error("intent", exc, intent=intent, payload=payload, command=command)

    ok, result, err = debug_agent.run_with_retry(_run, retries=retries, delay=0.5, on_error=_on_error)
    if not ok and err:
        print(f"Error: {err}")
    return result


def _parse_intent(text):
    raw = _normalize_space(text)
    t = raw.lower()
    if t in {"exit", "quit", "bye"}:
        return ("exit", {})
    if t in {"help", "menu", "options"}:
        return ("help", {})
    if t.startswith("meaning of "):
        return ("meaning", {"word": t.replace("meaning of ", "", 1).strip()})
    if t.startswith("what is meaning of "):
        return ("meaning", {"word": t.replace("what is meaning of ", "", 1).strip()})
    if t.startswith("my name is "):
        return ("set-user", {"name": t.replace("my name is ", "", 1).strip()})
    if t in {"parental status", "parental control status"}:
        return ("parental-status", {})
    if t in {"parental on", "parental control on"}:
        return ("parental-on", {})
    if t in {"parental off", "parental control off"}:
        return ("parental-off", {})
    if t in {"debug report", "debugging report"}:
        return ("debug-report", {})
    if t in {"debug watch", "watch debug"}:
        return ("debug-watch", {})
    if t.startswith("set browser "):
        return ("set-browser", {"name": t.replace("set browser ", "", 1).strip()})
    if t == "show browser":
        return ("show-browser", {})
    if t.startswith("secure write "):
        name, rest = t.replace("secure write ", "", 1).split(" and ", 1) if " and " in t else (t.replace("secure write ", "", 1), "")
        return ("secure-write", {"path": name.strip(), "content": rest.strip()})
    if t.startswith("secure read "):
        return ("secure-read", {"path": t.replace("secure read ", "", 1).strip()})
    if t.startswith("secure encrypt "):
        return ("secure-encrypt", {"path": t.replace("secure encrypt ", "", 1).strip()})
    if t.startswith("secure decrypt "):
        return ("secure-decrypt", {"path": t.replace("secure decrypt ", "", 1).strip()})
    if t in {"nlp status", "show nlp status"}:
        return ("nlp-status", {})
    if "environment" in t or "env vars" in t:
        return ("show-env", {})
    if "cpu info" in t or "check cpu" in t or t == "cpu":
        return ("cpu-info", {})
    if "ram" in t or "memory usage" in t or "check memory" in t:
        return ("memory-info", {})
    if "disk usage" in t or "check disk" in t or "storage" in t:
        return ("disk-info", {})
    if t in {"current directory", "pwd", "where am i"}:
        return ("cwd", {})
    if t.startswith("change directory to "):
        return ("chdir", {"path": t.replace("change directory to ", "", 1).strip()})
    if t.startswith("make directory "):
        return ("mkdir", {"name": t.replace("make directory ", "", 1).strip()})
    if t.startswith("remove directory "):
        return ("rmdir", {"name": t.replace("remove directory ", "", 1).strip()})
    if "show process id" in t or t == "pid":
        return ("pid", {})
    if "simulate cache" in t:
        return ("cache-sim", {})
    if "simulate pipeline" in t:
        return ("pipeline-sim", {})
    if t.startswith("run instruction "):
        return ("run-instruction", {"instr": t.replace("run instruction ", "", 1).strip()})
    if t.startswith("create file ") and " and " in t:
        name, rest = t.replace("create file ", "", 1).split(" and ", 1)
        return ("create-file-content", {"name": name.strip(), "content": rest.strip()})
    if t.startswith("create file "):
        return ("create-file", {"name": t.replace("create file ", "", 1).strip()})
    m = re.match(r"(?i)^add\s+(.+)\s+to\s+(.+)$", raw)
    if m:
        text = m.group(1).strip()
        path = m.group(2).strip()
        if (text.startswith('"') and text.endswith('"')) or (text.startswith("'") and text.endswith("'")):
            text = text[1:-1]
        return ("smart-file", {"args": ["append", path, text]})
    m = re.match(r"(?i)^display\\s+file\\s+(.+)$", raw)
    if m:
        path = m.group(1).strip()
        return ("smart-file", {"args": ["read", path]})
    m = re.match(r"(?i)^display\\s+(.+)$", raw)
    if m:
        path = m.group(1).strip()
        return ("smart-file", {"args": ["read", path]})
    m = re.match(r"(?i)^edit\s+(.+)\s+to\s+(.+)$", raw)
    if m:
        path = m.group(2).strip()
        return ("edit-file", {"path": path})
    m = re.match(r"(?i)^edit\s+(.+)$", raw)
    if m:
        path = m.group(1).strip()
        return ("edit-file", {"path": path})
    if t.startswith("file ") or t.startswith("fm ") or t.startswith("sfm ") or t.startswith("smart file "):
        if t.startswith("file "):
            rest = raw[5:]
        elif t.startswith("fm "):
            rest = raw[3:]
        elif t.startswith("sfm "):
            rest = raw[4:]
        else:
            rest = raw[11:]
        args = shlex.split(rest)
        return ("smart-file", {"args": args})
    if t.startswith("open ") and " and " in t:
        parts = t.split(" and ", 1)
        target = parts[0].replace("open ", "").strip()
        action_text = parts[1].strip()
        return ("workflow", {"target": target, "action": action_text})

    if "system info" in t or t == "system":
        return ("system-info", {})
    if "process list" in t or t == "processes":
        return ("process-list", {})
    if t.startswith("start process "):
        return ("process-start", {"cmd": t.replace("start process ", "", 1)})
    if t.startswith("kill process "):
        pid_str = t.replace("kill process ", "", 1).strip()
        return ("process-kill", {"pid": pid_str})
    if t.startswith("ist files") or t.startswith("lst files") or t.startswith("lsit files"):
        return ("fs-list", {"path": "."})
    if t.startswith("list files") or t.startswith("list ") or t.startswith("ls"):
        path = t.replace("list files", "", 1).strip()
        if not path and t.startswith("list "):
            path = t.replace("list ", "", 1).strip()
        if not path and t.startswith("ls "):
            path = t.replace("ls ", "", 1).strip()
        return ("fs-list", {"path": path or "."})
    if t.startswith("create folder "):
        return ("fs-mkdir", {"path": t.replace("create folder ", "", 1).strip()})
    if t.startswith("open project "):
        return ("open-project", {"path": t.replace("open project ", "", 1).strip()})
    if t.startswith("delete file "):
        path = t.replace("delete file ", "", 1).strip()
        return ("fs-rm", {"path": path})
    if t.startswith("remove file "):
        path = t.replace("remove file ", "", 1).strip()
        return ("fs-rm", {"path": path})
    if t.startswith("remove ") or t.startswith("delete "):
        path = t.replace("remove ", "", 1).replace("delete ", "", 1).strip()
        return ("fs-rm", {"path": path})
    if t.startswith("move "):
        rest = t.replace("move ", "", 1).strip()
        parts = rest.split(" to ")
        if len(parts) == 2:
            return ("fs-mv", {"src": parts[0].strip(), "dst": parts[1].strip()})
    if t.startswith("copy "):
        rest = t.replace("copy ", "", 1).strip()
        parts = rest.split(" to ")
        if len(parts) == 2:
            return ("fs-cp", {"src": parts[0].strip(), "dst": parts[1].strip()})
    if "network info" in t or t == "network":
        return ("network-info", {})
    if "memory" in t and "warning" in t:
        return ("memory-warning", {})
    if "devices" in t or "usb" in t:
        return ("devices", {})
    if "external storage" in t or "external disk" in t:
        return ("external-storage", {})
    if "connections" in t or "interfaces" in t:
        return ("connections", {})
    if t == "jobs":
        return ("jobs", {})
    if t.startswith("background "):
        return ("background", {"command": t.replace("background ", "", 1).strip()})
    if t.startswith("install "):
        app = t.replace("install ", "", 1).strip()
        return ("install-app", {"app": app})
    if t.startswith("uninstall "):
        app = t.replace("uninstall ", "", 1).strip()
        return ("uninstall-app", {"app": app})
    if t.startswith("delete app "):
        app = t.replace("delete app ", "", 1).strip()
        return ("uninstall-app", {"app": app})
    # Workflow: "open X and do Y" (e.g., "open youtube and play x", "open pages app and type hello")
    if t.startswith("open "):
        # Split on " and " / " then " (first occurrence only)
        for sep in [" and ", " then "]:
            if sep in t:
                left, right = t.split(sep, 1)
                target = left.replace("open ", "", 1).strip()
                action = right.strip()
                if target and action:
                    return ("workflow", {"target": target, "action": action})
    if t.startswith("open app "):
        app = t.replace("open app ", "", 1).strip()
        return ("open-app", {"app": app})
    if t.startswith("close app ") or t.startswith("quit app "):
        app = t.replace("close app ", "", 1).replace("quit app ", "", 1).strip()
        return ("close-app", {"app": app})
    if t.startswith("open ") and t.endswith(" app"):
        app = t.replace("open ", "", 1).replace(" app", "", 1).strip()
        return ("open-app", {"app": app})
    if t.startswith("remember shortcut ") or t.startswith("learn shortcut "):
        phrase = "remember shortcut " if t.startswith("remember shortcut ") else "learn shortcut "
        body = t.replace(phrase, "", 1).strip()
        if body.startswith("for "):
            body = body.replace("for ", "", 1).strip()
        if ":" in body:
            left, right = body.split(":", 1)
            left = left.strip()
            keys = right.strip()
            if " " in left:
                app, action = left.split(" ", 1)
            elif ":" in left:
                app, action = left.split(":", 1)
            else:
                app, action = left, "search"
            return ("remember-shortcut", {"app": app.strip(), "action": action.strip(), "keys": keys})
    if "youtube" in t and ("play" in t or "songs" in t or "song" in t):
        query = t.replace("open", "").replace("youtube", "").replace("play", "").strip()
        return ("youtube-play", {"query": query})
    if t.startswith("open "):
        site = t.replace("open ", "", 1).strip()
        # If this matches an installed app, open the app instead of a web search.
        try:
            if unified._find_app_paths(site):
                return ("open-app", {"app": site})
        except Exception:
            pass
        return ("open-website", {"site": site})
    if " open " in t and "app" not in t and "application" not in t:
        site = t.split(" open ", 1)[1].strip()
        return ("open-website", {"site": site})
    if t.startswith("search "):
        return ("search-web", {"query": t.replace("search ", "", 1).strip()})
    if t.startswith("find file "):
        return ("find-file", {"query": t.replace("find file ", "", 1).strip()})
    if "continue my work" in t or "resume project" in t:
        return ("resume-project", {})

    if t.startswith("http://") or t.startswith("https://"):
        return ("open-website", {"site": t})
    if "." in t and " " not in t:
        return ("open-website", {"site": t})

    return ("unknown", {})


def _handle_intent(intent, payload):
    if intent == "exit":
        print("Bye.")
        return "exit"
    if intent == "help":
        print("Try: system info | process list | open chatgpt | list files . | exit")
        print("Batch: use ';' or 'and' between commands. Example: open notes; open safari")
        print("Parallel: add 'simultaneously' at end.")
        print("Background: prefix with 'background '. Example: background open safari")
        print("File manager: file <command>. Example: file create-file notes.txt")
        print("Parental control: parental status | parental on | parental off")
        return "ok"
    if intent == "secure-write":
        path = payload.get("path", "").strip()
        content = payload.get("content", "")
        if not path:
            print("File path is required.")
            return "ok"
        secure_storage.write_secure(path, content)
        print(f"Encrypted and saved: {path}")
        return "ok"
    if intent == "secure-read":
        path = payload.get("path", "").strip()
        if not path:
            print("File path is required.")
            return "ok"
        text = secure_storage.read_secure(path)
        print(text)
        return "ok"
    if intent == "secure-encrypt":
        path = payload.get("path", "").strip()
        if not path:
            print("File path is required.")
            return "ok"
        out = secure_storage.encrypt_file(path)
        print(f"Encrypted file: {out}")
        return "ok"
    if intent == "secure-decrypt":
        path = payload.get("path", "").strip()
        if not path:
            print("File path is required.")
            return "ok"
        out = secure_storage.decrypt_file(path)
        print(f"Decrypted file: {out}")
        return "ok"
    if intent == "parental-status":
        parental_control.ensure_enabled()
        status = "on" if parental_control.is_enabled() else "off"
        print(f"Parental control: {status}")
        return "ok"
    if intent == "parental-on":
        parental_control.enable_now()
        print("Parental control enabled.")
        return "ok"
    if intent == "parental-off":
        ok = parental_control.disable_with_password()
        if ok:
            print("Parental control disabled.")
        else:
            print("Authentication failed. Parental control remains enabled.")
        return "ok"
    if intent == "debug-report":
        report = debug_agent.generate_report()
        _print_json(report)
        return "ok"
    if intent == "debug-watch":
        debug_agent.watch_logs()
        return "ok"
    if intent == "set-browser":
        name = payload.get("name", "").strip()
        if not name:
            print("Browser name is required.")
            return "ok"
        memory = unified._load_memory()
        memory["default_browser"] = name
        unified._save_memory(memory)
        print(f"Default browser set to: {name}")
        return "ok"
    if intent == "show-browser":
        memory = unified._load_memory()
        name = memory.get("default_browser")
        if not name:
            print("No default browser set.")
        else:
            print(f"Default browser: {name}")
        return "ok"
    if intent == "nlp-status":
        _print_json(intent_classifier.nlp_status())
        return "ok"
    if intent == "cpu-info":
        _print_json(arch_assistant.cpu_info())
        return "ok"
    if intent == "memory-info":
        _print_json(arch_assistant.memory_info())
        return "ok"
    if intent == "disk-info":
        _print_json(arch_assistant.disk_info("/"))
        return "ok"
    if intent == "cache-sim":
        _print_json(arch_assistant.simulate_cache())
        return "ok"
    if intent == "pipeline-sim":
        _print_json(arch_assistant.simulate_pipeline())
        return "ok"
    if intent == "run-instruction":
        instr = payload.get("instr", "").strip()
        _print_json(arch_assistant.run_instruction(instr))
        return "ok"
    if intent == "create-file":
        name = payload.get("name", "").strip()
        if not name:
            print("File name is required.")
            return "ok"
        os_actions.create_file(name)
        print(f"File created: {name}")
        return "ok"
    if intent == "create-file-content":
        name = payload.get("name", "").strip()
        content = payload.get("content", "").strip()
        if not name:
            print("File name is required.")
            return "ok"
        unified.write_file(name, content)
        print(f"File created with content: {name}")
        return "ok"
    if intent == "workflow":
        target = payload.get("target", "").strip()
        action_text = payload.get("action", "").strip()
        if parental_control.should_block_text(f"{target} {action_text}".strip()):
            print("This request is restricted.")
            return "ok"
        result = workflow_engine.run_workflow(target, action_text)
        print(result)
        return "ok"
    if intent == "edit-file":
        path = payload.get("path", "").strip()
        if not path:
            print("File path is required.")
            return "ok"
        choice = input("Do you want to add or delete content? (add/delete): ").strip().lower()
        if choice in {"add", "a"}:
            text = input("Text to add: ")
            try:
                with open(path, "a", encoding="utf-8") as f:
                    f.write(text + "\n")
                print(f"Added content to: {path}")
            except PermissionError:
                print("Permission denied.")
            except Exception as exc:
                print(f"Failed to edit file: {exc}")
            return "ok"
        if choice in {"delete", "del", "d"}:
            confirm = input("This will clear the file content. Proceed? (y/n): ").strip().lower()
            if confirm in {"y", "yes"}:
                try:
                    unified.write_file(path, "")
                    print(f"Cleared content in: {path}")
                except PermissionError:
                    print("Permission denied.")
                except Exception as exc:
                    print(f"Failed to clear file: {exc}")
            else:
                print("Canceled.")
            return "ok"
        print("Invalid choice. Use 'add' or 'delete'.")
        return "ok"
    if intent == "smart-file":
        args = payload.get("args", [])
        script = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "smart_file_manager.py"))
        if not os.path.exists(script):
            print("smart_file_manager.py not found.")
            return "ok"
        try:
            subprocess.run([sys.executable, script, *args], check=False)
        except Exception as exc:
            print(f"File manager failed: {exc}")
        return "ok"
    if intent == "show-env":
        _print_json(unified.env_vars())
        return "ok"
    if intent == "cwd":
        print(f"Current directory: {unified.current_dir()}")
        return "ok"
    if intent == "chdir":
        path = payload.get("path", "").strip()
        new_dir = unified.change_dir(path)
        print(f"Changed directory to: {new_dir}")
        return "ok"
    if intent == "mkdir":
        name = payload.get("name", "").strip()
        unified.make_dir(name)
        print(f"Directory created: {name}")
        return "ok"
    if intent == "rmdir":
        name = payload.get("name", "").strip()
        unified.remove_dir(name)
        print(f"Directory removed: {name}")
        return "ok"
    if intent == "pid":
        print(f"Current process ID: {unified.process_id()}")
        return "ok"
    if intent == "meaning":
        word = payload.get("word", "").strip()
        if not word:
            print("Please provide a word to define.")
            return "ok"
        query = f"meaning of {word}"
        memory = unified._load_memory()
        browser_name = memory.get("meaning_browser")
        if not browser_name:
            browser_name = input("Which browser should I use for meanings? ").strip() or None
            if browser_name:
                memory["meaning_browser"] = browser_name
                unified._save_memory(memory)
        result = unified.open_website(query, browser_name)
        memory_manager.save_event("search", query)
        _print_json(result)
        return "ok"
    if intent == "start-agent":
        base_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
        agent_dir = os.path.join(base_dir, "automation_agent")
        controller = os.path.join(agent_dir, "controller.swift")
        if not os.path.exists(controller):
            print("Automation agent not found. Expected: automation_agent/controller.swift")
            return "ok"

    if intent == "system-info":
        _print_json(unified.get_system_info())
    elif intent == "process-list":
        _print_json(unified.list_processes())
    elif intent == "process-start":
        cmd = payload.get("cmd", "").strip()
        if not cmd:
            print("Command is required.")
            return "ok"
        pid = unified.start_process(cmd)
        _print_json({"pid": pid})
    elif intent == "process-kill":
        pid_str = str(payload.get("pid", "")).strip()
        if not pid_str.isdigit():
            print("PID must be a number.")
            return "ok"
        unified.kill_process(int(pid_str))
        _print_json({"status": "terminated", "pid": int(pid_str)})
    elif intent == "fs-list":
        _print_json(unified.fs_list(payload.get("path", ".")))
    elif intent == "fs-mkdir":
        path = payload.get("path", "").strip()
        if not path:
            print("Path is required.")
            return "ok"
        unified.fs_mkdir(path)
        _print_json({"status": "created", "path": path})
    elif intent == "open-project":
        path = payload.get("path", "").strip()
        if not path:
            print("Project path is required.")
            return "ok"
        result = unified.open_folder(path)
        memory_manager.save_event("project", path)
        _print_json(result)
    elif intent == "fs-rm":
        path = payload.get("path", "").strip()
        if not path:
            print("Path is required.")
            return "ok"
        script = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "smart_file_manager.py"))
        if os.path.exists(script):
            subprocess.run([sys.executable, script, "delete", path], check=False)
        else:
            try:
                unified.fs_rm(path)
                _print_json({"status": "removed", "path": path})
            except Exception as exc:
                print(f"Error: {exc}")
    elif intent == "fs-mv":
        src = payload.get("src", "").strip()
        dst = payload.get("dst", "").strip()
        if not src or not dst:
            print("Source and destination are required.")
            return "ok"
        confirm = input(f"Move '{src}' to '{dst}'? (y/n): ").strip().lower()
        if confirm not in {"y", "yes"}:
            print("Canceled.")
            return "ok"
        unified.fs_move(src, dst)
        _print_json({"status": "moved", "src": src, "dst": dst})
    elif intent == "fs-cp":
        src = payload.get("src", "").strip()
        dst = payload.get("dst", "").strip()
        if not src or not dst:
            print("Source and destination are required.")
            return "ok"
        confirm = input(f"Copy '{src}' to '{dst}'? (y/n): ").strip().lower()
        if confirm not in {"y", "yes"}:
            print("Canceled.")
            return "ok"
        unified.fs_copy(src, dst)
        _print_json({"status": "copied", "src": src, "dst": dst})
    elif intent == "network-info":
        _print_json(unified.network_info())
    elif intent == "memory-warning":
        _print_json(unified.memory_warning())
    elif intent == "devices":
        _print_json(unified.list_usb_devices())
    elif intent == "external-storage":
        _print_json(unified.list_external_storage())
    elif intent == "connections":
        _print_json(unified.list_network_interfaces())
    elif intent == "open-website":
        site = payload.get("site", "").strip()
        if not site:
            print("Site is required.")
            return "ok"
        if parental_control.should_block_text(site) or parental_control.should_block_url(site):
            print("This request is restricted.")
            return "ok"
        result = workflow_engine.run_workflow(site, "")
        memory_manager.save_event("search", site)
        print(result)
    elif intent == "youtube-play":
        query = payload.get("query", "").strip()
        if not query:
            query = input("What should I play on YouTube? ").strip()
        if not query:
            print("Query is required.")
            return "ok"
        result = workflow_engine.run_workflow("youtube", f"play {query}")
        memory_manager.save_event("search", f"youtube {query}")
        print(result)
    elif intent == "search-web":
        query = payload.get("query", "").strip()
        if not query:
            print("Query is required.")
            return "ok"
        if parental_control.should_block_text(query):
            print("This request is restricted.")
            return "ok"
        result = workflow_engine.run_workflow(query, "")
        memory_manager.save_event("search", query)
        print(result)
    elif intent == "open-app":
        app = payload.get("app", "").strip()
        if not app:
            print("App name is required.")
            return "ok"
        result = unified.open_app(app)
        memory_manager.save_event("app", app)
        _print_json(result)
    elif intent == "remember-shortcut":
        app = payload.get("app", "").strip()
        action = payload.get("action", "").strip() or "search"
        keys = payload.get("keys", "").strip()
        if not app or not keys:
            print("App and keys are required.")
            return "ok"
        # Normalize keys: "cmd+f" or "cmd f" -> ["cmd", "f"]
        raw = keys.replace("+", " ")
        parts = [p.strip().lower() for p in raw.split() if p.strip()]
        if not parts:
            print("Keys are required.")
            return "ok"
        memory = unified._load_memory()
        app_key = app.lower().strip()
        memory.setdefault("app_shortcuts", {}).setdefault(app_key, {})[action] = parts
        unified._save_memory(memory)
        _print_json({"status": "saved", "app": app_key, "action": action, "keys": parts})
    elif intent == "close-app":
        app = payload.get("app", "").strip()
        if not app:
            print("App name is required.")
            return "ok"
        result = unified.close_app(app)
        _print_json(result)
    elif intent == "find-file":
        query = payload.get("query", "").strip()
        if not query:
            print("Query is required.")
            return "ok"
        result = unified.find_file(query)
        _print_json(result)
    elif intent == "work-mode":
        mode = payload.get("mode", "").strip()
        if not mode:
            print("Mode is required.")
            return "ok"
        result = automation_modes.run_mode(mode)
        _print_json(result)
    elif intent == "run-model":
        model = payload.get("model", "").strip()
        if not model:
            print("Model is required.")
            return "ok"
        result = medical_interface.run_model(model)
        _print_json(result)
    elif intent == "resume-project":
        project = memory_manager.get_last_project()
        if not project:
            print("No last project found.")
            return "ok"
        result = unified.open_folder(project)
        _print_json(result)
    elif intent == "set-user":
        name = payload.get("name", "").strip()
        if not name:
            print("Name is required.")
            return "ok"
        memory_manager.save_event("user", name)
        _print_json({"status": "saved", "username": name})
    elif intent == "install-app":
        app = payload.get("app", "").strip()
        if not app:
            app = input("App name: ").strip()
        if not app:
            print("App name is required.")
            return "ok"

        print("Choose install source:")
        print("1. Homebrew (best for most apps)")
        print("2. DMG file (you already downloaded)")
        print("3. PKG file (you already downloaded)")
        print("4. App Store (best for Apple apps)")
        source = input("Source (1/2/3/4): ").strip()
        brew_cask = False

        if source == "1":
            is_gui = input("Is this a GUI app? (y/n): ").strip().lower()
            brew_cask = is_gui in {"y", "yes"}
            info = unified._brew_info(app)
            print("\nReview:")
            print(f"Method: Homebrew {'cask' if brew_cask else 'formula'}")
            print(f"App: {app}")
            if info["dependencies"]:
                print("Dependencies:")
                for dep in info["dependencies"]:
                    print(f"- {dep}")
            else:
                print("Dependencies: unknown (brew info not available)")
            confirm = input("\nProceed with install? (y/n): ").strip().lower()
            if confirm not in {"y", "yes"}:
                print("Canceled.")
                return "ok"
            result = unified.install_app("homebrew", app_name=app, brew_cask=brew_cask)
            _print_json(result)
            if result.get("status") == "error" and result.get("suggestions"):
                print("\nDid you mean one of these casks?")
                for s in result["suggestions"]:
                    print(f"- {s}")
                retry = input("Install one of these now? (enter name or press Enter to cancel): ").strip()
                if retry:
                    retry_result = unified.install_app("homebrew", app_name=retry, brew_cask=True)
                    _print_json(retry_result)
                else:
                    print("You can retry with: install <cask-name>")
            elif result.get("status") == "error":
                print("Tip: try `brew search --cask <name>` to find the exact cask.")
        elif source == "2":
            path = input("DMG file path: ").strip()
            print("\nReview:")
            print("Method: DMG installer")
            print(f"Path: {path}")
            print("Note: This will open the installer UI.")
            confirm = input("\nProceed to open installer? (y/n): ").strip().lower()
            if confirm not in {"y", "yes"}:
                print("Canceled.")
                return "ok"
            result = unified.install_app("dmg", installer_path=path)
            _print_json(result)
        elif source == "3":
            path = input("PKG file path: ").strip()
            print("\nReview:")
            print("Method: PKG installer")
            print(f"Path: {path}")
            print("Note: This will open the installer UI.")
            confirm = input("\nProceed to open installer? (y/n): ").strip().lower()
            if confirm not in {"y", "yes"}:
                print("Canceled.")
                return "ok"
            result = unified.install_app("pkg", installer_path=path)
            _print_json(result)
        elif source == "4":
            print("\nReview:")
            print("Method: App Store")
            print(f"App: {app}")
            print("Note: This will open the App Store search.")
            confirm = input("\nProceed to open App Store? (y/n): ").strip().lower()
            if confirm not in {"y", "yes"}:
                print("Canceled.")
                return "ok"
            result = unified.install_app("appstore", app_name=app)
            _print_json(result)
        else:
            print("Invalid source.")
    elif intent == "uninstall-app":
        app = payload.get("app", "").strip()
        if not app:
            app = input("App name to remove: ").strip()
        if not app:
            print("App name is required.")
            return "ok"
        preview = unified._find_app_paths(app)
        print("\nReview (safe uninstall):")
        if preview:
            print("App bundle(s) to move to Trash:")
            for path in preview:
                print(f"- {path}")
        else:
            print("App not found in /Applications or ~/Applications.")
        print("Note: This does not delete your user data or caches.")
        confirm = input("\nProceed with uninstall? (y/n): ").strip().lower()
        if confirm not in {"y", "yes"}:
            print("Canceled.")
            return "ok"
        result = unified.uninstall_app_safe(app)
        _print_json(result)
    elif intent == "jobs":
        return "jobs"
    else:
        print("I didn't understand that. Try 'help'.")

    return "ok"


def _map_intent(classified):
    intent = classified["intent"]
    params = classified["parameters"]
    if intent == "OPEN_APP":
        return {"intent": "open-app", "parameters": {"app": params.get("app", "")}}
    if intent == "CLOSE_APP":
        return {"intent": "close-app", "parameters": {"app": params.get("app", "")}}
    if intent == "SEARCH_WEB":
        return {"intent": "search-web", "parameters": {"query": params.get("query", "")}}
    if intent == "FIND_FILE":
        return {"intent": "find-file", "parameters": {"query": params.get("query", "")}}
    if intent == "WORK_MODE":
        return {"intent": "work-mode", "parameters": {"mode": params.get("mode", "")}}
    if intent == "RUN_MODEL":
        return {"intent": "run-model", "parameters": {"model": params.get("model", "")}}
    return {"intent": "help", "parameters": {}}


def _interactive():
    print("AVA-OS Interactive")
    print("Type a command like: open chatgpt, system info, list files, exit.")
    jobs = {}
    job_counter = 0
    jobs_lock = threading.Lock()

    def _run_job(job_id, intent, payload):
        try:
            _execute_intent(intent, payload)
            status = "done"
        except Exception as exc:
            status = f"error: {exc}"
            debug_agent.log_error("background", exc, intent=intent, payload=payload)
        with jobs_lock:
            jobs[job_id]["status"] = status
            jobs[job_id]["ended_at"] = time.time()

    while True:
        user_input = input("\nAIOS > ").strip()
        if not user_input:
            continue
        block_reason = parental_control.should_block_text(user_input)
        if block_reason:
            print("This request is restricted.")
            continue
        # Continuous mode: "continuous 5: command1; command2"
        if user_input.lower().startswith("continuous "):
            try:
                header, body = user_input.split(":", 1)
                interval = float(header.replace("continuous", "").strip())
                cmds, par = _split_commands(body.strip())
                if not cmds:
                    print("No commands to run in continuous mode.")
                    continue
                with jobs_lock:
                    job_counter += 1
                    job_id = job_counter
                    jobs[job_id] = {
                        "status": "running",
                        "command": f"continuous {interval}s: {body.strip()}",
                        "started_at": time.time(),
                        "ended_at": None,
                    }
                def _loop():
                    while True:
                        for cmd in cmds:
                            if parental_control.should_block_text(cmd):
                                print("This request is restricted.")
                                continue
                            intent, payload = _parse_intent(cmd)
                            if intent == "unknown":
                                classified = intent_classifier.classify(cmd)
                                if classified["intent"] and classified["confidence"] >= 0.55:
                                    mapped = _map_intent(classified)
                                    intent = mapped["intent"]
                                    payload = mapped["parameters"]
                            _execute_intent(intent, payload, command=cmd)
                        time.sleep(interval)
                thread = threading.Thread(target=_loop, daemon=True)
                thread.start()
                print(f"Started continuous job #{job_id} every {interval}s")
                continue
            except Exception:
                print("Usage: continuous <seconds>: command1; command2")
                continue
        commands, parallel = _split_commands(user_input)

        if len(commands) == 1:
            intent, payload = _parse_intent(commands[0])
            if intent == "background":
                inner = payload.get("command", "")
                if not inner:
                    print("Background command is required.")
                    continue
                inner_intent, inner_payload = _parse_intent(inner)
                if inner_intent == "unknown":
                    llm_result = llm.llm_parse(inner)
                    inner_intent = llm_result.get("action", "help")
                    inner_payload = llm_result.get("params", {})
                with jobs_lock:
                    job_counter += 1
                    job_id = job_counter
                    jobs[job_id] = {
                        "status": "running",
                        "command": inner,
                        "started_at": time.time(),
                        "ended_at": None,
                    }
                thread = threading.Thread(
                    target=_run_job, args=(job_id, inner_intent, inner_payload), daemon=True
                )
                thread.start()
                print(f"Started background job #{job_id}: {inner}")
                continue
        try:
            intents = []
            for cmd in commands:
                if parental_control.should_block_text(cmd):
                    print("This request is restricted.")
                    continue
                intent, payload = _parse_intent(cmd)
                acc = 1.0
                if intent == "unknown":
                    classified = intent_classifier.classify(cmd)
                    if classified["intent"] and classified["confidence"] >= 0.55:
                        mapped = _map_intent(classified)
                        intent = mapped["intent"]
                        payload = mapped["parameters"]
                        acc = float(classified.get("confidence", 0.6))
                    else:
                        llm_result = llm.llm_parse(cmd)
                        intent = llm_result.get("action", "help")
                        payload = llm_result.get("params", {})
                        if payload.get("error") == "llm_unavailable":
                            print("LLM not available. Install Ollama to enable NLP.")
                            intent = "help"
                        acc = 0.6
                intents.append((intent, payload, acc))

            if parallel and len(intents) > 1:
                confirm_actions = {"fs-mv", "fs-cp", "fs-rm", "install-app", "uninstall-app"}
                if any(i in confirm_actions for i, _, _ in intents):
                    parallel = False

            if parallel and len(intents) > 1:
                threads = []
                for intent, payload, acc in intents:
                    t = threading.Thread(target=_execute_intent, args=(intent, payload))
                    t.start()
                    threads.append(t)
                for t in threads:
                    t.join()
                continue

            for intent, payload, acc in intents:
                start = time.perf_counter()
                result = _execute_intent(intent, payload, command=user_input)
                duration = time.perf_counter() - start
                print(f"Accuracy: {acc:.2f} | Time: {duration:.3f}s")
                if result == "exit":
                    return
                if result == "jobs":
                    with jobs_lock:
                        if not jobs:
                            print("No background jobs.")
                        else:
                            for job_id, info in jobs.items():
                                print(f"#{job_id} {info['status']} - {info['command']}")
        except Exception as exc:
            print(f"Error: {exc}")


def handle_text_command(text):
    commands, parallel = _split_commands(text)
    intents = []
    for cmd in commands:
        if parental_control.should_block_text(cmd):
            return "This request is restricted."
        intent, payload = _parse_intent(cmd)
        if intent == "unknown":
            classified = intent_classifier.classify(cmd)
            if classified["intent"] and classified["confidence"] >= 0.55:
                mapped = _map_intent(classified)
                intent = mapped["intent"]
                payload = mapped["parameters"]
            else:
                llm_result = llm.llm_parse(cmd)
                intent = llm_result.get("action", "help")
                payload = llm_result.get("params", {})
                if payload.get("error") == "llm_unavailable":
                    return "LLM not available. Install Ollama to enable NLP."
        intents.append((intent, payload))

    results = []
    for intent, payload in intents:
        result = _execute_intent(intent, payload)
        if result == "exit":
            results.append("Bye.")
            continue
        results.append(result)
    return results[0] if len(results) == 1 else results


def main():
    parser = argparse.ArgumentParser(
        prog="aios",
        description="Unified OS-agnostic CLI (macOS first, then Linux, then Windows).",
    )
    sub = parser.add_subparsers(dest="command", required=False)

    sub.add_parser("system-info", help="Show unified system info JSON")
    sub.add_parser("process-list", help="List running processes")

    proc_start = sub.add_parser("process-start", help="Start a process")
    proc_start.add_argument("cmd", nargs=argparse.REMAINDER, help="Command to run")

    proc_kill = sub.add_parser("process-kill", help="Terminate a process")
    proc_kill.add_argument("pid", type=int, help="Process ID")

    fs_list = sub.add_parser("fs-list", help="List a directory")
    fs_list.add_argument("path", nargs="?", default=".")

    fs_mkdir = sub.add_parser("fs-mkdir", help="Create a directory")
    fs_mkdir.add_argument("path")

    fs_rm = sub.add_parser("fs-rm", help="Remove a file or directory")
    fs_rm.add_argument("path")

    fs_move = sub.add_parser("fs-mv", help="Move a file or directory")
    fs_move.add_argument("src")
    fs_move.add_argument("dst")

    fs_copy = sub.add_parser("fs-cp", help="Copy a file or directory")
    fs_copy.add_argument("src")
    fs_copy.add_argument("dst")

    sub.add_parser("network-info", help="Show basic network info")
    open_site = sub.add_parser("open-website", help="Open a website with memory")
    open_site.add_argument("site", help="Site or query to open")
    open_site.add_argument("--browser", help="Preferred browser name")

    args = parser.parse_args()

    if args.command is None:
        _interactive()
        return

    try:
        if args.command == "system-info":
            _print_json(unified.get_system_info())
        elif args.command == "process-list":
            _print_json(unified.list_processes())
        elif args.command == "process-start":
            if not args.cmd:
                raise ValueError("process-start requires a command")
            pid = unified.start_process(args.cmd)
            _print_json({"pid": pid})
        elif args.command == "process-kill":
            unified.kill_process(args.pid)
            _print_json({"status": "terminated", "pid": args.pid})
        elif args.command == "fs-list":
            _print_json(unified.fs_list(args.path))
        elif args.command == "fs-mkdir":
            unified.fs_mkdir(args.path)
            _print_json({"status": "created", "path": args.path})
        elif args.command == "fs-rm":
            unified.fs_rm(args.path)
            _print_json({"status": "removed", "path": args.path})
        elif args.command == "fs-mv":
            unified.fs_move(args.src, args.dst)
            _print_json({"status": "moved", "src": args.src, "dst": args.dst})
        elif args.command == "fs-cp":
            unified.fs_copy(args.src, args.dst)
            _print_json({"status": "copied", "src": args.src, "dst": args.dst})
        elif args.command == "network-info":
            _print_json(unified.network_info())
        elif args.command == "open-website":
            result = unified.open_website(args.site, args.browser)
            _print_json(result)
        else:
            raise ValueError("Unknown command")
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
