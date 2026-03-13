import os
import re
import aios_unified as unified

try:
    from playwright.sync_api import sync_playwright
except Exception:
    sync_playwright = None


def _playwright_available():
    return sync_playwright is not None


def _run_in_browser(action_fn, ask_close=False):
    if not _playwright_available():
        return {
            "status": "error",
            "message": "Playwright not available. Run: /Users/manthan/ai_os/.venv/bin/python -m playwright install",
        }
    try:
        with sync_playwright() as p:
            user_data_dir = os.path.join(os.path.dirname(__file__), "playwright_profile")
            context = p.chromium.launch_persistent_context(
                user_data_dir=user_data_dir,
                headless=False,
            )
            page = context.new_page()
            result = action_fn(page) or {}
            if ask_close:
                try:
                    confirm = input("Can I close this website? (y/n): ").strip().lower()
                except Exception:
                    confirm = "y"
                if confirm in {"y", "yes"}:
                    context.close()
                    return {"status": "ok", **result, "closed": True}
                return {"status": "ok", **result, "closed": False}
            # Keep the browser open when not explicitly told to close.
            return {"status": "ok", **result, "closed": False}
    except Exception as exc:
        return {"status": "error", "message": str(exc)}


def _memory():
    try:
        return unified._load_memory()
    except Exception:
        return {}


def _save_memory(mem):
    try:
        unified._save_memory(mem)
    except Exception:
        pass


def _site_key(url):
    try:
        from urllib.parse import urlparse
        host = urlparse(url).netloc.lower()
        if host.startswith("www."):
            host = host[4:]
        return host or url
    except Exception:
        return url


def open_chatgpt_and_prompt(prompt_text, ask_close=False):
    prompt_text = (prompt_text or "").strip()
    if not prompt_text:
        return {"status": "error", "message": "Prompt text required."}

    def _action(page):
        page.goto("https://chatgpt.com", wait_until="domcontentloaded")
        page.wait_for_timeout(2500)
        # Try common input selectors
        textarea = page.locator("textarea")
        if textarea.count() == 0:
            return {"status": "error", "message": "ChatGPT input not found. Please type manually."}
        textarea.first.fill(prompt_text)
        textarea.first.press("Enter")
        return {"message": "Prompt sent to ChatGPT."}

    return _run_in_browser(_action, ask_close=ask_close)


def open_youtube_and_play(query, ask_close=False):
    query = (query or "").strip()
    if not query:
        return {"status": "error", "message": "Query required."}

    def _action(page):
        page.goto("https://www.youtube.com", wait_until="domcontentloaded")
        page.wait_for_timeout(1500)
        mem = _memory()
        shortcuts = mem.get("site_shortcuts", {}).get("youtube.com", {})
        selector_order = []
        saved_sel = shortcuts.get("search_selector")
        if saved_sel:
            selector_order.append(saved_sel)
        selector_order += [
            "input#search",
            "input[name='search_query']",
            "input[aria-label='Search']",
        ]
        search = None
        for sel in selector_order:
            loc = page.locator(sel)
            if loc.count() > 0:
                search = loc.first
                # Persist the working selector
                mem.setdefault("site_shortcuts", {}).setdefault("youtube.com", {})["search_selector"] = sel
                _save_memory(mem)
                break
        if search is None:
            return {"status": "error", "message": "YouTube search not found. Please search manually."}
        search.fill(query)
        search.press("Enter")
        page.wait_for_timeout(2000)
        first = page.locator("ytd-video-renderer a#thumbnail").first
        if first.count() == 0:
            return {"status": "error", "message": "No results found. Please pick a video manually."}
        first.click()
        return {"message": f"Playing: {query}"}

    return _run_in_browser(_action, ask_close=ask_close)


def open_site_and_type(url, text, ask_close=False):
    text = (text or "").strip()
    if not url or not text:
        return {"status": "error", "message": "URL and text required."}

    def _action(page):
        page.goto(url, wait_until="domcontentloaded")
        page.wait_for_timeout(2000)
        # Try common editable targets, prefer saved selector if known.
        mem = _memory()
        key = _site_key(url)
        saved_sel = mem.get("site_shortcuts", {}).get(key, {}).get("input_selector")
        selectors = []
        if saved_sel:
            selectors.append(saved_sel)
        selectors += [
            "textarea",
            "input[type='text']",
            "input[type='search']",
            "div[contenteditable='true']",
        ]
        target = None
        for sel in selectors:
            loc = page.locator(sel)
            if loc.count() > 0:
                target = loc.first
                # Persist the working selector
                mem.setdefault("site_shortcuts", {}).setdefault(key, {})["input_selector"] = sel
                _save_memory(mem)
                break
        if target is None:
            return {"status": "error", "message": "No input found. Please paste manually."}
        target.click()
        target.fill(text)
        return {"message": "Typed text into the page."}

    return _run_in_browser(_action, ask_close=ask_close)
