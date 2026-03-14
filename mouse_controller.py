import pyautogui


def move_to(x: int, y: int, duration: float = 0.1) -> None:
    pyautogui.moveTo(x, y, duration=duration)


def click(x: int, y: int) -> None:
    move_to(x, y)
    pyautogui.click()
