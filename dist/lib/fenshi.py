#!/usr/bin/env python3
"""
snowball kchart --period minute — Terminal Intraday Minute Chart (分时图)
Usage: snowball kchart <symbol> --period minute [--refresh 30]
"""

import sys
import json
import subprocess
import time
import os
import shutil
from datetime import datetime


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
    """Fetch and parse minute + quote data. Returns dict with parsed fields."""
    raw_minute = run_snowball(["minute", symbol])
    minute_data = json.loads(raw_minute)

    raw_quote = run_snowball(["quote", symbol])
    quote_list = json.loads(raw_quote)
    quote = quote_list[0] if quote_list else {}

    last_close = minute_data.get("last_close") or quote.get("last_close", 0)
    after = minute_data.get("after", [])

    # Build 240-slot arrays
    prices = [None] * 240
    avg_prices = [None] * 240
    # Store raw minute points by slot for volume computation
    slot_data = {}

    for pt in after:
        ts = pt["timestamp"] / 1000
        dt = datetime.fromtimestamp(ts)
        slot = slot_from_time(dt.hour, dt.minute)
        if slot < 0:
            continue
        prices[slot] = pt.get("current")
        avg_prices[slot] = pt.get("avg_price")
        if slot not in slot_data:
            slot_data[slot] = pt

    # Fill forward prices
    last_valid = last_close
    for i in range(240):
        if prices[i] is not None:
            last_valid = prices[i]
        else:
            prices[i] = last_valid

    # Compute per-minute volumes
    # The API gives per-minute volume in the 'volume' field for some points,
    # and cumulative volume_total for the first point (total day volume)
    # Strategy: use the 'volume' field directly when available
    per_minute_vol = [0] * 240
    for slot, pt in slot_data.items():
        vol = pt.get("volume")
        if vol and vol > 0:
            per_minute_vol[slot] = vol

    # If per-minute volumes are all zero (after-hours sparse data),
    # show total volume as a single bar at the last known slot
    if not any(v > 0 for v in per_minute_vol):
        total_vol = quote.get("volume", 0)
        if total_vol and total_vol > 0:
            # Distribute evenly across all active slots
            active_count = len(slot_data)
            if active_count > 0:
                per_bar = total_vol / active_count
                for slot in slot_data:
                    per_minute_vol[slot] = int(per_bar)

    # Find last active slot
    last_slot = 0
    for i in range(239, -1, -1):
        if i in slot_data or per_minute_vol[i] > 0:
            last_slot = i
            break
    if last_slot == 0 and after:
        # Use all 240 slots if we have data
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


def draw_fenshi(symbol, refresh_interval=0):
    import plotext as plt

    while True:
        data = fetch_data(symbol)
        last_close = data["last_close"]
        prices = data["prices"]
        avg_prices = data["avg_prices"]
        per_minute_vol = data["per_minute_vol"]
        last_slot = data["last_slot"]
        quote = data["quote"]
        slot_data = data["slot_data"]

        if not last_close:
            print("No intraday data available.")
            return

        n = last_slot + 1
        active_prices = prices[:n]
        active_avg = avg_prices[:n]
        active_vol = per_minute_vol[:n]

        # Y-axis: 9 price levels, centered on last_close, ±1.80%
        max_pct = 1.80
        step_pct = max_pct / 4  # 0.45%
        step_price = last_close * step_pct / 100
        y_levels = []
        y_labels_left = []
        y_labels_right = []
        for k in range(4, -5, -1):
            p = last_close + k * step_price
            pct = k * step_pct
            y_levels.append(p)
            sign = "+" if pct >= 0 else ""
            y_labels_left.append(f"{p:.2f}")
            y_labels_right.append(f"{sign}{pct:.2f}%")

        # Adjust y-axis range if prices exceed ±1.80%
        actual_max = max(active_prices)
        actual_min = min(active_prices)
        upper_bound = last_close + 4 * step_price
        lower_bound = last_close - 4 * step_price
        while actual_max > upper_bound:
            step_price *= 1.2
            step_pct *= 1.2
            upper_bound = last_close + 4 * step_price
            lower_bound = last_close - 4 * step_price
        while actual_min < lower_bound:
            step_price *= 1.2
            step_pct *= 1.2
            upper_bound = last_close + 4 * step_price
            lower_bound = last_close - 4 * step_price

        if step_price != last_close * max_pct / 100 / 4:
            y_levels = []
            y_labels_left = []
            y_labels_right = []
            for k in range(4, -5, -1):
                p = last_close + k * step_price
                pct = k * step_pct
                y_levels.append(p)
                sign = "+" if pct >= 0 else ""
                y_labels_left.append(f"{p:.2f}")
                y_labels_right.append(f"{sign}{pct:.2f}%")

        def slot_time(s):
            if s < 120:
                mins = s + 30
                h = 9 + mins // 60
                m = mins % 60
            else:
                mins = s - 120
                h = 13 + mins // 60
                m = mins % 60
            return f"{h}:{m:02d}"

        x_vals = list(range(n))

        # X-axis key time labels
        tick_slots = []
        tick_labels = []
        for s, label in [(0, "9:30"), (60, "10:30"), (119, "11:30"),
                         (120, "13:00"), (180, "14:00"), (239, "15:00")]:
            if s < n:
                tick_slots.append(s)
                tick_labels.append(label)

        # ── Draw ──
        plt.clf()
        plt.plotsize(130, 36)
        plt.theme("dark")

        plt.subplots(2, 1)

        # ── Price chart ──
        plt.subplot(1, 1)

        # Baseline at last_close
        plt.hline(last_close)

        # Split price line into red/green segments for continuity
        segments_red = []
        segments_green = []
        cur_x, cur_y, cur_color = [], [], None

        for i in range(n):
            color = "red" if active_prices[i] >= last_close else "green"
            if cur_color is None:
                cur_color = color
            if color != cur_color:
                # Overlap point for continuity
                if cur_color == "red":
                    segments_red.append((cur_x + [x_vals[i]], cur_y + [active_prices[i]]))
                else:
                    segments_green.append((cur_x + [x_vals[i]], cur_y + [active_prices[i]]))
                cur_x = [x_vals[i]]
                cur_y = [active_prices[i]]
                cur_color = color
            else:
                cur_x.append(x_vals[i])
                cur_y.append(active_prices[i])

        if cur_x:
            if cur_color == "red":
                segments_red.append((cur_x, cur_y))
            else:
                segments_green.append((cur_x, cur_y))

        for sx, sy in segments_red:
            plt.plot(sx, sy, color="red+")
        for sx, sy in segments_green:
            plt.plot(sx, sy, color="green+")

        # Average price line
        avg_valid_x = [x_vals[i] for i in range(n) if active_avg[i] is not None]
        avg_valid_y = [active_avg[i] for i in range(n) if active_avg[i] is not None]
        if avg_valid_x:
            plt.plot(avg_valid_x, avg_valid_y, color="yellow", label="均价")

        # Y-axis ticks
        plt.yticks(y_levels, y_labels_left)

        # X-axis ticks
        plt.xticks(tick_slots, tick_labels)

        cur = active_prices[-1]
        chg_val = cur - last_close
        pct_val = chg_val / last_close * 100 if last_close else 0
        sign = "+" if pct_val >= 0 else ""
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        plt.title(f"{symbol}  分时图  {now_str}  {cur:.2f} {sign}{pct_val:.2f}%")

        # ── Volume chart ──
        plt.subplot(2, 1)

        red_vol_x = [x_vals[i] for i in range(n) if active_prices[i] >= last_close and active_vol[i] > 0]
        red_vol_y = [active_vol[i] for i in range(n) if active_prices[i] >= last_close and active_vol[i] > 0]
        green_vol_x = [x_vals[i] for i in range(n) if active_prices[i] < last_close and active_vol[i] > 0]
        green_vol_y = [active_vol[i] for i in range(n) if active_prices[i] < last_close and active_vol[i] > 0]

        if red_vol_x:
            plt.bar(red_vol_x, red_vol_y, color="red+", width=0.8)
        if green_vol_x:
            plt.bar(green_vol_x, green_vol_y, color="green+", width=0.8)

        plt.ylabel("Vol")
        plt.xticks(tick_slots, tick_labels)

        plt.show()

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

        print()
        print(f"  {symbol}  {now_str}")
        print(f"  ┌──────────────────────────────────────────────────────────┐")
        print(f"  │ 最新: {cur:>8.2f}   涨跌: {sign}{chg_val:>7.2f}   涨跌幅: {sign}{pct_val:>6.2f}%      │")
        print(f"  │ 今开: {open_str:>8}   昨收: {last_close:>8.2f}   今高: {high_str:>8}   今低: {low_str:>8} │")
        print(f"  │ 成交量: {vol_str:>6}    成交额: {amt_str:>10}                     │")
        print(f"  └──────────────────────────────────────────────────────────┘")

        if refresh_interval <= 0:
            break

        print(f"  ── 每 {refresh_interval}s 自动刷新, Ctrl+C 停止 ──")
        try:
            time.sleep(refresh_interval)
        except KeyboardInterrupt:
            print("\n  刷新已停止。")
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