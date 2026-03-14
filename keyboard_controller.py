import logging
import time
import pyautogui


def write_text(text: str, interval: float = 0.05) -> None:
    logging.info("Typing text")
    pyautogui.write(text, interval=interval)


def press_key(key: str) -> None:
    pyautogui.press(key)


def hotkey(*keys: str) -> None:
    pyautogui.hotkey(*keys)


def open_search() -> None:
    hotkey("command", "f")
    time.sleep(0.5)


def open_address_bar() -> None:
    hotkey("command", "l")
    time.sleep(0.5)


def press_enter() -> None:
    press_key("enter")


def press_down(n: int = 1, delay: float = 0.2) -> None:
    for _ in range(max(1, n)):
        press_key("down")
        time.sleep(delay)
