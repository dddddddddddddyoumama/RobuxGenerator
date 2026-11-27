"""
Windows only.
Install:  pip install pyautogui requests pillow
Usage:    python cmd_to_discord.py
"""

import ctypes
import os
import subprocess
import sys
import time
import uuid
from ctypes import wintypes
from io import BytesIO

import pyautogui
import requests

# ------------------------- CONFIGURATION -------------------------
WEBHOOK_URL = os.environ.get("DISCORD_WEBHOOK_URL", "https://discord.com/api/webhooks/1574853837599023165/hS7eRezU6iNKkOlSEWanjaB5Qhg3H6ga8Qe-1-qkxSeQn0M1hFWUFG-MISQGgVFMMFyX")
COMMAND = "ipconfig"        # <-- change this to the command you want to run
TYPE_INTERVAL = 0.02
WINDOW_WAIT_TIMEOUT = 10
CAPTURE_DELAY = 1.0
HTTP_TIMEOUT = 20
# -----------------------------------------------------------------

user32 = ctypes.windll.user32
dwmapi = ctypes.windll.dwmapi

WM_CLOSE = 0x0010
SW_RESTORE = 9
DWMWA_EXTENDED_FRAME_BOUNDS = 9
CREATE_NEW_CONSOLE = 0x00000010

try:
    ctypes.windll.shcore.SetProcessDpiAwareness(2)
except Exception:
    try:
        user32.SetProcessDPIAware()
    except Exception:
        pass


class AutomationError(Exception):
    pass


def open_cmd(title):
    attempts = [
        ["conhost.exe", "cmd.exe", "/k", f"title {title}"],
        ["cmd.exe", "/k", f"title {title}"],
    ]
    last_error = None
    for args in attempts:
        try:
            return subprocess.Popen(args, creationflags=CREATE_NEW_CONSOLE)
        except (OSError, subprocess.SubprocessError) as e:
            last_error = e
    raise AutomationError(f"Could not open CMD: {last_error}")


def find_window(title, timeout):
    deadline = time.time() + timeout
    while time.time() < deadline:
        hwnd = user32.FindWindowW(None, title)
        if hwnd and user32.IsWindowVisible(hwnd):
            return hwnd
        time.sleep(0.1)
    raise AutomationError("CMD window did not appear.")


def focus_window(hwnd):
    user32.ShowWindow(hwnd, SW_RESTORE)
    user32.keybd_event(0x12, 0, 0, 0)  # ALT trick to allow focus change
    user32.keybd_event(0x12, 0, 2, 0)
    user32.SetForegroundWindow(hwnd)
    for _ in range(20):
        if user32.GetForegroundWindow() == hwnd:
            time.sleep(0.3)
            return
        time.sleep(0.1)
    raise AutomationError("Could not focus the CMD window.")


def get_window_rect(hwnd):
    rect = wintypes.RECT()
    hr = dwmapi.DwmGetWindowAttribute(
        wintypes.HWND(hwnd),
        wintypes.DWORD(DWMWA_EXTENDED_FRAME_BOUNDS),
        ctypes.byref(rect),
        ctypes.sizeof(rect),
    )
    if hr != 0:
        if not user32.GetWindowRect(hwnd, ctypes.byref(rect)):
            raise AutomationError("Could not read CMD window position.")
    w, h = rect.right - rect.left, rect.bottom - rect.top
    if w <= 0 or h <= 0:
        raise AutomationError("CMD window has an invalid size.")
    return rect.left, rect.top, w, h


def close_cmd(hwnd, proc):
    try:
        if hwnd and user32.IsWindow(hwnd):
            user32.PostMessageW(hwnd, WM_CLOSE, 0, 0)
            for _ in range(20):
                if not user32.IsWindow(hwnd):
                    break
                time.sleep(0.1)
        if proc and proc.poll() is None:
            subprocess.run(
                ["taskkill", "/PID", str(proc.pid), "/T", "/F"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
    except Exception as e:
        print(f"[warn] Could not fully close CMD: {e}")


def send_to_discord(image_buffer, command):
    if not WEBHOOK_URL or "PASTE_YOUR_WEBHOOK_URL_HERE" in WEBHOOK_URL:
        raise AutomationError("Webhook URL not configured.")

    image_buffer.seek(0)
    files = {"file": ("cmd_screenshot.png", image_buffer, "image/png")}
    data = {"content": f"Output of `{command[:1500]}`"}

    try:
        resp = requests.post(WEBHOOK_URL, data=data, files=files, timeout=HTTP_TIMEOUT)
    except requests.exceptions.ConnectionError:
        raise AutomationError("Discord is unreachable (check your internet).")
    except requests.exceptions.Timeout:
        raise AutomationError("Discord request timed out.")
    except requests.exceptions.RequestException as e:
        raise AutomationError(f"Discord request failed: {e}")

    if resp.status_code == 429:
        raise AutomationError("Discord rate limit hit. Try again later.")
    if resp.status_code in (401, 404):
        raise AutomationError("Webhook is invalid or was deleted.")
    if not resp.ok:
        raise AutomationError(f"Discord returned HTTP {resp.status_code}: {resp.text[:200]}")


def run(command):
    title = f"AutoCMD-{uuid.uuid4().hex[:8]}"
    proc = None
    hwnd = None
    image_buffer = BytesIO()

    try:
        proc = open_cmd(title)                      # 1. open visible CMD
        hwnd = find_window(title, WINDOW_WAIT_TIMEOUT)
        focus_window(hwnd)

        pyautogui.write(command, interval=TYPE_INTERVAL)   # 2. type
        pyautogui.press("enter")                           # 3. execute

        time.sleep(CAPTURE_DELAY)                          # 4. wait 1 second

        if not user32.IsWindow(hwnd):
            raise AutomationError("CMD closed before screenshot.")
        left, top, width, height = get_window_rect(hwnd)
        shot = pyautogui.screenshot(region=(left, top, width, height))  # 5. only CMD
        shot.save(image_buffer, format="PNG")              # saved in memory only

    except pyautogui.FailSafeException:
        raise AutomationError("PyAutoGUI fail-safe triggered.")
    finally:
        close_cmd(hwnd, proc)                              # 6. always close CMD

    send_to_discord(image_buffer, command)                 # 7. send from memory
    print("Screenshot sent to Discord.")


def main():
    if sys.platform != "win32":
        print("This script only runs on Windows.")
        return 1

    if not COMMAND.strip():
        print("COMMAND is empty. Set it in the configuration section.")
        return 1

    try:
        run(COMMAND)
        return 0
    except AutomationError as e:                           # 8. error handling
        print(f"[error] {e}")
    except Exception as e:
        print(f"[unexpected error] {type(e).__name__}: {e}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
