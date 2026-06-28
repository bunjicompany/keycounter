"""
key_tracker.py
--------------
物理キーボードのキー別 + マウスボタン別統計をローカルに記録するツール。

保存するもの:
  - キー/ボタン識別子
  - 押下回数
  - 合計押下時間（秒）
  - 平均押下時間（秒）
  - 最大押下時間（秒）

保存しないもの:
  - 入力文字列・貼り付け文字列・クリップボード内容
  - 押下順序・時系列ログ・タイムスタンプ
  - マウス座標・移動量・スクロール量
"""

import json
import time
import signal
import sys
import threading
from pathlib import Path
from datetime import datetime
from pynput import keyboard, mouse

# --- 設定 ---
STATS_FILE = Path(__file__).parent / "keys_stats.json"
SAVE_INTERVAL = 30  # 秒ごとに自動保存
MAX_KEY_DURATION = 10.0  # キー押下がこれを超えた場合は記録しない
MAX_MOUSE_DURATION = 180.0  # マウス押下がこれを超えた場合は記録しない
IME_TOGGLE_SCAN_CODES = {41}  # 半角/全角キー。IME状態により vk_243 / vk_244 に揺れることがある。
KANA_SCAN_CODES = {112}
KANA_VKS = {21, 242, 244}
PRESS_COUNTED_KEYS = {"vk_243", "vk_244", "caps_lock"}  # 離上イベントが揺れやすいキーは押下時点で回数を確定する
PRESS_COUNT_DEBOUNCE = 0.03

# --- データ構造 ---
# stats[key_id] = {
#   "count": int,
#   "total_duration": float,
#   "max_duration": float,
# }
stats: dict[str, dict] = {}
press_times: dict[str, float] = {}  # 押下中のキーの開始時刻（一時的・保存しない）
last_press_counted_at: dict[str, float] = {}
DATA_LOCK = threading.RLock()
META_KEY = "_meta"


def load_stats() -> dict:
    """保存済み統計を読み込む。ファイルがなければ空dictを返す。"""
    if STATS_FILE.exists():
        try:
            with open(STATS_FILE, "r", encoding="utf-8") as f:
                return normalize_stats(json.load(f))
        except (json.JSONDecodeError, OSError):
            return {}
    return {}


def merge_entry(target: dict, source: dict) -> None:
    target["count"] = target.get("count", 0) + source.get("count", 0)
    target["total_duration"] = target.get("total_duration", 0.0) + source.get("total_duration", 0.0)
    target["max_duration"] = max(target.get("max_duration", 0.0), source.get("max_duration", 0.0))


def normalize_stats(data: dict) -> dict:
    """古い記録で分裂した特殊キー名を現在のキーIDに統合する。"""
    if META_KEY in data and not isinstance(data[META_KEY], dict):
        data.pop(META_KEY, None)
    if "alt_gr" in data:
        target = data.setdefault("alt_r", {"count": 0, "total_duration": 0.0, "max_duration": 0.0})
        merge_entry(target, data.pop("alt_gr"))
    if "escape" in data:
        target = data.setdefault("esc", {"count": 0, "total_duration": 0.0, "max_duration": 0.0})
        merge_entry(target, data.pop("escape"))
    if "shift" in data:
        target = data.setdefault("shift_l", {"count": 0, "total_duration": 0.0, "max_duration": 0.0})
        merge_entry(target, data.pop("shift"))
    for old_key in ("vk_20", "vk_240", "caps", "capital"):
        if old_key in data:
            target = data.setdefault("caps_lock", {"count": 0, "total_duration": 0.0, "max_duration": 0.0})
            merge_entry(target, data.pop(old_key))
    for old_key in ("vk_21", "vk_242", "kana", "hiragana", "katakana"):
        if old_key in data:
            target = data.setdefault("vk_244", {"count": 0, "total_duration": 0.0, "max_duration": 0.0})
            merge_entry(target, data.pop(old_key))
    return data


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def ensure_meta() -> dict:
    meta = stats.setdefault(META_KEY, {})
    if not isinstance(meta, dict):
        meta = {}
        stats[META_KEY] = meta
    meta.setdefault("active_seconds", 0.0)
    meta.setdefault("active_days", {})
    return meta


def mark_recorded_event() -> None:
    """実際にキー/クリックが1件記録された時刻をメタ情報へ反映する。"""
    meta = ensure_meta()
    ts = now_iso()
    meta.setdefault("first_recorded_at", ts)
    meta["last_recorded_at"] = ts


def save_stats() -> None:
    """統計をJSONファイルに保存する。"""
    with DATA_LOCK:
        ensure_meta()
        payload = json.dumps(stats, ensure_ascii=False, indent=2)

    tmp_file = STATS_FILE.with_suffix(".tmp")
    with open(tmp_file, "w", encoding="utf-8") as f:
        f.write(payload)
    tmp_file.replace(STATS_FILE)


def ensure_entry(key_id: str) -> dict:
    if key_id not in stats:
        stats[key_id] = {"count": 0, "total_duration": 0.0, "max_duration": 0.0}
    return stats[key_id]


def key_to_id(key) -> str:
    """
    キーを文字列識別子に変換する。
    文字の内容（'a', 'A' など）ではなくキー名を返す。
    英数字キーはスキャンコードベースの識別子を使用。
    """
    if isinstance(key, keyboard.KeyCode):
        # 文字キー: 文字内容は捨て、仮想キーコード（vk）で識別
        if key.vk is not None:
            scan = getattr(key, "_scan", None)
            if key.vk in (20, 240):
                return "caps_lock"
            if key.vk in (243, 244) and scan in IME_TOGGLE_SCAN_CODES:
                return "vk_243"
            if scan in KANA_SCAN_CODES or key.vk in (KANA_VKS - {244}):
                return "vk_244"
            if key.vk == 244:
                return "vk_243"
            return f"vk_{key.vk}"
        elif key.char is not None:
            # vkがない場合のフォールバック（稀）
            # 文字そのものは使わず、ordで識別
            return f"ord_{ord(key.char)}"
        else:
            return "unknown"
    elif isinstance(key, keyboard.Key):
        # 特殊キー（Enter, Shift, Ctrl など）
        if key.name == "alt_gr":
            return "alt_r"
        if key.name == "escape":
            return "esc"
        if key.name == "shift":
            return "shift_l"
        if key.name in ("kana", "hiragana", "katakana"):
            return "vk_244"
        return key.name
    else:
        return str(key)


def on_press(key) -> None:
    """キーが押されたときのコールバック。"""
    key_id = key_to_id(key)
    now = time.perf_counter()
    with DATA_LOCK:
        if key_id in PRESS_COUNTED_KEYS:
            last = last_press_counted_at.get(key_id, 0.0)
            if now - last >= PRESS_COUNT_DEBOUNCE:
                ensure_entry(key_id)["count"] += 1
                mark_recorded_event()
                last_press_counted_at[key_id] = now
            press_times[key_id] = now
            return

        # すでに押下中（キーリピート）の場合は無視
        if key_id in press_times:
            return
        press_times[key_id] = now


def on_release(key) -> None:
    """キーが離されたときのコールバック。"""
    key_id = key_to_id(key)
    with DATA_LOCK:
        start = press_times.pop(key_id, None)
        if start is None:
            return  # on_pressが記録されていない場合はスキップ

        duration = time.perf_counter() - start
        if duration > MAX_KEY_DURATION:
            return

        entry = ensure_entry(key_id)
        if key_id not in PRESS_COUNTED_KEYS:
            entry["count"] += 1
            mark_recorded_event()
        entry["total_duration"] += duration
        if duration > entry["max_duration"]:
            entry["max_duration"] = duration


def mouse_button_id(button) -> str:
    """マウスボタンを識別子に変換する。"""
    name = getattr(button, 'name', None) or str(button)
    return f"mouse_{name}"


def on_mouse_click(x, y, button, pressed) -> None:
    """マウスボタンが押された/離されたときのコールバック。座標は無視。"""
    btn_id = mouse_button_id(button)
    with DATA_LOCK:
        if pressed:
            if btn_id not in press_times:
                press_times[btn_id] = time.perf_counter()
        else:
            start = press_times.pop(btn_id, None)
            if start is None:
                return
            duration = time.perf_counter() - start
            if duration > MAX_MOUSE_DURATION:
                return
            if btn_id not in stats:
                stats[btn_id] = {"count": 0, "total_duration": 0.0, "max_duration": 0.0}
            entry = stats[btn_id]
            entry["count"] += 1
            mark_recorded_event()
            entry["total_duration"] += duration
            if duration > entry["max_duration"]:
                entry["max_duration"] = duration


def periodic_save() -> None:
    """定期保存ループ（別スレッドで動作）。"""
    def _loop():
        while True:
            time.sleep(SAVE_INTERVAL)
            save_stats()
    t = threading.Thread(target=_loop, daemon=True)
    t.start()


def handle_exit(signum, frame) -> None:
    """Ctrl+C / SIGTERMで終了時に保存。"""
    print("\n終了します。統計を保存中...")
    save_stats()
    sys.exit(0)


def main() -> None:
    global stats
    stats = load_stats()

    signal.signal(signal.SIGINT, handle_exit)
    signal.signal(signal.SIGTERM, handle_exit)

    periodic_save()

    print(f"キー＆マウス統計の記録を開始しました。")
    print(f"保存先: {STATS_FILE.resolve()}")
    print(f"終了するには Ctrl+C を押してください。")
    print()

    mouse_listener = mouse.Listener(on_click=on_mouse_click)
    mouse_listener.start()

    with keyboard.Listener(on_press=on_press, on_release=on_release) as kb_listener:
        kb_listener.join()


if __name__ == "__main__":
    main()
