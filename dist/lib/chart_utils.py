#!/usr/bin/env python3
"""
Terminal Chart Shared Utilities — ANSI colors, data formatting, Braille rendering.
Used by both kchart.py (K-line) and fenshi.py (分时图).
"""

import sys
import json
import subprocess
import shutil
import os
from datetime import datetime

# ── ANSI helpers ──────────────────────────────────────────────

ESC = "\033["
RESET = f"{ESC}0m"
BOLD = f"{ESC}1m"
DIM = f"{ESC}2m"
CLEAR = f"{ESC}2J{ESC}H"
HIDE_CUR = f"{ESC}?25l"
SHOW_CUR = f"{ESC}?25h"

def fg(r, g, b): return f"{ESC}38;2;{r};{g};{b}m"
def bg(r, g, b): return f"{ESC}48;2;{r};{g};{b}m"
def move_to(row, col): return f"{ESC}{row};{col}H"
def clear_line(): return f"{ESC}2K"

# Stock app standard colors
C_RED    = fg(232, 76, 61)     # 涨 (up, 阳线)
C_GREEN  = fg(38, 166, 91)     # 跌 (down, 阴线)
C_YELLOW = fg(240, 200, 60)    # 均线/参考线
C_WHITE  = fg(220, 220, 220)   # 主要文字
C_DIM    = fg(110, 110, 130)   # 次要文字/标签
C_CYAN   = fg(80, 200, 220)    # PE 指标
C_MAGENTA = fg(200, 120, 200)  # MA20/MA60
C_BLUE   = fg(80, 160, 255)    # MA10
C_ORANGE = fg(255, 160, 60)    # MA5
C_BG     = bg(26, 26, 46)      # 深色背景 #1A1A2E

# ── Braille rendering (shared between chart types) ────────────

BRAILLE_BASE = 0x2800
_BIT_AT = [[0x01, 0x08], [0x02, 0x10], [0x04, 0x20], [0x40, 0x80]]


def braille_points(points, trace_w, height_rows, ymin, ymax):
    """Map data points to a sub-pixel bitmap, return (bitmap, sub_rows, sub_cols).
    Each cell contains the source point index or -1."""
    sub_rows = height_rows * 4
    sub_cols = trace_w * 2
    bitmap = [[-1] * sub_cols for _ in range(sub_rows)]

    if not points or ymax <= ymin:
        return bitmap, sub_rows, sub_cols

    n = len(points)
    prev_sr = None
    prev_sc = 0

    for i, val in enumerate(points):
        sc = int(i * (sub_cols - 1) / max(n - 1, 1))
        ratio = (val - ymin) / (ymax - ymin) if ymax > ymin else 0.5
        sr = int((1.0 - ratio) * (sub_rows - 1))
        sr = max(0, min(sub_rows - 1, sr))
        bitmap[sr][sc] = i

        if prev_sr is not None and abs(sr - prev_sr) > 1:
            a, b = (prev_sr, sr) if prev_sr < sr else (sr, prev_sr)
            for fill_r in range(a + 1, b):
                frac = (fill_r - prev_sr) / (sr - prev_sr) if sr != prev_sr else 0
                fill_c = int(prev_sc + frac * (sc - prev_sc))
                if 0 <= fill_r < sub_rows and 0 <= fill_c < sub_cols and bitmap[fill_r][fill_c] == -1:
                    bitmap[fill_r][fill_c] = i

        prev_sr = sr
        prev_sc = sc

    return bitmap, sub_rows, sub_cols


def bitmap_to_braille(bitmap, sub_rows, sub_cols, height_rows, trace_w):
    """Convert sub-pixel bitmap to Braille character grid."""
    rows = []
    for row in range(height_rows):
        cells = []
        for col in range(trace_w):
            code = 0
            src = -1
            for r in range(4):
                for c in range(2):
                    br = row * 4 + r
                    bc = col * 2 + c
                    if 0 <= br < sub_rows and 0 <= bc < sub_cols and bitmap[br][bc] >= 0:
                        code |= _BIT_AT[r][c]
                        if src < 0:
                            src = bitmap[br][bc]
            cells.append((" " if code == 0 else chr(BRAILLE_BASE + code), src))
        rows.append(cells)
    return rows


def braille_bool_overlay(points, trace_w, height_rows, ymin, ymax):
    """Create a boolean Braille overlay (e.g., for avg price line).
    Returns list of strings per row."""
    sub_rows = height_rows * 4
    sub_cols = trace_w * 2
    bitmap = [[False] * sub_cols for _ in range(sub_rows)]

    if not points or ymax <= ymin:
        return [" " * trace_w] * height_rows

    n = len(points)
    prev_sr = None
    prev_sc = 0

    for i, val in enumerate(points):
        if val is None:
            prev_sr = None
            continue
        sc = int(i * (sub_cols - 1) / max(n - 1, 1))
        ratio = (val - ymin) / (ymax - ymin) if ymax > ymin else 0.5
        sr = int((1.0 - ratio) * (sub_rows - 1))
        sr = max(0, min(sub_rows - 1, sr))
        bitmap[sr][sc] = True

        if prev_sr is not None and abs(sr - prev_sr) > 1:
            a, b = (prev_sr, sr) if prev_sr < sr else (sr, prev_sr)
            for fill_r in range(a + 1, b):
                frac = (fill_r - prev_sr) / (sr - prev_sr) if sr != prev_sr else 0
                fill_c = int(prev_sc + frac * (sc - prev_sc))
                if 0 <= fill_r < sub_rows and 0 <= fill_c < sub_cols:
                    bitmap[fill_r][fill_c] = True

        prev_sr = sr
        prev_sc = sc

    lines = []
    for row in range(height_rows):
        line = []
        for col in range(trace_w):
            code = 0
            for r in range(4):
                for c in range(2):
                    br = row * 4 + r
                    bc = col * 2 + c
                    if 0 <= br < sub_rows and 0 <= bc < sub_cols and bitmap[br][bc]:
                        code |= _BIT_AT[r][c]
            line.append(" " if code == 0 else chr(BRAILLE_BASE + code))
        lines.append("".join(line))
    return lines


# ── Data helpers ──────────────────────────────────────────────

def run_snowball(args):
    """Execute snowball CLI and return stdout text."""
    snowball_path = shutil.which("snowball")
    if not snowball_path:
        for p in [os.path.expanduser("~/AppData/Roaming/npm/snowball.cmd"),
                  os.path.expanduser("~/AppData/Roaming/npm/snowball"),
                  "/usr/local/bin/snowball"]:
            if os.path.exists(p):
                snowball_path = p
                break
    if not snowball_path:
        sys.stderr.write("Error: snowball CLI not found\n")
        sys.exit(1)
    if sys.platform == "win32":
        cmd = ["cmd", "/c", "snowball"] + args
    else:
        cmd = [snowball_path] + args
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    if result.returncode != 0 and not result.stdout.strip():
        sys.stderr.write(f"Error: {result.stderr.strip()}\n")
        sys.exit(1)
    return result.stdout.strip()


def fmt_vol(v):
    if not isinstance(v, (int, float)) or v == 0:
        return "-"
    if v >= 1e8:
        return f"{v/1e8:.1f}亿"
    if v >= 1e4:
        return f"{v/1e4:.0f}万"
    return str(int(v))


def fmt_amt(a):
    if not isinstance(a, (int, float)) or a == 0:
        return "-"
    if a >= 1e8:
        return f"{a/1e8:.1f}亿"
    if a >= 1e4:
        return f"{a/1e4:.0f}万"
    return f"{a:.0f}"


def fmt_pct(v):
    """Format percentage with sign."""
    if v is None:
        return "N/A"
    sign = "+" if v >= 0 else ""
    return f"{sign}{v:.2f}%"


def fetch_json(command_args):
    """Run snowball command and parse JSON output."""
    raw = run_snowball(command_args)
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        sys.stderr.write(f"Failed to parse JSON from: {' '.join(command_args)}\n")
        sys.stderr.write(raw[:200] + "\n")
        sys.exit(1)


# ── Time helpers ──────────────────────────────────────────────

def slot_from_time(h, m):
    """Map trading hour:minute to 0-239 slot index for A-share market.
    9:30=0, 11:30=119(闭市), 13:00=120(开市), 15:00=239(收盘).
    After-hours (>15:00) maps to 239."""
    if h == 9 and m >= 30: return m - 30
    elif h == 10: return 30 + m
    elif h == 11 and m <= 30: return 90 + m
    elif h == 13: return 120 + m
    elif h == 14: return 180 + m
    elif h >= 15: return 239
    return -1


def compute_trace_width(chart_w, now=None):
    """Compute trace width based on elapsed trading time proportion.
    A-share: 9:30-11:30 morning + 13:00-15:00 afternoon = 240 minutes."""
    if now is None:
        now = datetime.now()
    h, m = now.hour, now.minute
    total = 240
    if h < 9 or (h == 9 and m < 30):
        elapsed = 0
    elif h < 12:
        elapsed = (h - 9) * 60 + m - 30
    elif h < 13:
        elapsed = 120
    elif h < 15:
        elapsed = 120 + (h - 13) * 60 + m
    else:
        elapsed = 240
    frac = min(elapsed / total, 1.0)
    return max(2, int(chart_w * frac))


def round_price(price, step=0.5):
    """Round to nearest nice step for Y-axis labels."""
    return round(price / step) * step


def nice_y_range(ymin, ymax, levels=5):
    """Compute nice Y-axis range with rounded levels."""
    span = ymax - ymin
    if span <= 0:
        if ymin <= 0:
            return [0, 1, 2, 3, 4], 0, 4
        return [ymin * (1 + i * 0.02) for i in range(levels)], ymin * 0.98, ymax * 1.02
    # Find nice step size
    raw_step = span / (levels - 1)
    magnitude = 10 ** (len(str(int(raw_step))) - 1) if raw_step >= 1 else 0.1
    nice_step = round(raw_step / magnitude) * magnitude
    if nice_step == 0:
        nice_step = max(raw_step, 0.01)
    nice_min = (ymin // nice_step) * nice_step
    nice_max = ((ymax // nice_step) + 1) * nice_step
    if nice_max - nice_min < span:
        nice_max += nice_step
    levels_out = []
    v = nice_min
    while v <= nice_max + nice_step * 0.5:
        levels_out.append(v)
        v += nice_step
    return levels_out, nice_min, nice_max
