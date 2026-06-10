#!/usr/bin/env python3
"""
snowball kchart — Terminal K-line chart with indicators
Usage: snowball kchart <symbol> [--period day] [--count 60] [--ma 5,10,20]
"""

import sys
import json
import subprocess
from datetime import datetime

def run_snowball(args):
    import shutil, os
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

def parse_args():
    symbol = None
    period = "day"
    count = 60
    ma = "5,10,20"

    i = 1
    while i < len(sys.argv):
        a = sys.argv[i]
        if a in ("--period", "-p") and i + 1 < len(sys.argv):
            period = sys.argv[i + 1]; i += 2
        elif a in ("--count", "-c") and i + 1 < len(sys.argv):
            count = int(sys.argv[i + 1]); i += 2
        elif a in ("--ma", "-m") and i + 1 < len(sys.argv):
            ma = sys.argv[i + 1]; i += 2
        elif not a.startswith("-") and symbol is None:
            symbol = a; i += 1
        else:
            i += 1

    if not symbol:
        print("Usage: snowball kchart <symbol> [--period day] [--count 60] [--ma 5,10,20]")
        sys.exit(1)

    ma_periods = [int(x) for x in ma.split(",")]
    return symbol, period, count, ma_periods

def calc_ma(closes, period):
    result = []
    for i in range(len(closes)):
        if i < period - 1:
            result.append(None)
        else:
            result.append(sum(closes[i - period + 1:i + 1]) / period)
    return result

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

def draw_kline(data, ma_periods):
    import plotext as plt

    columns = data.get("column", [])
    items = data.get("item", [])

    if not items:
        print("No K-line data available.")
        return

    col_idx = {name: i for i, name in enumerate(columns)}

    timestamps = [row[col_idx["timestamp"]] for row in items]
    opens = [row[col_idx["open"]] for row in items]
    highs = [row[col_idx["high"]] for row in items]
    lows = [row[col_idx["low"]] for row in items]
    closes = [row[col_idx["close"]] for row in items]
    volumes = [row[col_idx["volume"]] for row in items]
    pcts = [row[col_idx["percent"]] for row in items]
    turnover_rates = [row[col_idx["turnoverrate"]] for row in items]
    amounts = [row[col_idx["amount"]] for row in items]
    pe_list = [row[col_idx["pe"]] for row in items]
    pb_list = [row[col_idx["pb"]] for row in items]

    dates = [datetime.fromtimestamp(t / 1000).strftime("%d/%m/%Y") for t in timestamps]
    n = len(items)

    plt.plotsize(130, 40)
    plt.theme("dark")

    # ── Subplot 1: Candlestick + MA ──
    plt.subplots(3, 1)
    plt.subplot(1, 1)

    # Native candlestick chart
    plt.candlestick(
        dates,
        {"Open": opens, "Close": closes, "High": highs, "Low": lows},
        colors=["red+", "green+"]
    )

    # Moving averages (use numeric x for MA lines, skip date alignment issues)
    ma_colors = ["cyan", "yellow", "magenta", "white", "blue"]
    for mi, period in enumerate(ma_periods):
        if period > n:
            continue
        ma_vals = calc_ma(closes, period)
        valid_x = [dates[i] for i in range(n) if ma_vals[i] is not None]
        valid_y = [ma_vals[i] for i in range(n) if ma_vals[i] is not None]
        clr = ma_colors[mi % len(ma_colors)]
        plt.plot(valid_x, valid_y, label=f"MA{period}", color=clr)

    plt.title(f"{data.get('symbol', '')}  K-Line  |  {dates[0]} ~ {dates[-1]}  |  {n} bars")
    plt.ylabel("Price")

    # ── Subplot 2: Volume ──
    plt.subplot(2, 1)
    vol_colors = ["green+" if closes[i] >= opens[i] else "red+" for i in range(n)]
    plt.bar(dates, volumes, color=vol_colors, label="Volume", width=0.6)
    plt.ylabel("Vol")

    # ── Subplot 3: PE/PB ──
    plt.subplot(3, 1)
    valid_pe_x = [dates[i] for i in range(n) if pe_list[i] is not None]
    valid_pe_y = [pe_list[i] for i in range(n) if pe_list[i] is not None]
    valid_pb_x = [dates[i] for i in range(n) if pb_list[i] is not None]
    valid_pb_y = [pb_list[i] for i in range(n) if pb_list[i] is not None]

    if valid_pe_y:
        plt.plot(valid_pe_x, valid_pe_y, label="PE", color="cyan")
    if valid_pb_y:
        plt.plot(valid_pb_x, valid_pb_y, label="PB", color="yellow")

    plt.ylabel("PE/PB")
    plt.xlabel("Date")

    plt.show()

    # ── Summary info ──
    print()
    sym = data.get("symbol", "")
    print(f"  {sym}  {dates[-1]}")
    print(f"  ┌──────────────────────────────────────────────────────────┐")
    print(f"  │ 收盘: {closes[-1]:>10.2f}   涨跌幅: {pcts[-1]:>+7.2f}%                 │")
    print(f"  │ 开盘: {opens[-1]:>10.2f}   最高:   {highs[-1]:>10.2f}  最低: {lows[-1]:>10.2f} │")
    print(f"  │ 成交量: {fmt_volume(volumes[-1]):>8}   成交额: {fmt_amount(amounts[-1]):>10}        │")
    pe_str = f"{pe_list[-1]:>10.1f}" if pe_list[-1] is not None else "       N/A"
    pb_str = f"{pb_list[-1]:>8.2f}" if pb_list[-1] is not None else "     N/A"
    print(f"  │ 换手率: {turnover_rates[-1]:>7.2f}%   PE:{pe_str}  PB:{pb_str} │")
    print(f"  └──────────────────────────────────────────────────────────┘")

    ma_strs = []
    for period in ma_periods:
        ma_vals = calc_ma(closes, period)
        val = ma_vals[-1]
        if val is not None:
            ma_strs.append(f"MA{period}={val:.2f}")
    if ma_strs:
        print(f"  均线: {' | '.join(ma_strs)}")

def main():
    symbol, period, count, ma_periods = parse_args()

    raw = run_snowball(["kline", symbol, "--period", period, "--count", str(count)])
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        print("Failed to parse K-line data:", file=sys.stderr)
        print(raw[:200], file=sys.stderr)
        sys.exit(1)

    draw_kline(data, ma_periods)

if __name__ == "__main__":
    main()
