#!/usr/bin/env python3
"""
snowball kchart --period minute — Terminal Intraday Minute Chart (分时图)
Uses Unicode Braille characters for high-resolution rendering, inspired by glint.
Usage: snowball kchart <symbol> --period minute [--refresh 30]
"""

import sys
import json
import subprocess
import time
import os
import shutil
from datetime import datetime

# ── ANSI helpers ──────────────────────────────────────────────

ESC = "\033["
RESET = f"{ESC}0m"
BOLD = f"{ESC}1m"
DIM = f"{ESC}2m"

def fg(r, g, b): return f"{ESC}38;2;{r};{g};{b}m"
def bg(r, g, b): return f"{ESC}48;2;{r};{g};{b}m"

# Theme colors
C_RED     = fg(232, 76, 61)
C_GREEN   = fg(38, 166, 91)
C_YELLOW  = fg(240, 200, 60)
C_WHITE   = fg(220, 220, 220)
C_DIM     = fg(110, 110, 130)
C_DARK    = fg(70, 70, 90)
C_CYAN    = fg(80, 200, 220)
C_BG      = bg(22, 22, 40)

# ── Braille rendering ────────────────────────────────────────

BRAILLE_BASE = 0x2800
BIT_AT = [
    [0x01, 0x08],
    [0x02, 0x10],
    [0x04, 0x20],
    [0x40, 0x80],
]

def braille_char(bitmap, row, col, sub_rows, sub_cols):
    """Get Braille character for a 4x2 sub-cell at (row_block, col_block)."""
    code = 0
    for r in range(4):
        for c in range(2):
            br = row * 4 + r
            bc = col * 2 + c
            if 0 <= br < sub_rows and 0 <= bc < sub_cols:
                if bitmap[br][bc]:
                    code |= BIT_AT[r][c]
    if code == 0:
        return None
    return chr(BRAILLE_BASE + code)


def render_braille(points, width, height_rows, ymin, ymax):
    """Render a price series as Braille character grid.
    Returns list of strings, one per row (top to bottom).
    points: list of float values
    width: character columns for the chart area
    height_rows: character rows for the chart area
    """
    if not points or ymax <= ymin:
        return [" " * width] * height_rows

    sub_rows = height_rows * 4
    sub_cols = width * 2
    # Use plain list of lists instead of numpy
    bitmap = [[False] * sub_cols for _ in range(sub_rows)]

    n = len(points)

    # Map each point to sub-pixel coordinates
    prev_sr = None
    prev_sc = 0
    for i, val in enumerate(points):
        sc = int(i * (sub_cols - 1) / max(n - 1, 1))
        if ymax == ymin:
            sr = sub_rows // 2
        else:
            ratio = (val - ymin) / (ymax - ymin)
            sr = int((1.0 - ratio) * (sub_rows - 1))
            sr = max(0, min(sub_rows - 1, sr))

        bitmap[sr][sc] = True

        # Connect to previous point to avoid gaps
        if prev_sr is not None and abs(sr - prev_sr) > 1:
            step = 1 if sr > prev_sr else -1
            for fill_r in range(prev_sr + step, sr, step):
                frac = (fill_r - prev_sr) / (sr - prev_sr) if sr != prev_sr else 0
                fill_c = int(prev_sc + frac * (sc - prev_sc))
                if 0 <= fill_r < sub_rows and 0 <= fill_c < sub_cols:
                    bitmap[fill_r][fill_c] = True

        prev_sr = sr
        prev_sc = sc

    # Fold bitmap into Braille characters
    lines = []
    for row in range(height_rows):
        line = []
        for col in range(width):
            ch = braille_char(bitmap, row, col, sub_rows, sub_cols)
            line.append(ch if ch else " ")
        lines.append("".join(line))

    return lines


# ── Data fetching ─────────────────────────────────────────────

def run_snowball(args):
    snowball_path = shutil.which("snowball")
    if not snowball_path:
        for p in [os.path.expanduser("~/AppData/Roaming/npm/snowball.cmd"),
                  os.path.expanduser("~/AppData/Roaming/npm/snowball"),
                  "/usr/local/bin/snowball"]:
            if os.path.exists(p):
                snowball_path = p
                break
    if not snowball_path:
        print("Error: snowball CLI not found", file=sys.stderr)
        sys.exit(1)

    if sys.platform == "win32":
        cmd = ["cmd", "/c", "snowball"] + args
    else:
        cmd = [snowball_path] + args

    result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    if result.returncode != 0 and not result.stdout.strip():
        print(f"Error: {result.stderr.strip()}", file=sys.stderr)
        sys.exit(1)
    return result.stdout.strip()


def fmt_volume(v):
    if v >= 1e8:
        return f"{v/1e8:.1f}亿"
    if v >= 1e4:
        return f"{v/1e4:.0f}万"
    return str(int(v))


def fmt_amount(a):
    if a >= 1e8:
        return f"{a/1e8:.1f}亿"
    if a >= 1e4:
        return f"{a/1e4:.0f}万"
    return f"{a:.0f}"


def slot_from_time(h, m):
    """Map hour:minute to slot index (0-239)."""
    if 9 <= h < 12:
        mins = (h - 9) * 60 + m - 30
        if mins < 0:
            mins = 0
        return max(0, min(119, mins))
    elif 13 <= h <= 15:
        mins = (h - 13) * 60 + m
        return 120 + max(0, min(119, mins))
    return -1


def fetch_data(symbol):
    """Fetch and parse minute + quote data."""
    raw_minute = run_snowball(["minute", symbol])
    minute_data = json.loads(raw_minute)

    raw_quote = run_snowball(["quote", symbol])
    quote_list = json.loads(raw_quote)
    quote = quote_list[0] if quote_list else {}

    last_close = minute_data.get("last_close") or quote.get("last_close", 0)
    after = minute_data.get("after", [])

    prices = [None] * 240
    avg_prices = [None] * 240
    slot_data = {}

    for pt in after:
        ts = pt["timestamp"] / 1000
        dt = datetime.fromtimestamp(ts)
        slot = slot_from_time(dt.hour, dt.minute)
        if slot < 0:
            continue
        prices[slot] = pt.get("current")
        avg_prices[slot] = pt.get("avg_price")
        slot_data[slot] = pt

    # Fill forward
    last_valid = last_close
    for i in range(240):
        if prices[i] is not None:
            last_valid = prices[i]
        else:
            prices[i] = last_valid

    # Per-minute volumes
    per_minute_vol = [0] * 240
    for slot, pt in slot_data.items():
        vol = pt.get("volume")
        if vol and vol > 0:
            per_minute_vol[slot] = vol

    # Fallback: distribute total volume if per-minute is sparse
    if not any(v > 0 for v in per_minute_vol):
        total_vol = quote.get("volume", 0)
        if total_vol and total_vol > 0 and slot_data:
            per_bar = total_vol / len(slot_data)
            for slot in slot_data:
                per_minute_vol[slot] = int(per_bar)

    # Find last active slot
    last_slot = 0
    for i in range(239, -1, -1):
        if i in slot_data or per_minute_vol[i] > 0:
            last_slot = i
            break
    if last_slot == 0 and after:
        last_slot = 239

    return {
        "last_close": last_close,
        "prices": prices,
        "avg_prices": avg_prices,
        "per_minute_vol": per_minute_vol,
        "last_slot": last_slot,
        "quote": quote,
        "slot_data": slot_data,
    }


# ── Rendering ─────────────────────────────────────────────────

def draw_fenshi(symbol, refresh_interval=0):
    import shutil

    term_size = shutil.get_terminal_size((120, 36))
    term_w = min(term_size.columns, 140)
    term_h = min(term_size.lines, 42)

    while True:
        data = fetch_data(symbol)
        last_close = data["last_close"]
        prices = data["prices"]
        avg_prices = data["avg_prices"]
        per_minute_vol = data["per_minute_vol"]
        last_slot = data["last_slot"]
        quote = data["quote"]

        if not last_close:
            print("No intraday data available.")
            return

        n = last_slot + 1
        active_prices = prices[:n]
        active_avg = avg_prices[:n]
        active_vol = per_minute_vol[:n]

        # ── Layout ──
        # Row 0: header
        # Row 1: period tabs
        # Rows 2-2+price_h: price chart (with Y-axis labels)
        # Row separator
        # Rows vol area: volume bars (with label)
        # Row: info bar line 1
        # Row: info bar line 2

        y_label_w = 10  # "129.86 " width
        y_pct_w = 8     # "+1.80%" width
        x_label_h = 1
        price_h = max(8, term_h - 14)  # chart rows for price
        vol_h = 4                       # chart rows for volume
        chart_w = term_w - y_label_w - y_pct_w - 2  # chart character columns

        if chart_w < 20:
            chart_w = 60
            term_w = chart_w + y_label_w + y_pct_w + 2

        # ── Y-axis: 9 levels centered on last_close ──
        max_pct = 1.80
        # Expand if actual range exceeds
        actual_max = max(active_prices)
        actual_min = min(active_prices)
        step_pct = max_pct / 4  # 0.45%
        step_price = last_close * step_pct / 100
        while actual_max > last_close + 4 * step_price:
            step_price *= 1.3
            step_pct = step_price / last_close * 100
        while actual_min < last_close - 4 * step_price:
            step_price *= 1.3
            step_pct = step_price / last_close * 100

        y_levels = []
        y_labels_left = []
        y_labels_right = []
        for k in range(4, -5, -1):
            p = last_close + k * step_price
            pct = k * step_pct
            y_levels.append(p)
            sign = "+" if pct >= 0 else ""
            y_labels_left.append(f"{p:>9.2f}")
            y_labels_right.append(f"{sign}{pct:>6.2f}%")

        ymin = y_levels[-1]
        ymax = y_levels[0]

        # ── Render price Braille chart ──
        price_lines = render_braille(active_prices, chart_w, price_h, ymin, ymax)
        avg_lines = render_braille(
            [v if v is not None else last_close for v in active_avg],
            chart_w, price_h, ymin, ymax
        )

        # Reference line row (where last_close falls)
        if ymax > ymin:
            ref_ratio = (last_close - ymin) / (ymax - ymin)
            ref_row = int((1.0 - ref_ratio) * (price_h - 1))
            ref_row = max(0, min(price_h - 1, ref_row))
        else:
            ref_row = price_h // 2

        # ── X-axis time labels ──
        def slot_to_x(s):
            return int(s * (chart_w - 1) / max(n - 1, 1))

        time_marks = [
            (0, "9:30"), (60, "10:30"), (119, "11:30"),
            (120, "13:00"), (180, "14:00"), (min(239, n-1), "15:00")
        ]

        # ── Build output ──
        out = []
        out.append(C_BG)  # set background

        # Row 0: Header
        cur = active_prices[-1]
        chg_val = cur - last_close
        pct_val = chg_val / last_close * 100 if last_close else 0
        sign = "+" if pct_val >= 0 else ""
        now_str = datetime.now().strftime("%H:%M:%S")
        price_color = C_RED if pct_val >= 0 else C_GREEN

        header = f" {C_WHITE}{BOLD}{symbol}{RESET}{C_BG}  {price_color}{BOLD}{cur:.2f}  {sign}{pct_val:.2f}%{RESET}{C_BG}    {C_DIM}{now_str}{RESET}{C_BG}"
        out.append(header.ljust(term_w))

        # Row 1: Period tabs
        tabs = ["分时", "日K", "周K", "月K", "股价提醒"]
        tab_str = ""
        for i, t in enumerate(tabs):
            if i == 0:
                tab_str += f" {C_WHITE}{BOLD}[{t}]{RESET}{C_BG}"
            else:
                tab_str += f" {C_DIM}[{t}]{RESET}{C_BG}"
        out.append(tab_str.ljust(term_w))

        # Rows 2+: Price chart with Y-axis
        for row in range(price_h):
            left_label = y_labels_left[row] if row < len(y_labels_left) else " " * 9
            right_label = y_labels_right[row] if row < len(y_labels_right) else " " * 7

            # Determine line color
            line = price_lines[row]
            avg_line = avg_lines[row]

            # Merge avg line into price line (avg in yellow)
            merged = []
            for ci in range(len(line)):
                pch = line[ci] if ci < len(line) else " "
                ach = avg_line[ci] if ci < len(avg_line) else " "
                if ach != " " and pch == " ":
                    merged.append((ach, C_YELLOW))
                elif pch != " ":
                    # Determine color based on which price this column maps to
                    col_idx = int(ci / (chart_w - 1) * (n - 1)) if chart_w > 1 else 0
                    col_idx = max(0, min(n - 1, col_idx))
                    color = C_RED if active_prices[col_idx] >= last_close else C_GREEN
                    merged.append((pch, color))
                else:
                    merged.append((" ", None))

            # Reference line (dashed) at ref_row
            if row == ref_row:
                ref_chars = []
                for ci in range(len(merged)):
                    ch, _ = merged[ci]
                    if ch != " ":
                        ref_chars.append((ch, C_YELLOW if ch != " " else C_DARK))
                    else:
                        # Dashed line pattern
                        if ci % 4 < 2:
                            ref_chars.append(("┄", C_YELLOW + DIM))
                        else:
                            ref_chars.append((" ", None))
                merged = ref_chars

            # Build colored chart line
            chart_str = ""
            cur_color = None
            for ch, color in merged:
                if color != cur_color:
                    if color:
                        chart_str += color + C_BG
                    else:
                        chart_str += C_DIM + C_BG
                    cur_color = color
                chart_str += ch
            chart_str += RESET + C_BG

            label_color = C_DIM
            if row == ref_row:
                label_color = C_YELLOW

            line_str = f" {label_color}{left_label}{RESET}{C_BG} {chart_str} {label_color}{right_label}{RESET}{C_BG}"
            out.append(line_str.ljust(term_w))

        # X-axis time labels
        x_label_row = [" "] * chart_w
        for slot_val, label in time_marks:
            if slot_val < n:
                x_pos = slot_to_x(slot_val)
                for li, lc in enumerate(label):
                    if x_pos + li < chart_w:
                        x_label_row[x_pos + li] = lc

        x_str = " " * (y_label_w + 1) + C_DIM + "".join(x_label_row) + RESET + C_BG
        out.append(x_str.ljust(term_w))

        # ── Volume chart ──
        max_vol = max(active_vol) if active_vol and max(active_vol) > 0 else 1
        vol_block_chars = "▁▂▃▄▅▆▇█"

        vol_title = f" {C_DIM}成交量{RESET}{C_BG}"
        out.append(vol_title.ljust(term_w))

        for vh in range(vol_h):
            vol_line = []
            for ci in range(min(chart_w, len(active_vol))):
                bar_idx = int(ci / (chart_w - 1) * (n - 1)) if chart_w > 1 else 0
                bar_idx = max(0, min(n - 1, bar_idx))
                v = active_vol[bar_idx]
                if v <= 0:
                    vol_line.append(" ")
                    continue

                # Map volume to block height
                vol_ratio = v / max_vol
                filled_h = vol_ratio * vol_h
                row_from_top = vol_h - vh  # bottom row = vol_h-1
                if filled_h >= row_from_top:
                    vol_line.append("█")
                elif filled_h >= row_from_top - 1:
                    partial = int((filled_h - row_from_top + 1) * 8)
                    partial = max(0, min(7, partial))
                    vol_line.append(vol_block_chars[partial] if partial > 0 else " ")
                else:
                    vol_line.append(" ")

            # Color the volume line
            colored_vol = ""
            for ci, ch in enumerate(vol_line):
                if ch == " ":
                    colored_vol += " "
                else:
                    bar_idx = int(ci / (chart_w - 1) * (n - 1)) if chart_w > 1 else 0
                    bar_idx = max(0, min(n - 1, bar_idx))
                    color = C_RED if active_prices[bar_idx] >= last_close else C_GREEN
                    colored_vol += color + ch + RESET + C_BG

            vol_str = " " * (y_label_w + 1) + colored_vol
            out.append(vol_str.ljust(term_w))

        # Volume max label
        vol_max_str = f" {C_DIM}{fmt_volume(max_vol):>9}{RESET}{C_BG} {C_DIM}{'─' * chart_w}{RESET}{C_BG}"
        out.append(vol_max_str.ljust(term_w))

        # ── Info bar ──
        q_open = quote.get("open", "-")
        q_high = quote.get("high", "-")
        q_low = quote.get("low", "-")
        q_vol = quote.get("volume", 0)
        q_amt = quote.get("amount", 0)

        open_str = f"{q_open:.2f}" if isinstance(q_open, (int, float)) else "-"
        high_str = f"{q_high:.2f}" if isinstance(q_high, (int, float)) else "-"
        low_str = f"{q_low:.2f}" if isinstance(q_low, (int, float)) else "-"
        vol_str = fmt_volume(q_vol) if isinstance(q_vol, (int, float)) and q_vol else "-"
        amt_str = fmt_amount(q_amt) if isinstance(q_amt, (int, float)) and q_amt else "-"

        info1 = f" {C_DIM}今开{RESET}{C_BG} {C_WHITE}{open_str}{RESET}{C_BG}  {C_DIM}昨收{RESET}{C_BG} {C_WHITE}{last_close:.2f}{RESET}{C_BG}  {C_DIM}最高{RESET}{C_BG} {C_RED}{high_str}{RESET}{C_BG}  {C_DIM}最低{RESET}{C_BG} {C_GREEN}{low_str}{RESET}{C_BG}"
        info2 = f" {C_DIM}成交量{RESET}{C_BG} {C_WHITE}{vol_str}{RESET}{C_BG}  {C_DIM}成交额{RESET}{C_BG} {C_WHITE}{amt_str}{RESET}{C_BG}  {C_DIM}换手率{RESET}{C_BG} {C_WHITE}{quote.get('turnover_rate', '-')}%{RESET}{C_BG}"

        out.append(info1.ljust(term_w))
        out.append(info2.ljust(term_w))

        # ── Output ──
        # Clear screen and move cursor to top
        sys.stdout.write(f"{ESC}2J{ESC}H")
        sys.stdout.write("\n".join(out) + RESET + "\n")

        if refresh_interval <= 0:
            break

        sys.stdout.write(f" {C_DIM}── 每 {refresh_interval}s 自动刷新, Ctrl+C 停止 ──{RESET}\n")
        sys.stdout.flush()
        try:
            time.sleep(refresh_interval)
        except KeyboardInterrupt:
            sys.stdout.write(f"\n{ESC}2J{ESC}H")
            sys.stdout.write(f" {C_DIM}刷新已停止{RESET}\n")
            sys.stdout.flush()
            break


def parse_args():
    symbol = None
    refresh = 0

    i = 1
    while i < len(sys.argv):
        a = sys.argv[i]
        if a in ("--refresh", "-r") and i + 1 < len(sys.argv):
            refresh = int(sys.argv[i + 1])
            i += 2
        elif not a.startswith("-") and symbol is None:
            symbol = a
            i += 1
        else:
            i += 1

    if not symbol:
        print("Usage: snowball kchart <symbol> --period minute [--refresh 30]")
        sys.exit(1)

    return symbol, refresh


def main():
    symbol, refresh = parse_args()
    draw_fenshi(symbol, refresh)


if __name__ == "__main__":
    main()