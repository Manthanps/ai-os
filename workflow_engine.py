import re
import time
import platform
import aios_unified as unified
import memory_manager
import feedback_engine
import browser_automation
import os
import web_filter
import time



SITE_URLS = {
    "chatgpt": "https://chatgpt.com",
    "youtube": "https://www.youtube.com",
    "kaggle": "https://www.kaggle.com/datasets",
}


def _normalize_target(target):
    t = target.lower().strip()
    t = re.sub(r"\\s+", " ", t)
    t = t.replace("chat gpt", "chatgpt")
    return t


def _explicit_app_target(target):
    t = target.lower().strip()
    return " app" in f" {t} " or " application" in f" {t} "


def _strip_app_suffix(target):
    t = target
    for token in [" app", " application"]:
        if t.lower().endswith(token):
            t = t[: -len(token)].strip()
            break
    t = t.strip()
    if t.lower().startswith("the "):
        t = t[4:].strip()
    return t


def _resolve_url(target):
    key = _normalize_target(target)
    if key in SITE_URLS:
        return SITE_URLS[key]
    if key.startswith("http://") or key.startswith("https://"):
        return key
    if "." in key:
        return f"https://{key}"
    return f"https://www.google.com/search?q={target}"


def _block_reason(url: str):
    config_path = os.path.join(os.path.dirname(__file__), "filter_config.yaml")
    if not os.path.exists(config_path):
        return None
    try:
        reason = web_filter.check_url(url, config_path)
        return reason
    except Exception:
        return None


def _installed_app_name(target):
    # Best-effort: if a macOS app bundle exists for this name, treat it as an app.
    try:
        paths = unified._find_app_paths(target)
    except Exception:
        return None
    if paths:
        # Use the friendly app name (without .app)
        return target
    return None


def _extract_browser_hint(target):
    match = re.search(r"\\b(?:in|on)\\s+([\\w ._-]+)$", target, flags=re.IGNORECASE)
    if not match:
        return None
    browser = match.group(1).strip()
    return browser or None


def _strip_browser_hint(target):
    cleaned = re.sub(r"\\b(?:in|on)\\s+[\\w ._-]+$", "", target, flags=re.IGNORECASE).strip()
    return cleaned


def _clean_action_text(action_text):
    t = (action_text or "").strip()
    if not t:
        return t
    t = re.sub(r"^(type|say|write)\\b\\s*[:,]?", "", t, flags=re.IGNORECASE).strip()
    return t


def _prompt_choice(prompt, options):
    print(prompt)
    for i, opt in enumerate(options, start=1):
        print(f"{i}. {opt}")
    choice = input("Choose: ").strip()
    try:
        idx = int(choice)
        if 1 <= idx <= len(options):
            return options[idx - 1]
    except ValueError:
        pass
    # Fallback: match by text
    for opt in options:
        if choice.lower() in opt.lower():
            return opt
    return options[0]


def _parse_file_action(action_text):
    # Examples: "send file /path/to/file", "share file report.txt"
    t = (action_text or "").strip()
    m = re.search(r"(?:send|share)\\s+file\\s+(.+)$", t, flags=re.IGNORECASE)
    if not m:
        return None
    return m.group(1).strip()


def run_workflow(target, action_text):
    target = target.strip()
    if not target:
        return feedback_engine.error("Target is required.")

    browser_hint = _extract_browser_hint(target)
    if browser_hint:
        target = _strip_browser_hint(target)

    choice = "website"
    if browser_hint:
        choice = "website"
    elif _explicit_app_target(target):
        choice = "app"
        target = _strip_app_suffix(target)
    elif _normalize_target(target) in SITE_URLS:
        choice = "website"
    else:
        # Default to website to match spoken commands like "WhatsApp" or "ChatGPT".
        choice = "website"

    # If the target matches an installed macOS app name, prefer opening the app.
    if choice == "website" and platform.system().lower() == "darwin":
        app_name = _installed_app_name(target)
        if app_name:
            choice = "app"
            target = app_name

    action_text = _clean_action_text(action_text)

    if choice == "app":
        unified.open_app(target)
        message = f"Opened app '{target}'."
        if action_text:
            # Give the app a moment to focus, then attempt typing.
            # Some desktop apps need extra time to be ready.
            time.sleep(2.5)
            try:
                # Preflight: verify OS automation permissions so typing/search can work.
                access = unified.check_accessibility()
                if access.get("status") != "ok":
                    return feedback_engine.error(
                        "I can open apps, but typing/clicking is blocked. "
                        "Enable macOS Accessibility/Automation for your terminal/Python, then try again."
                    )
                # Ensure app is frontmost before sending keystrokes.
                try:
                    if not unified.ensure_app_frontmost(target):
                        return feedback_engine.error(
                            f"Couldn't focus '{target}'. Please bring it to front and try again."
                        )
                    time.sleep(0.4)
                except Exception:
                    pass
                unified.type_text(action_text)
                message = f"Opened app '{target}'. Typed the prompt."
            except Exception:
                copied = unified.copy_to_clipboard(action_text)
                if copied:
                    message = f"Opened app '{target}'. Prompt copied — paste it where needed."
                else:
                    message = f"Opened app '{target}'. Please type: {action_text}"

        # Always ask whether to close the app after finishing.
        # Print status before asking, so user sees progress even while waiting for input.
        if message:
            print(message)
        confirm = input(f"Can I close {target}? (y/n): ").strip().lower()
        if confirm in {"y", "yes"}:
            try:
                unified.close_app(target)
                return feedback_engine.info(f"{message} Closed '{target}'.")
            except Exception:
                return feedback_engine.info(f"{message} Please close '{target}' manually.")
        return feedback_engine.info(message)

    # Website flow
    memory = unified._load_memory()
    browser_name = browser_hint or memory.get("default_browser")
    if not browser_name and not browser_hint:
        browser_name = input("Which browser should I use for websites? ").strip() or None
        if browser_name:
            memory["default_browser"] = browser_name
            unified._save_memory(memory)

    url = _resolve_url(target)
    reason = _block_reason(url)
    if reason:
        return feedback_engine.error("Blocked: adult rated content.")

    # Try automation for known sites when action is provided.
    key = _normalize_target(target)
    if action_text:
        if key == "chatgpt":
            auto = browser_automation.open_chatgpt_and_prompt(action_text, ask_close=True)
            if auto.get("status") == "ok":
                return auto.get("message", "Done.")
            # Fallback: open site and copy prompt
            unified.open_website(url, browser_name)
            copied = unified.copy_to_clipboard(action_text)
            if copied:
                return feedback_engine.info(
                    f"Opened {url}. Prompt copied — paste it into the site."
                )
            return feedback_engine.info(
                f"Opened {url}. Please type: {action_text}"
            )
        if key == "youtube":
            query = action_text.replace("play", "").strip()
            auto = browser_automation.open_youtube_and_play(query, ask_close=True)
            if auto.get("status") == "ok":
                return auto.get("message", "Done.")
        if key == "gmail":
            # Open Gmail web and guide user through attachment workflow.
            unified.open_website("https://mail.google.com", browser_name or "Safari")
            file_path = _parse_file_action(action_text)
            if file_path:
                input("Click Compose, then click Attach, then press Enter.")
                try:
                    unified.type_text(file_path)
                    unified.press_key("enter")
                except Exception:
                    pass
                input("Fill To/Subject/Body. Press Enter when ready to send.")
                try:
                    unified.send_hotkey(["cmd"], "enter")
                except Exception:
                    pass
                return feedback_engine.info("Opened Gmail and attached the file.")
        # Generic website typing attempt
        auto = browser_automation.open_site_and_type(url, action_text, ask_close=True)
        if auto.get("status") == "ok":
            return auto.get("message", "Typed text on the site.")

    unified.open_website(url, browser_name)

    if action_text:
        copied = unified.copy_to_clipboard(action_text)
        if copied:
            return feedback_engine.info(
                f"Opened {url}. Prompt copied — paste it into the site."
            )
        return feedback_engine.info(
            f"Opened {url}. Please type: {action_text}"
        )
    return feedback_engine.info(f"Opened {url}.")
