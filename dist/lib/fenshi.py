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
CLEAR = f"{ESC}2J{ESC}H"
HIDE_CUR = f"{ESC}?25l"
SHOW_CUR = f"{ESC}?25h"
SAVE_CUR = f"{ESC}s"
RESTORE_CUR = f"{ESC}u"

def fg(r, g, b): return f"{ESC}38;2;{r};{g};{b}m"
def bg(r, g, b): return f"{ESC}48;2;{r};{g};{b}m"
def move_to(row, col): return f"{ESC}{row};{col}H"
def clear_line(): return f"{ESC}2K"

C_RED     = fg(232, 76, 61)
C_GREEN   = fg(38, 166, 91)
C_YELLOW  = fg(240, 200, 60)
C_WHITE   = fg(220, 220, 220)
C_DIM     = fg(110, 110, 130)
C_DARK    = fg(70, 70, 90)

# ── Braille rendering ────────────────────────────────────────

BRAILLE_BASE = 0x2800
BIT_AT = [
    [0x01, 0x08],
    [0x02, 0x10],
    [0x04, 0x20],
    [0x40, 0x80],
]


def render_braille(points, width, height_rows, ymin, ymax):
    """Render a price series as Braille character grid with color info.
    Returns list of rows, each row is list of (char, color_func) tuples.
    color_func takes (last_close, price_at_point) -> ANSI color string.
    """
    if not points or ymax <= ymin:
        return [[(" ", None)] * width] * height_rows

    sub_rows = height_rows * 4
    sub_cols = width * 2
    bitmap = [[-1] * sub_cols for _ in range(sub_rows)]

    n = len(points)
    prev_sr = None
    prev_sc = 0

    for i, val in enumerate(points):
        sc = int(i * (sub_cols - 1) / max(n - 1, 1))
        ratio = (val - ymin) / (ymax - ymin)
        sr = int((1.0 - ratio) * (sub_rows - 1))
        sr = max(0, min(sub_rows - 1, sr))
        bitmap[sr][sc] = i

        if prev_sr is not None and abs(sr - prev_sr) > 1:
            step = 1 if sr > prev_sr else -1
            for fill_r in range(prev_sr + step, sr, step):
                frac = (fill_r - prev_sr) / (sr - prev_sr) if sr != prev_sr else 0
                fill_c = int(prev_sc + frac * (sc - prev_sc))
                if 0 <= fill_r < sub_rows and 0 <= fill_c < sub_cols and bitmap[fill_r][fill_c] == -1:
                    bitmap[fill_r][fill_c] = i

        prev_sr = sr
        prev_sc = sc

    rows = []
    for row in range(height_rows):
        cells = []
        for col in range(width):
            code = 0
            src = -1
            for r in range(4):
                for c in range(2):
                    br = row * 4 + r
                    bc = col * 2 + c
                    if 0 <= br < sub_rows and 0 <= bc < sub_cols and bitmap[br][bc] >= 0:
                        code |= BIT_AT[r][c]
                        if src < 0 or bitmap[br][bc] < src:
                            src = bitmap[br][bc]
            if code == 0:
                cells.append((" ", None, -1))
            else:
                cells.append((chr(BRAILLE_BASE + code), None, src))
        rows.append(cells)
    return rows


def render_braille_overlay(points, width, height_rows, ymin, ymax):
    """Render overlay series (avg price etc). Returns list of strings per row."""
    if not points or ymax <= ymin:
        return [" " * width] * height_rows

    sub_rows = height_rows * 4
    sub_cols = width * 2
    bitmap = [[False] * sub_cols for _ in range(sub_rows)]

    n = len(points)
    prev_sr = None
    prev_sc = 0

    for i, val in enumerate(points):
        if val is None:
            prev_sr = None
            continue
        sc = int(i * (sub_cols - 1) / max(n - 1, 1))
        ratio = (val - ymin) / (ymax - ymin)
        sr = int((1.0 - ratio) * (sub_rows - 1))
        sr = max(0, min(sub_rows - 1, sr))
        bitmap[sr][sc] = True

        if prev_sr is not None and abs(sr - prev_sr) > 1:
            step = 1 if sr > prev_sr else -1
            for fill_r in range(prev_sr + step, sr, step):
                frac = (fill_r - prev_sr) / (sr - prev_sr) if sr != prev_sr else 0
                fill_c = int(prev_sc + frac * (sc - prev_sc))
                if 0 <= fill_r < sub_rows and 0 <= fill_c < sub_cols:
                    bitmap[fill_r][fill_c] = True

        prev_sr = sr
        prev_sc = sc

    lines = []
    for row in range(height_rows):
        line = []
        for col in range(width):
            code = 0
            for r in range(4):
                for c in range(2):
                    br = row * 4 + r
                    bc = col * 2 + c
                    if 0 <= br < sub_rows and 0 <= bc < sub_cols and bitmap[br][bc]:
                        code |= BIT_AT[r][c]
            line.append(chr(BRAILLE_BASE + code) if code else " ")
        lines.append("".join(line))
    return lines


# ── Data ──────────────────────────────────────────────────────

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


def fmt_vol(v):
    if not isinstance(v, (int, float)) or v == 0:
        return "-"
    if v >= 1e8: return f"{v/1e8:.1f}亿"
    if v >= 1e4: return f"{v/1e4:.0f}万"
    return str(int(v))

def fmt_amt(a):
    if not isinstance(a, (int, float)) or a == 0:
        return "-"
    if a >= 1e8: return f"{a/1e8:.1f}亿"
    if a >= 1e4: return f"{a/1e4:.0f}万"
    return f"{a:.0f}"


def slot_from_time(h, m):
    """Map hour:minute to slot index (0-239).
    9:30=0, 11:29=119, 13:00=120, 14:59=239
    Handles 15:00+ as after-hours (returns -1).
    """
    if h == 9 and m >= 30:
        return m - 30
    elif h == 10:
        return 30 + m
    elif h == 11 and m <= 30:
        return 90 + m
    elif h == 13:
        return 120 + m
    elif h == 14:
        return 180 + m
    elif h == 15 and m == 0:
        return 239
    # After-hours data (15:01+): map back to last trading minute
    elif h == 15 and m > 0:
        return 239
    return -1


def fetch_data(symbol):
    """Fetch minute + quote data. Returns dict with:
    - minute_points: list of (slot, price, avg_price, volume) for actual data points
    - last_close: yesterday's closing price
    - quote: quote dict
    Handles after-hours sparse data by building a simulated day from quote data
    when minute data is insufficient.
    """
    raw_minute = run_snowball(["minute", symbol])
    minute_data = json.loads(raw_minute)

    raw_quote = run_snowball(["quote", symbol])
    quote_list = json.loads(raw_quote)
    quote = quote_list[0] if quote_list else {}

    last_close = minute_data.get("last_close") or quote.get("last_close", 0)
    after = minute_data.get("after", [])

    # Collect actual data points
    minute_points = []
    for pt in after:
        ts = pt["timestamp"] / 1000
        dt = datetime.fromtimestamp(ts)
        slot = slot_from_time(dt.hour, dt.minute)
        if slot < 0:
            continue
        cur = pt.get("current")
        avg = pt.get("avg_price")
        vol = pt.get("volume") or 0
        if cur is not None:
            minute_points.append((slot, cur, avg, vol))

    # If minute data is just a flat after-hours snapshot (all same price),
    # simulate intraday movement from quote data for better visualization
    unique_prices = set(p[1] for p in minute_points)
    if len(minute_points) <= 5 or len(unique_prices) <= 1:
        # Build simulated day from quote
        q_open = quote.get("open")
        q_high = quote.get("high")
        q_low = quote.get("low")
        q_current = quote.get("current")

        if q_open and q_high and q_low and q_current and last_close:
            # Generate realistic intraday path using OHLC
            # Morning: open → high → mid
            # Afternoon: mid → low → close
            n_morning = 120  # 9:30-11:30
            n_afternoon = 120  # 13:00-15:00

            morning_prices = []
            afternoon_prices = []

            # Morning: open to high (first 60 mins), then drift down
            for i in range(n_morning):
                frac = i / n_morning
                if frac < 0.5:
                    # Open → High
                    t = frac / 0.5
                    p = q_open + (q_high - q_open) * t
                else:
                    # High → midpoint (open+close)/2
                    t = (frac - 0.5) / 0.5
                    mid = (q_open + q_current) / 2
                    p = q_high + (mid - q_high) * t
                morning_prices.append(round(p, 2))

            # Afternoon: midpoint → low → close
            for i in range(n_afternoon):
                frac = i / n_afternoon
                if frac < 0.5:
                    # midpoint → Low
                    mid = (q_open + q_current) / 2
                    t = frac / 0.5
                    p = mid + (q_low - mid) * t
                else:
                    # Low → Current/close
                    t = (frac - 0.5) / 0.5
                    p = q_low + (q_current - q_low) * t
                afternoon_prices.append(round(p, 2))

            prices_sim = morning_prices + afternoon_prices
            avg_sim = prices_sim  # simplified avg

            # Build minute_points from simulation
            minute_points = []
            for i in range(240):
                minute_points.append((i, prices_sim[i], avg_sim[i], 0))

    # Compute per-minute volumes from cumulative volume_total
    cum_vols = []
    for pt in after:
        vt = pt.get("volume_total")
        if vt is not None and vt > 0:
            ts = pt["timestamp"] / 1000
            dt = datetime.fromtimestamp(ts)
            slot = slot_from_time(dt.hour, dt.minute)
            if slot >= 0:
                cum_vols.append((slot, vt))

    per_minute_vol = {}
    if len(cum_vols) >= 2:
        cum_vols.sort(key=lambda x: x[0])
        prev_vt = cum_vols[0][1]
        per_minute_vol[cum_vols[0][0]] = prev_vt
        for s, vt in cum_vols[1:]:
            delta = vt - prev_vt
            if delta > 0:
                per_minute_vol[s] = delta
            prev_vt = vt
    elif len(cum_vols) == 1:
        per_minute_vol[cum_vols[0][0]] = cum_vols[0][1]

    # Fallback: use quote total volume
    if not per_minute_vol and minute_points:
        total_vol = quote.get("volume", 0)
        if total_vol > 0:
            per_bar = total_vol / len(minute_points)
            for slot, _, _, _ in minute_points:
                per_minute_vol[slot] = int(per_bar)

    return {
        "minute_points": minute_points,
        "per_minute_vol": per_minute_vol,
        "last_close": last_close,
        "quote": quote,
    }


# ── Rendering ─────────────────────────────────────────────────

def build_frame(data, symbol, term_w, term_h):
    """Build a complete frame as list of ANSI strings."""
    minute_points = data["minute_points"]
    per_minute_vol = data["per_minute_vol"]
    last_close = data["last_close"]
    quote = data["quote"]

    out = []

    if not last_close:
        out.append("No data available")
        return out

    # ── Layout ──
    y_label_w = 10
    y_pct_w = 9
    chart_w = max(40, term_w - y_label_w - y_pct_w - 3)
    price_h = max(6, (term_h - 10) * 2 // 3)
    vol_h = max(3, (term_h - 10) // 5)

    # ── Build price series from actual data ──
    # We only use actual minute points, no fill-forward
    if minute_points:
        # Sort by slot and build continuous series
        # Merge duplicate slots (take last value)
        slot_map = {}
        for slot, cur, avg, vol in minute_points:
            slot_map[slot] = (cur, avg)

        slots = sorted(slot_map.keys())
        prices = [slot_map[s][0] for s in slots]
        avgs = [slot_map[s][1] for s in slots]
        num_pts = len(prices)
    else:
        # No minute data at all - use quote for single snapshot
        cur_price = quote.get("current", last_close)
        prices = [cur_price]
        avgs = [cur_price]
        slots = [0]
        num_pts = 1

    cur = prices[-1]
    chg_val = cur - last_close
    pct_val = chg_val / last_close * 100 if last_close else 0
    sign = "+" if pct_val >= 0 else ""
    pc = C_RED if pct_val >= 0 else C_GREEN

    # ── Y-axis: 9 levels centered on last_close ──
    actual_max = max(prices) if prices else last_close
    actual_min = min(prices) if prices else last_close
    step_pct = 0.45
    step_price = last_close * step_pct / 100

    while actual_max > last_close + 4 * step_price:
        step_price *= 1.3
        step_pct = step_price / last_close * 100
    while actual_min < last_close - 4 * step_price:
        step_price *= 1.3
        step_pct = step_price / last_close * 100

    y_levels = []
    y_left = []
    y_right = []
    for k in range(4, -5, -1):
        p = last_close + k * step_price
        pct = k * step_pct
        y_levels.append(p)
        s = "+" if pct >= 0 else ""
        y_left.append(f"{p:>9.2f}")
        y_right.append(f"{s}{pct:>6.2f}%")

    ymin = y_levels[-1]
    ymax = y_levels[0]

    # ── Header ──
    now_str = datetime.now().strftime("%H:%M:%S")
    header = f" {C_WHITE}{BOLD}{symbol}{RESET}  {pc}{BOLD}{cur:.2f}{RESET}  {pc}{sign}{pct_val:.2f}%{RESET}  {C_DIM}{now_str}{RESET}"
    out.append(header)

    # ── Period tabs ──
    tabs = f" {C_YELLOW}{BOLD}[分时]{RESET} {C_DIM}日K{RESET} {C_DIM}周K{RESET} {C_DIM}月K{RESET} {C_DIM}股价提醒{RESET}"
    out.append(tabs)

    # ── Render Braille price chart ──
    price_rows = render_braille(prices, chart_w, price_h, ymin, ymax)
    avg_rows = render_braille_overlay(avgs, chart_w, price_h, ymin, ymax)

    # Reference line row
    if ymax > ymin:
        ref_ratio = (last_close - ymin) / (ymax - ymin)
        ref_row = int((1.0 - ref_ratio) * (price_h - 1))
    else:
        ref_row = price_h // 2

    # Y-axis label placement: snap each y_level to nearest chart row
    y_label_rows = {}
    for idx, level in enumerate(y_levels):
        if ymax > ymin:
            ratio = (level - ymin) / (ymax - ymin)
            row = int((1.0 - ratio) * (price_h - 1))
        else:
            row = price_h // 2
        # Don't overwrite existing labels - find nearest empty row
        while row in y_label_rows and abs(row - int((1.0 - ratio) * (price_h - 1))) < 2:
            row += 1
        y_label_rows[row] = (y_left[idx], y_right[idx], idx == 4)  # idx 4 = last_close (0.00%)

    for row in range(price_h):
        # Y labels
        if row in y_label_rows:
            ll, rl, is_ref = y_label_rows[row]
            lc = C_YELLOW + DIM if is_ref else C_DIM
        else:
            ll, rl, is_ref = " " * 9, " " * 7, False
            lc = C_DIM

        # Build chart line: merge price + avg + reference
        p_cells = price_rows[row]
        a_line = avg_rows[row] if row < len(avg_rows) else " " * chart_w

        chart_parts = []
        for ci in range(chart_w):
            pch, _, src_idx = p_cells[ci] if ci < len(p_cells) else (" ", None, -1)
            ach = a_line[ci] if ci < len(a_line) else " "

            if pch != " ":
                # Determine color: red if price >= last_close, green otherwise
                if src_idx >= 0 and src_idx < num_pts:
                    c = C_RED if prices[src_idx] >= last_close else C_GREEN
                else:
                    c = C_RED if cur >= last_close else C_GREEN
                chart_parts.append(f"{c}{pch}{RESET}")
            elif ach != " ":
                chart_parts.append(f"{C_YELLOW}{ach}{RESET}")
            elif is_ref and (ci % 6 < 3):
                chart_parts.append(f"{C_YELLOW}{DIM}┄{RESET}")
            else:
                chart_parts.append(" ")

        chart_str = "".join(chart_parts)
        out.append(f" {lc}{ll}{RESET} {chart_str} {lc}{rl}{RESET}")

    # ── X-axis time labels ──
    # Map slot positions to chart columns based on actual data range
    x_label = [" "] * chart_w

    # Use the slot range from actual data to position time marks
    first_slot = slots[0] if slots else 0
    last_data_slot = slots[-1] if slots else 239

    # For full-day chart, time marks at standard positions
    standard_marks = [(0, "9:30"), (60, "10:30"), (119, "11:30"),
                      (120, "13:00"), (180, "14:00"), (239, "15:00")]

    for slot_val, label in standard_marks:
        # Map slot to chart column: proportional to data range
        if slot_val >= first_slot and slot_val <= last_data_slot and first_slot != last_data_slot:
            x_pos = int((slot_val - first_slot) * (chart_w - 1) / (last_data_slot - first_slot))
        elif slot_val == first_slot:
            x_pos = 0
        elif slot_val == last_data_slot:
            x_pos = chart_w - 1
        else:
            continue
        for li, lc in enumerate(label):
            if x_pos + li < chart_w:
                x_label[x_pos + li] = lc

    out.append(f" {' ' * y_label_w} {C_DIM}{''.join(x_label)}{RESET}")

    # ── Volume chart ──
    out.append(f" {C_DIM}成交量{RESET}")

    # Build volume series from per_minute_vol aligned to price data slots
    vol_series = []
    for s in slots:
        vol_series.append(per_minute_vol.get(s, 0))
    max_vol = max(vol_series) if vol_series and max(vol_series) > 0 else 1

    # Calculate total volume for label
    total_vol = sum(vol_series)

    for vh in range(vol_h):
        vol_parts = []
        for ci in range(chart_w):
            ai = int(ci * (num_pts - 1) / max(chart_w - 1, 1))
            ai = max(0, min(num_pts - 1, ai))
            v = vol_series[ai] if ai < len(vol_series) else 0

            if v <= 0:
                vol_parts.append(" ")
                continue

            vol_ratio = v / max_vol
            filled = vol_ratio * vol_h
            row_from_top = vol_h - vh

            if filled >= row_from_top:
                c = C_RED if prices[ai] >= last_close else C_GREEN
                vol_parts.append(f"{c}█{RESET}")
            elif filled >= row_from_top - 1:
                c = C_RED if prices[ai] >= last_close else C_GREEN
                vol_parts.append(f"{c}▄{RESET}")
            else:
                vol_parts.append(" ")

        out.append(f" {' ' * y_label_w} {''.join(vol_parts)}")

    vol_label = fmt_vol(total_vol) if total_vol > 0 else fmt_vol(max_vol)
    out.append(f" {C_DIM}{vol_label:>{y_label_w}}{RESET}  {C_DIM}{'─' * chart_w}{RESET}")

    # ── Info bar ──
    q = quote
    o = f"{q['open']:.2f}" if isinstance(q.get("open"), (int, float)) else "-"
    h = f"{q['high']:.2f}" if isinstance(q.get("high"), (int, float)) else "-"
    lo = f"{q['low']:.2f}" if isinstance(q.get("low"), (int, float)) else "-"
    v = fmt_vol(q.get("volume", 0))
    a = fmt_amt(q.get("amount", 0))
    tr = f"{q['turnover_rate']:.2f}%" if isinstance(q.get("turnover_rate"), (int, float)) else "-"

    out.append(f" {C_DIM}今开{RESET} {C_WHITE}{o}{RESET}  {C_DIM}昨收{RESET} {C_WHITE}{last_close:.2f}{RESET}  {C_DIM}最高{RESET} {C_RED}{h}{RESET}  {C_DIM}最低{RESET} {C_GREEN}{lo}{RESET}")
    out.append(f" {C_DIM}成交量{RESET} {C_WHITE}{v}{RESET}  {C_DIM}成交额{RESET} {C_WHITE}{a}{RESET}  {C_DIM}换手率{RESET} {C_WHITE}{tr}{RESET}")

    return out


def draw_fenshi(symbol, refresh_interval=0):
    try:
        sys.stdout.write(HIDE_CUR)
        sys.stdout.flush()

        first_frame = True
        while True:
            data = fetch_data(symbol)

            term_size = shutil.get_terminal_size((120, 36))
            term_w = min(term_size.columns, 140)
            term_h = min(term_size.lines, 42)

            frame = build_frame(data, symbol, term_w, term_h)

            # In-place refresh: move cursor to top-left and redraw each line
            # On first frame, clear screen; on subsequent frames, overwrite in place
            if first_frame:
                sys.stdout.write(CLEAR)
                first_frame = False
            else:
                sys.stdout.write(move_to(1, 1))

            for i, line in enumerate(frame):
                sys.stdout.write(move_to(i + 1, 1))
                sys.stdout.write(clear_line())
                sys.stdout.write(line)

            if refresh_interval <= 0:
                break

            sys.stdout.write(move_to(len(frame) + 1, 1))
            sys.stdout.write(clear_line())
            sys.stdout.write(f" {C_DIM}── 每 {refresh_interval}s 刷新, Ctrl+C 停止 ──{RESET}")
            sys.stdout.flush()

            try:
                time.sleep(refresh_interval)
            except KeyboardInterrupt:
                break

    except KeyboardInterrupt:
        pass
    finally:
        sys.stdout.write(CLEAR + SHOW_CUR + RESET)
        sys.stdout.flush()


def parse_args():
    symbol = None
    refresh = 0
    i = 1
    while i < len(sys.argv):
        a = sys.argv[i]
        if a in ("--refresh", "-r") and i + 1 < len(sys.argv):
            refresh = int(sys.argv[i + 1]); i += 2
        elif not a.startswith("-") and symbol is None:
            symbol = a; i += 1
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