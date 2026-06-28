"""
show_stats.py
-------------
keys_stats.json の統計を表形式で表示する。

使い方:
  python show_stats.py              # 押下回数の多い順に表示（上位50件）
  python show_stats.py --all        # 全キーを表示
  python show_stats.py --sort avg   # 平均押下時間順
  python show_stats.py --sort max   # 最大押下時間順
  python show_stats.py --sort total # 合計押下時間順
  python show_stats.py --sort count # 押下回数順（デフォルト）
"""

import json
import argparse
from pathlib import Path

STATS_FILE = Path(__file__).parent / "keys_stats.json"

# vk番号 → わかりやすいキー名のマップ（主要なもの）
VK_NAMES = {
    8: "Backspace", 9: "Tab", 13: "Enter", 20: "CapsLock",
    21: "カタカナ/ひらがな", 27: "Escape", 32: "Space", 33: "PageUp", 34: "PageDown",
    35: "End", 36: "Home", 37: "Left", 38: "Up", 39: "Right", 40: "Down",
    45: "Insert", 46: "Delete",
    48: "0", 49: "1", 50: "2", 51: "3", 52: "4",
    53: "5", 54: "6", 55: "7", 56: "8", 57: "9",
    65: "A", 66: "B", 67: "C", 68: "D", 69: "E",
    70: "F", 71: "G", 72: "H", 73: "I", 74: "J",
    75: "K", 76: "L", 77: "M", 78: "N", 79: "O",
    80: "P", 81: "Q", 82: "R", 83: "S", 84: "T",
    85: "U", 86: "V", 87: "W", 88: "X", 89: "Y", 90: "Z",
    96: "Num0", 97: "Num1", 98: "Num2", 99: "Num3", 100: "Num4",
    101: "Num5", 102: "Num6", 103: "Num7", 104: "Num8", 105: "Num9",
    106: "Num*", 107: "Num+", 109: "Num-", 110: "Num.", 111: "Num/",
    112: "F1", 113: "F2", 114: "F3", 115: "F4", 116: "F5", 117: "F6",
    118: "F7", 119: "F8", 120: "F9", 121: "F10", 122: "F11", 123: "F12",
    144: "NumLock", 145: "ScrollLock",
    186: "*", 187: "+", 188: ",", 189: "-", 190: ".", 191: "/",
    192: "@", 219: "[", 220: "¥", 221: "]", 222: "^",
    242: "カタカナ/ひらがな", 243: "半角/全角", 244: "カタカナ/ひらがな",
}

SPECIAL_NAMES = {
    "shift_l": "Shift(L)", "shift_r": "Shift(R)",
    "ctrl_l": "Ctrl(L)", "ctrl_r": "Ctrl(R)",
    "alt_l": "Alt(L)", "alt_r": "Alt(R)", "alt_gr": "Alt(R)",
    "cmd": "Win", "cmd_l": "Win(L)", "cmd_r": "Win(R)",
    "space": "Space", "enter": "Enter", "backspace": "Backspace",
    "tab": "Tab", "caps_lock": "CapsLock", "esc": "Escape",
    "delete": "Delete", "insert": "Insert",
    "home": "Home", "end": "End", "page_up": "PageUp", "page_down": "PageDown",
    "left": "Left", "right": "Right", "up": "Up", "down": "Down",
    "print_screen": "PrintScreen", "pause": "Pause",
}

MOUSE_NAMES = {
    "mouse_left": "MouseLeft",
    "mouse_right": "MouseRight",
    "mouse_middle": "MouseMiddle",
    "mouse_x1": "MouseBack",
    "mouse_x2": "MouseForward",
}


def friendly_name(key_id: str) -> str:
    """key_idをわかりやすいキー名に変換する。"""
    if key_id.startswith("vk_"):
        vk = int(key_id[3:])
        return VK_NAMES.get(vk, f"vk{vk}")
    elif key_id.startswith("ord_"):
        return f"ord{key_id[4:]}"
    elif key_id.startswith("mouse_"):
        return MOUSE_NAMES.get(key_id, key_id)
    else:
        # 特殊キー名（pynput の Key.name）
        return SPECIAL_NAMES.get(key_id, key_id)


def fmt_ms(seconds: float) -> str:
    """秒をミリ秒文字列に変換。"""
    return f"{seconds * 1000:.1f}ms"


def main():
    parser = argparse.ArgumentParser(description="キー押下統計を表示する")
    parser.add_argument("--all", action="store_true", help="全キーを表示（デフォルト: 上位50件）")
    parser.add_argument("--sort", choices=["count", "total", "avg", "max"], default="count",
                        help="ソート順（デフォルト: count）")
    parser.add_argument("--ignore-outliers", action="store_true",
                        help="長すぎる押下データを含むキー/ボタンを表示から除外")
    parser.add_argument("--key-outlier-seconds", type=float, default=10.0,
                        help="キーボード押下の外れ値しきい値（秒、デフォルト: 10）")
    parser.add_argument("--mouse-outlier-seconds", type=float, default=180.0,
                        help="マウス押下の外れ値しきい値（秒、デフォルト: 180）")
    args = parser.parse_args()

    if not STATS_FILE.exists():
        print(f"統計ファイルが見つかりません: {STATS_FILE}")
        print("先に key_tracker.py を実行してキーを記録してください。")
        return

    with open(STATS_FILE, "r", encoding="utf-8") as f:
        raw: dict = json.load(f)

    if not raw:
        print("統計データが空です。")
        return

    # 表示用データを構築
    rows = []
    total_count = 0
    for key_id, entry in raw.items():
        if key_id.startswith("_"):
            continue
        count = entry.get("count", 0)
        total = entry.get("total_duration", 0.0)
        max_dur = entry.get("max_duration", 0.0)
        outlier_limit = args.mouse_outlier_seconds if key_id.startswith("mouse_") else args.key_outlier_seconds
        if args.ignore_outliers and max_dur > outlier_limit:
            continue
        avg = total / count if count > 0 else 0.0
        rows.append({
            "key": friendly_name(key_id),
            "count": count,
            "total": total,
            "avg": avg,
            "max": max_dur,
        })
        total_count += count

    # ソート
    sort_key = {"count": "count", "total": "total", "avg": "avg", "max": "max"}[args.sort]
    rows.sort(key=lambda r: r[sort_key], reverse=True)
    row_count = len(rows)

    # 件数制限
    if not args.all:
        rows = rows[:50]

    # ヘッダー
    header = f"{'キー':<14} {'押下回数':>8} {'割合':>6} {'合計時間':>10} {'平均時間':>10} {'最大時間':>10}"
    sep = "-" * len(header)
    print(sep)
    print(header)
    print(sep)

    for r in rows:
        pct = r["count"] / total_count * 100 if total_count > 0 else 0
        print(
            f"{r['key']:<14} "
            f"{r['count']:>8,} "
            f"{pct:>5.1f}% "
            f"{fmt_ms(r['total']):>10} "
            f"{fmt_ms(r['avg']):>10} "
            f"{fmt_ms(r['max']):>10}"
        )

    print(sep)
    print(f"合計押下回数: {total_count:,}  |  記録キー数: {row_count}")
    if not args.all and row_count > 50:
        print(f"（上位50件を表示。全件表示は --all オプションを使用）")


if __name__ == "__main__":
    main()
