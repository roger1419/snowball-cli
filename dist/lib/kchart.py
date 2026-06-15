#!/usr/bin/env python3
"""
snowball kchart — Terminal K-line chart with candlesticks and indicators.
Usage: snowball kchart <symbol> [--period day] [--count 60] [--ma 5,10,20,60]
"""
import sys
from datetime import datetime
from chart_utils import (
    fetch_json, run_snowball, fmt_vol, fmt_amt, fmt_pct,
    C_RED, C_GREEN, C_YELLOW, C_WHITE, C_DIM, C_CYAN, C_MAGENTA, C_ORANGE, C_BLUE,
    RESET, BOLD, DIM, CLEAR,
)


def parse_args():
    symbol = None
    period = "day"
    count = 60
    ma = "5,10,20,60"
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
        print("Usage: snowball kchart <symbol> [--period day|week|month] [--count 60] [--ma 5,10,20,60]")
        sys.exit(1)
    return symbol, period, count, [int(x) for x in ma.split(",")]


def calc_ma(closes, period):
    result = []
    for i in range(len(closes)):
        if i < period - 1:
            result.append(None)
        else:
            window = closes[i - period + 1:i + 1]
            result.append(sum(window) / period)
    return result


def draw_kline(data, ma_periods):
    import plotext as plt

    columns = data.get("column", [])
    items = data.get("item", [])
    if not items:
        print("No K-line data available.")
        return

    ci = {name: i for i, name in enumerate(columns)}

    # Extract arrays
    timestamps = [row[ci["timestamp"]] for row in items]
    opens   = [row[ci["open"]]   for row in items]
    highs   = [row[ci["high"]]   for row in items]
    lows    = [row[ci["low"]]    for row in items]
    closes  = [row[ci["close"]]  for row in items]
    volumes = [row[ci["volume"]] for row in items]
    pcts    = [row[ci["percent"]] for row in items]
    pe_list = [row[ci["pe"]] for row in items]
    pb_list = [row[ci["pb"]] for row in items]
    turnover = [row[ci["turnoverrate"]] for row in items]
    amounts  = [row[ci["amount"]] for row in items]

    dates = [datetime.fromtimestamp(t / 1000).strftime("%d/%m/%Y") for t in timestamps]
    n = len(items)
    sym = data.get("symbol", "")

    # ── Configure plotext ──
    plt.plotsize(125, 38)
    plt.theme("dark")
    plt.subplots(3, 1)

    # ── Panel 1: Candlestick + MA ──
    plt.subplot(1, 1)
    plt.candlestick(
        dates,
        {"Open": opens, "Close": closes, "High": highs, "Low": lows},
        colors=["red+", "green+"]
    )

    # MA lines with stock-app color scheme
    ma_colors = {
        5:  "orange",      # MA5 = orange (similar to stock apps)
        10: "cyan",        # MA10 = cyan
        20: "yellow",      # MA20 = yellow
        30: "violet",      # MA30
        60: "lightgray",   # MA60 = gray
        90: "blue",        # MA90
        120: "magenta",    # MA120
        250: "lightgreen", # MA250 (年线)
    }

    for period in ma_periods:
        if period > n:
            continue
        ma_vals = calc_ma(closes, period)
        valid_x = [dates[i] for i in range(n) if ma_vals[i] is not None]
        valid_y = [ma_vals[i] for i in range(n) if ma_vals[i] is not None]
        clr = ma_colors.get(period, "white")
        plt.plot(valid_x, valid_y, label=f"MA{period}", color=clr)

    first_date = datetime.fromtimestamp(timestamps[0] / 1000).strftime("%Y-%m-%d")
    last_date  = datetime.fromtimestamp(timestamps[-1] / 1000).strftime("%Y-%m-%d")
    plt.title(f"{sym}  K-Line  {first_date} → {last_date}  [{n} bars]")
    plt.ylabel("Price")

    # ── Panel 2: Volume ──
    plt.subplot(2, 1)
    vol_colors = ["green+" if closes[i] >= opens[i] else "red+" for i in range(n)]
    plt.bar(dates, volumes, color=vol_colors, label="Volume", width=0.6)
    plt.ylabel("Volume")

    # ── Panel 3: PE / PB ──
    plt.subplot(3, 1)
    pe_x = [dates[i] for i in range(n) if pe_list[i] is not None]
    pe_y = [pe_list[i] for i in range(n) if pe_list[i] is not None]
    pb_x = [dates[i] for i in range(n) if pb_list[i] is not None]
    pb_y = [pb_list[i] for i in range(n) if pb_list[i] is not None]

    if pe_y:
        plt.plot(pe_x, pe_y, label="PE", color="cyan")
    if pb_y:
        plt.plot(pb_x, pb_y, label="PB", color="yellow")
    plt.ylabel("PE / PB")
    plt.xlabel("Date")
    plt.show()

    # ── Summary panel ──
    cur  = closes[-1]
    o    = opens[-1]
    hi   = highs[-1]
    lo   = lows[-1]
    pct  = pcts[-1]
    vol  = volumes[-1]
    amt  = amounts[-1]
    tr   = turnover[-1]
    pe   = pe_list[-1]
    pb   = pb_list[-1]
    pc   = C_RED if pct >= 0 else C_GREEN
    sign = "+" if pct >= 0 else ""
    green_or_red = "red" if pct >= 0 else "green"

    # Compute trend stats
    if n >= 5:
        ma5_now  = sum(closes[-5:]) / 5
        ma10_now = sum(closes[-10:]) / 10 if n >= 10 else None
        ma20_now = sum(closes[-20:]) / 20 if n >= 20 else None
        ma60_now = sum(closes[-60:]) / 60 if n >= 60 else None
    else:
        ma5_now = ma10_now = ma20_now = ma60_now = None

    # Change-rate brightness
    chg_sign = "▲" if pct >= 0 else "▼"

    print(f"\n  {C_WHITE}{BOLD}{sym}{RESET}  {last_date}")
    print(f"  ┌───────────────────────────────────────────────────────────────┐")
    print(f"  │ {C_WHITE}收盘{RESET} {C_WHITE}{cur:>10.2f}{RESET}    {C_WHITE}涨跌幅{RESET} {pc}{chg_sign} {sign}{pct:>7.2f}%{RESET}                          │")
    print(f"  │ {C_DIM}开盘{RESET} {o:>10.2f}    {C_DIM}最高{RESET}   {C_RED}{hi:>10.2f}{RESET}  {C_DIM}最低{RESET} {C_GREEN}{lo:>10.2f}{RESET}     │")
    print(f"  │ {C_DIM}成交量{RESET} {fmt_vol(vol):>8}    {C_DIM}成交额{RESET} {fmt_amt(amt):>10}                          │")

    pe_str = f"{pe:>8.1f}" if pe is not None else "      N/A"
    pb_str = f"{pb:>6.2f}" if pb is not None else "   N/A"
    tr_str = f"{tr:>6.2f}%" if tr is not None else "   N/A"

    print(f"  │ {C_DIM}换手率{RESET} {tr_str}     {C_DIM}PE{RESET} {pe_str}   {C_DIM}PB{RESET} {pb_str}            │")
    print(f"  └───────────────────────────────────────────────────────────────┘")

    # MA values
    ma_lines = []
    ma_names = {5: C_ORANGE, 10: C_BLUE, 20: C_MAGENTA, 60: C_DIM}
    for period in ma_periods:
        v = calc_ma(closes, period)[-1]
        if v is not None:
            c = ma_names.get(period, C_WHITE)
            ma_lines.append(f"{c}MA{period}{RESET}={v:.2f}")
    if ma_lines:
        print(f"  均线: {'  '.join(ma_lines)}")

    # Price position vs MA
    if ma5_now and ma10_now and ma20_now:
        above_below = []
        for period, val in [(5, ma5_now), (10, ma10_now), (20, ma20_now)]:
            relation = f"{C_RED}↑{RESET}" if cur > val else f"{C_GREEN}↓{RESET}"
            above_below.append(f"MA{period}{relation}")
        print(f"  价格位置: {'  '.join(above_below)}  (vs 均线)")


def main():
    symbol, period, count, ma_periods = parse_args()
    data = fetch_json(["kline", symbol, "--period", period, "--count", str(count)])
    draw_kline(data, ma_periods)


if __name__ == "__main__":
    main()