import time

from .app_controller import open_application, focus_application
from .keyboard_controller import (
    open_search,
    open_address_bar,
    write_text,
    press_enter,
)


def safari_google_search(command: str):
    """Open Safari and run a Google search."""
    query = command.replace("search google", "", 1).strip()
    if not query:
        logging.error("Search query required.")
        return
    open_application("Safari", wait=4)
    focus_application("Safari")

    logging.info("Opening Google")
    open_address_bar()
    write_text("https://www.google.com")
    press_enter()
    time.sleep(2.5)

    logging.info("Typing search query")
    write_text(query, interval=0.05)
    press_enter()


def open_and_search_youtube(command: str):
    """Open Safari and search YouTube for a term."""
    query = command.replace("open safari and search youtube", "", 1).strip()
    if not query:
        logging.error("Search query required.")
        return
    open_application("Safari", wait=4)
    focus_application("Safari")

    open_address_bar()
    write_text("https://www.youtube.com")
    press_enter()
    time.sleep(3)

    open_search()
    write_text(query, interval=0.05)
    press_enter()
