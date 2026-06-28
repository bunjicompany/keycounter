import ctypes
import json
import os
import shutil
import socket
import subprocess
import sys
import threading
import time
import webbrowser
import winreg
from pathlib import Path
from datetime import datetime, timedelta

from PIL import Image, ImageDraw
from pynput import keyboard, mouse
import pystray

import key_tracker


APP_NAME = "KeyCounter"
DEVELOPER_NAME = "ぶんじカンパニー"
DEVELOPER_WEBSITE_URL = "https://bunjicompany.com/"
SAVE_INTERVAL_SECONDS = 30
RUN_REG_PATH = r"Software\Microsoft\Windows\CurrentVersion\Run"
LOCK_PORT = 47192
MB_YESNO = 0x00000004
MB_ICONWARNING = 0x00000030
MB_DEFBUTTON2 = 0x00000100
MB_SETFOREGROUND = 0x00010000
IDYES = 6
CONFIRM_RESET_ARG = "--confirm-reset"
SHOW_VERSION_ARG = "--show-version"
BUILD_INFO_FILE = "build_info.json"


def resource_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
    return Path(__file__).resolve().parent


def data_dir() -> Path:
    base = os.environ.get("LOCALAPPDATA")
    if base:
        path = Path(base) / APP_NAME
    else:
        path = Path.home() / f".{APP_NAME.lower()}"
    path.mkdir(parents=True, exist_ok=True)
    return path


RESOURCE_DIR = resource_dir()
DATA_DIR = data_dir()
STATS_FILE = DATA_DIR / "keys_stats.json"
VIEWER_FILE = RESOURCE_DIR / "stats_viewer.html"
VIEWER_OUTPUT_DIR = DATA_DIR / "viewer"
GENERATED_VIEWER_FILE = VIEWER_OUTPUT_DIR / "stats_viewer.generated.html"

paused = False
running = True
keyboard_listener = None
mouse_listener = None
reset_dialog_active = False
reset_dialog_lock = threading.Lock()
active_tick_at = None


def startup_command() -> str:
    if getattr(sys, "frozen", False):
        return f'"{sys.executable}"'
    return f'"{sys.executable}" "{Path(__file__).resolve()}"'


def is_startup_enabled(_item=None) -> bool:
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_REG_PATH, 0, winreg.KEY_READ) as key:
            value, _value_type = winreg.QueryValueEx(key, APP_NAME)
        return value == startup_command()
    except FileNotFoundError:
        return False
    except OSError:
        return False


def set_startup_enabled(enabled: bool) -> None:
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_REG_PATH, 0, winreg.KEY_SET_VALUE) as key:
        if enabled:
            winreg.SetValueEx(key, APP_NAME, 0, winreg.REG_SZ, startup_command())
        else:
            try:
                winreg.DeleteValue(key, APP_NAME)
            except FileNotFoundError:
                pass


def enable_startup(icon, _item=None) -> None:
    set_startup_enabled(True)
    icon.update_menu()


def disable_startup(icon, _item=None) -> None:
    set_startup_enabled(False)
    icon.update_menu()


def is_startup_disabled(_item=None) -> bool:
    return not is_startup_enabled()


def acquire_single_instance_lock() -> socket.socket | None:
    lock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        lock.bind(("127.0.0.1", LOCK_PORT))
        lock.listen(1)
        return lock
    except OSError:
        lock.close()
        return None


def migrate_existing_stats() -> None:
    if getattr(sys, "frozen", False):
        return
    old_file = RESOURCE_DIR / "keys_stats.json"
    if not STATS_FILE.exists() and old_file.exists():
        shutil.copy2(old_file, STATS_FILE)


def configure_tracker() -> None:
    key_tracker.STATS_FILE = STATS_FILE
    key_tracker.stats = key_tracker.load_stats()


def local_datetime(timestamp: float | None = None) -> datetime:
    if timestamp is None:
        return datetime.now().astimezone()
    return datetime.fromtimestamp(timestamp).astimezone()


def add_active_interval(meta: dict, start_ts: float, end_ts: float) -> None:
    if end_ts <= start_ts:
        return
    meta["active_seconds"] = float(meta.get("active_seconds", 0.0)) + (end_ts - start_ts)
    active_days = meta.setdefault("active_days", {})

    cur = local_datetime(start_ts)
    end = local_datetime(end_ts)
    while cur < end:
        next_day = (cur + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
        segment_end = min(next_day, end)
        day_key = cur.date().isoformat()
        active_days[day_key] = float(active_days.get(day_key, 0.0)) + (segment_end - cur).total_seconds()
        cur = segment_end


def mark_app_started() -> None:
    global active_tick_at
    now = time.time()
    with key_tracker.DATA_LOCK:
        meta = key_tracker.ensure_meta()
        ts = local_datetime(now).isoformat(timespec="seconds")
        meta.setdefault("first_started_at", ts)
        meta["last_started_at"] = ts
    active_tick_at = now


def update_active_time() -> None:
    global active_tick_at
    now = time.time()
    if active_tick_at is None:
        active_tick_at = now
        return
    with key_tracker.DATA_LOCK:
        if not paused and running:
            meta = key_tracker.ensure_meta()
            add_active_interval(meta, active_tick_at, now)
            meta["last_active_at"] = local_datetime(now).isoformat(timespec="seconds")
        active_tick_at = now


def save_stats_with_active_time() -> None:
    update_active_time()
    key_tracker.save_stats()


def save_loop() -> None:
    while running:
        time.sleep(SAVE_INTERVAL_SECONDS)
        if running:
            save_stats_with_active_time()


def on_press(key) -> None:
    if not paused:
        key_tracker.on_press(key)


def on_release(key) -> None:
    if not paused:
        key_tracker.on_release(key)


def on_mouse_click(x, y, button, pressed) -> None:
    if not paused:
        key_tracker.on_mouse_click(x, y, button, pressed)


def start_tracking() -> None:
    global keyboard_listener, mouse_listener
    mouse_listener = mouse.Listener(on_click=on_mouse_click)
    keyboard_listener = keyboard.Listener(on_press=on_press, on_release=on_release)
    mouse_listener.start()
    keyboard_listener.start()


def inline_script(filename: str) -> str:
    path = RESOURCE_DIR / "vendor" / filename
    return f"<script>\n{path.read_text(encoding='utf-8')}\n</script>"


def build_generated_viewer() -> Path:
    if key_tracker.STATS_FILE != STATS_FILE:
        configure_tracker()
    save_stats_with_active_time()
    VIEWER_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    html = VIEWER_FILE.read_text(encoding="utf-8")
    html = html.replace('<script src="vendor/chart.umd.min.js"></script>', inline_script("chart.umd.min.js"))
    html = html.replace('<script src="vendor/html2canvas.min.js"></script>', inline_script("html2canvas.min.js"))

    stats_json = STATS_FILE.read_text(encoding="utf-8") if STATS_FILE.exists() else "{}"
    embedded = f"<script>window.KEYCOUNTER_EMBEDDED_STATS = {stats_json};</script>"
    html = html.replace("</head>", f"{embedded}\n</head>", 1)

    GENERATED_VIEWER_FILE.write_text(html, encoding="utf-8")
    return GENERATED_VIEWER_FILE


def open_stats(_icon=None, _item=None) -> None:
    webbrowser.open(build_generated_viewer().as_uri())


def open_stats_file_location(_icon=None, _item=None) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    if STATS_FILE.exists():
        subprocess.Popen(["explorer", f"/select,{STATS_FILE}"])
    else:
        os.startfile(DATA_DIR)


def save_now(_icon=None, _item=None) -> None:
    save_stats_with_active_time()


def open_developer_website(_icon=None, _item=None) -> None:
    webbrowser.open(DEVELOPER_WEBSITE_URL)


def load_build_info() -> dict:
    path = RESOURCE_DIR / BUILD_INFO_FILE
    if not path.exists():
        return {"version": "unknown", "built_at": "unknown"}
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except (json.JSONDecodeError, OSError):
        return {"version": "unknown", "built_at": "unknown"}


def show_info_message(title: str, message: str) -> int:
    ctypes.windll.user32.MessageBoxW.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p, ctypes.c_wchar_p, ctypes.c_uint]
    ctypes.windll.user32.MessageBoxW.restype = ctypes.c_int
    ctypes.windll.user32.MessageBoxW(None, message, title, MB_SETFOREGROUND)
    return 0


def version_info_message() -> str:
    info = load_build_info()
    return (
        f"{APP_NAME}\n"
        f"Developed by {DEVELOPER_NAME}\n\n"
        f"バージョン: {info.get('version', 'unknown')}\n"
        f"ビルド日時: {info.get('built_at', 'unknown')}"
    )


def show_version_info_dialog() -> int:
    return show_info_message(f"{APP_NAME} - バージョン情報", version_info_message())


def show_version_info(_icon=None, _item=None) -> None:
    subprocess.Popen([sys.executable, SHOW_VERSION_ARG])


def confirm_reset_stats() -> bool:
    result = subprocess.run(
        [sys.executable, CONFIRM_RESET_ARG],
        timeout=120,
    )
    return result.returncode == 0


def show_reset_confirmation_dialog() -> int:
    ctypes.windll.user32.MessageBoxW.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p, ctypes.c_wchar_p, ctypes.c_uint]
    ctypes.windll.user32.MessageBoxW.restype = ctypes.c_int
    result = ctypes.windll.user32.MessageBoxW(
        None,
        "記録した押下回数・押下時間をすべてリセットします。\n"
        "この操作は元に戻せません。\n\n"
        "本当にリセットしますか？",
        "KeyCounter - 統計をリセット",
        MB_YESNO | MB_ICONWARNING | MB_DEFBUTTON2 | MB_SETFOREGROUND,
    )
    return 0 if result == IDYES else 1


def toggle_pause(icon, _item=None) -> None:
    global paused
    update_active_time()
    paused = not paused
    icon.title = tray_title()
    icon.update_menu()


def pause_label(_item) -> str:
    return "記録を再開" if paused else "記録を一時停止"


def reset_stats_after_confirmation() -> None:
    global reset_dialog_active
    try:
        if not confirm_reset_stats():
            return
        update_active_time()
        with key_tracker.DATA_LOCK:
            key_tracker.stats.clear()
            key_tracker.press_times.clear()
        mark_app_started()
        key_tracker.save_stats()
    finally:
        with reset_dialog_lock:
            reset_dialog_active = False


def reset_stats(_icon=None, _item=None) -> None:
    global reset_dialog_active
    with reset_dialog_lock:
        if reset_dialog_active:
            return
        reset_dialog_active = True
    threading.Thread(target=reset_stats_after_confirmation, daemon=True).start()


def quit_app(icon, _item=None) -> None:
    global running
    update_active_time()
    running = False
    key_tracker.save_stats()
    if keyboard_listener:
        keyboard_listener.stop()
    if mouse_listener:
        mouse_listener.stop()
    icon.stop()


def tray_title() -> str:
    return f"{APP_NAME} - {'一時停止中' if paused else '記録中'}"


def create_icon_image() -> Image.Image:
    img = Image.new("RGBA", (64, 64), (0, 120, 212, 255))
    draw = ImageDraw.Draw(img)
    draw.rounded_rectangle((6, 10, 58, 54), radius=10, fill=(255, 255, 255, 255))
    draw.rectangle((14, 19, 24, 29), fill=(0, 120, 212, 255))
    draw.rectangle((27, 19, 37, 29), fill=(0, 120, 212, 255))
    draw.rectangle((40, 19, 50, 29), fill=(0, 120, 212, 255))
    draw.rectangle((14, 34, 50, 44), fill=(247, 99, 12, 255))
    return img


def main() -> None:
    lock = acquire_single_instance_lock()
    if lock is None:
        return

    migrate_existing_stats()
    configure_tracker()
    mark_app_started()
    start_tracking()
    threading.Thread(target=save_loop, daemon=True).start()

    menu = pystray.Menu(
        pystray.MenuItem("統計を見る", open_stats, default=True),
        pystray.MenuItem("記録ファイルの場所を開く", open_stats_file_location),
        pystray.MenuItem(pause_label, toggle_pause),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("Windows起動時に実行する", enable_startup, enabled=is_startup_disabled),
        pystray.MenuItem("Windows起動時の登録を解除する", disable_startup, enabled=is_startup_enabled),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("今すぐ保存", save_now),
        pystray.MenuItem("統計をリセット", reset_stats),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("開発元Webサイト", open_developer_website),
        pystray.MenuItem("バージョン情報", show_version_info),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("終了", quit_app),
    )
    icon = pystray.Icon(APP_NAME, create_icon_image(), tray_title(), menu)
    icon.run()


if __name__ == "__main__":
    if CONFIRM_RESET_ARG in sys.argv:
        raise SystemExit(show_reset_confirmation_dialog())
    if SHOW_VERSION_ARG in sys.argv:
        raise SystemExit(show_version_info_dialog())
    main()
