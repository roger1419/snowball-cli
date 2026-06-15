#!/usr/bin/env python3
"""
snowball kchart --period minute — Terminal Intraday Minute Chart (分时图)
Braille point-rendering with trace-width progress, inspired by glint.
Usage: snowball kchart <symbol> --period minute [--refresh 30]
"""
import sys
import time
import shutil
import json
from datetime import datetime
from chart_utils import (
    run_snowball, fetch_json, fmt_vol, fmt_amt,
    braille_points, bitmap_to_braille, braille_bool_overlay,
    slot_from_time, compute_trace_width,
    C_RED, C_GREEN, C_YELLOW, C_WHITE, C_DIM, C_BG,
    RESET, BOLD, DIM, CLEAR, HIDE_CUR, SHOW_CUR,
    move_to, clear_line,
)


def fetch_intraday(symbol):
    """Fetch minute and quote data. Builds 240-point series.
    Falls back to OHLC-simulated path when minute data is sparse (after hours)."""
    minute_data = fetch_json(["minute", symbol])
    quote_data  = fetch_json(["quote", symbol])
    quote = quote_data[0] if quote_data else {}
    last_close = minute_data.get("last_close") or quote.get("last_close", 0)

    # API returns two fields: "items" (intraday minutes during trading)
    # and "after" (sparse after-hours snapshots). Use items as primary source.
    source = minute_data.get("items") or minute_data.get("after") or []

    # Collect per-slot data points
    minute_pts = []
    for pt in source:
        ts = pt["timestamp"] / 1000
        dt = datetime.fromtimestamp(ts)
        slot = slot_from_time(dt.hour, dt.minute)
        if slot < 0: continue
        cur = pt.get("current")
        if cur is not None:
            minute_pts.append((slot, cur, pt.get("avg_price"), pt.get("volume") or 0))

    # If data is sparse/flat, simulate from OHLC
    unique = set(p[1] for p in minute_pts)
    if len(minute_pts) <= 5 or len(unique) <= 1:
        o, hi, lo, cur = quote.get("open"), quote.get("high"), quote.get("low"), quote.get("current")
        if all(v is not None for v in [o, hi, lo, cur]) and last_close:
            pts = _simulate_path(o, hi, lo, cur)
            minute_pts = [(i, pts[i], pts[i], 0) for i in range(240)]

    # Build per-minute volumes from cumulative totals
    cum = []
    for pt in source:
        vt = pt.get("volume_total")
        if vt is not None and vt > 0:
            ts = pt["timestamp"] / 1000
            dt = datetime.fromtimestamp(ts)
            slot = slot_from_time(dt.hour, dt.minute)
            if slot >= 0: cum.append((slot, vt))

    per_vol = {}
    if len(cum) >= 2:
        cum.sort(key=lambda x: x[0])
        pv = cum[0][1]
        per_vol[cum[0][0]] = pv
        for s, vt in cum[1:]:
            d = vt - pv
            if d > 0: per_vol[s] = d
            pv = vt
    elif len(cum) == 1:
        per_vol[cum[0][0]] = cum[0][1]

    if not per_vol and minute_pts:
        tot = quote.get("volume", 0)
        if tot > 0:
            bar = tot / len(minute_pts)
            per_vol = {slot: int(bar) for slot, _, _, _ in minute_pts}

    return {"minute_pts": minute_pts, "per_vol": per_vol, "last_close": last_close, "quote": quote}


def _simulate_path(o, hi, lo, cur):
    """Build 240-point intraday path from OHLC snapshot (after-hours fallback)."""
    pts = []
    for i in range(120):
        frac = i / 120
        if frac < 0.5:
            pts.append(round(o + (hi - o) * frac / 0.5, 2))
        else:
            mid = (o + cur) / 2
            pts.append(round(hi + (mid - hi) * (frac - 0.5) / 0.5, 2))
    for i in range(120):
        frac = i / 120
        mid = (o + cur) / 2
        if frac < 0.5:
            pts.append(round(mid + (lo - mid) * frac / 0.5, 2))
        else:
            pts.append(round(lo + (cur - lo) * (frac - 0.5) / 0.5, 2))
    return pts


def build_frame(data, symbol):
    """Build complete rendering frame as ANSI strings."""
    pts  = data["minute_pts"]
    pv   = data["per_vol"]
    lc   = data["last_close"]
    quot = data["quote"]

    if not lc:
        return ["No data"]

    term = shutil.get_terminal_size((120, 36))
    tw = min(term.columns, 140)
    th = min(term.lines, 42)

    ylw = 8
    cw  = max(40, tw - ylw - 2)
    ph  = max(6, (th - 9) * 3 // 4)
    vh  = max(3, (th - 9) // 5)

    # Build price/avg arrays from slot data
    sm = {}; [sm.update({s: (p, a)}) for s, p, a, _ in pts]
    slots = sorted(sm.keys())
    prices = [sm[s][0] for s in slots]
    avgs   = [sm[s][1] for s in slots]
    np_     = len(prices)

    cur = prices[-1]
    chg = cur - lc
    pc_val = chg / lc * 100 if lc else 0
    sign = "+" if pc_val >= 0 else ""
    pc = C_RED if pc_val >= 0 else C_GREEN

    # Y range with padding
    mx = max(prices); mn = min(prices)
    pad = (mx - mn) * 0.05 if mx != mn else 1
    ymin = mn - pad; ymax = mx + pad
    if ymax <= ymin:
        ymax = lc * 1.02; ymin = lc * 0.98

    # Trace width: use time-based proportion during trading, full-width after hours
    now_dt = datetime.now()
    is_trading = (
        now_dt.weekday() < 5 and (
            (9 <= now_dt.hour < 12 and (now_dt.hour > 9 or now_dt.minute >= 30)) or
            (13 <= now_dt.hour < 15)
        )
    )
    trace_w = compute_trace_width(cw, now_dt) if is_trading else cw

    # ── Header ──
    now = datetime.now().strftime("%H:%M:%S")
    chg_s = f"{sign}{chg:.2f} ({sign}{pc_val:.2f}%)"
    out = [f" {C_WHITE}{BOLD}{symbol}{RESET}  {pc}{BOLD}{cur:.2f}{RESET}  {pc}{chg_s}{RESET}  {C_DIM}{now}{RESET}",
           f" {C_YELLOW}{BOLD}[分时]{RESET} {C_DIM}日K{RESET} {C_DIM}周K{RESET} {C_DIM}月K{RESET} {C_DIM}股价提醒{RESET}"]

    # ── Braille rendering ──
    bmp, sr, sc = braille_points(prices, trace_w, ph, ymin, ymax)
    p_rows = bitmap_to_braille(bmp, sr, sc, ph, trace_w)
    a_rows = braille_bool_overlay(avgs, trace_w, ph, ymin, ymax)

    # Reference line
    if ymax > ymin:
        ref_row = int((1.0 - (lc - ymin) / (ymax - ymin)) * (ph - 1))
    else:
        ref_row = ph // 2

    # Y-axis labels
    fracs = [0.0, 0.25, 0.5, 0.75, 1.0] if ph >= 7 else [0.0, 0.5, 1.0]
    ymap = {}
    for f in fracs:
        row = int(f * (ph - 1))
        v = ymax - f * (ymax - ymin)
        ymap[row] = (f"{v:>7.2f} ", abs(v - lc) < (ymax - ymin) * 0.01)
    if ref_row not in ymap:
        ymap[ref_row] = (f"{lc:>7.2f} ", True)

    for row in range(ph):
        lbl, is_ref = ymap.get(row, (" " * ylw, False))
        lc2 = C_YELLOW + DIM if is_ref else C_DIM

        parts = []
        for ci in range(cw):
            if ci < trace_w:
                pch, src = p_rows[row][ci] if ci < len(p_rows[row]) else (" ", -1)
                ach = a_rows[row][ci] if ci < len(a_rows[row]) else " "
                if pch != " ":
                    c = C_RED if (src >= 0 and src < np_ and prices[src] >= lc) else (C_GREEN if src >= 0 else pc)
                    parts.append(f"{c}{pch}{RESET}")
                elif not is_ref and ach != " ":
                    parts.append(f"{C_YELLOW}{ach}{RESET}")
                elif is_ref and ci % 5 < 3:
                    parts.append(f"{C_YELLOW}{DIM}┄{RESET}")
                else:
                    parts.append(" ")
            else:
                parts.append(f"{C_YELLOW}{DIM}┄{RESET}" if (is_ref and ci % 5 < 3) else " ")
        out.append(f" {lc2}{lbl}{RESET}{''.join(parts)}")

    # X-axis time labels: show all 6 key time marks positioned across full chart_w.
    # Even during trading hours, future time labels serve as reference points.
    xl = [" "] * cw
    # Use "11:30/13:00" combined label — slots 119/120 are adjacent (lunch gap)
    all_marks = [(0, "9:30"), (60, "10:30"), (119, "11:30/13:00"), (180, "14:00"), (239, "15:00")]

    for sv, lb in all_marks:
        xp = int(sv * (cw - 1) / 239)
        xp = max(0, min(cw - len(lb), xp))
        for li, ch in enumerate(lb):
            pos = xp + li
            if pos < cw:
                xl[pos] = ch
    out.append(f" {' ' * ylw}{C_DIM}{''.join(xl)}{RESET}")

    # ── Volume ──
    out.append(f" {C_DIM}成交量{RESET}")
    vs = [pv.get(s, 0) for s in slots]
    mv = max(vs) if vs and max(vs) > 0 else 1
    tv = sum(vs)

    for vh_ in range(vh):
        vp = []
        label_w = trace_w if is_trading else cw
        for ci in range(label_w):
            ai = int(ci * (np_ - 1) / max(label_w - 1, 1)); ai = max(0, min(np_ - 1, ai))
            v = vs[ai] if ai < len(vs) else 0
            if v <= 0: vp.append(" "); continue
            r = v / mv; fh = r * vh
            if fh >= vh - vh_:
                c = C_RED if prices[ai] >= lc else C_GREEN
                vp.append(f"{c}█{RESET}")
            elif fh >= vh - vh_ - 1:
                c = C_RED if prices[ai] >= lc else C_GREEN
                vp.append(f"{c}▄{RESET}")
            else:
                vp.append(" ")
        # Pad remaining chart width
        vp += [" "] * (cw - label_w)
        out.append(f" {' ' * ylw}{''.join(vp)}")

    vl = fmt_vol(tv) if tv > 0 else fmt_vol(mv)
    out.append(f" {C_DIM}{vl:>{ylw}}{RESET}{C_DIM}{'─' * cw}{RESET}")

    # ── Info bar ──
    q = quot
    o  = f"{q['open']:.2f}"  if isinstance(q.get("open"), (int, float)) else "-"
    h  = f"{q['high']:.2f}"  if isinstance(q.get("high"), (int, float)) else "-"
    l  = f"{q['low']:.2f}"   if isinstance(q.get("low"), (int, float)) else "-"
    v  = fmt_vol(q.get("volume", 0))
    a  = fmt_amt(q.get("amount", 0))
    tr = f"{q['turnover_rate']:.2f}%" if isinstance(q.get("turnover_rate"), (int, float)) else "-"

    out.append(f" {C_DIM}今开{RESET} {C_WHITE}{o}{RESET}  {C_DIM}昨收{RESET} {C_WHITE}{lc:.2f}{RESET}  {C_DIM}最高{RESET} {C_RED}{h}{RESET}  {C_DIM}最低{RESET} {C_GREEN}{l}{RESET}")
    out.append(f" {C_DIM}成交量{RESET} {C_WHITE}{v}{RESET}  {C_DIM}成交额{RESET} {C_WHITE}{a}{RESET}  {C_DIM}换手率{RESET} {C_WHITE}{tr}{RESET}")
    return out


def draw_fenshi(symbol, refresh=0):
    try:
        sys.stdout.write(HIDE_CUR); sys.stdout.flush()
        first = True
        while True:
            data = fetch_intraday(symbol)
            frame = build_frame(data, symbol)

            if first:
                sys.stdout.write(CLEAR); first = False
            else:
                sys.stdout.write(move_to(1, 1))

            for i, line in enumerate(frame):
                sys.stdout.write(move_to(i + 1, 1))
                sys.stdout.write(clear_line())
                sys.stdout.write(C_BG + line + RESET)

            if refresh <= 0: break
            sys.stdout.write(move_to(len(frame) + 1, 1))
            sys.stdout.write(clear_line())
            sys.stdout.write(f" {C_DIM}── 每 {refresh}s 刷新, Ctrl+C 停止 ──{RESET}")
            sys.stdout.flush()
            try:
                time.sleep(refresh)
            except KeyboardInterrupt:
                break
    except KeyboardInterrupt: pass
    finally:
        sys.stdout.write(CLEAR + SHOW_CUR + RESET); sys.stdout.flush()


def parse_args():
    sym, refresh = None, 0
    i = 1
    while i < len(sys.argv):
        a = sys.argv[i]
        if a in ("--refresh","-r") and i+1 < len(sys.argv): refresh = int(sys.argv[i+1]); i+=2
        elif not a.startswith("-") and sym is None: sym = a; i+=1
        else: i+=1
    if not sym:
        print("Usage: snowball kchart <symbol> --period minute [--refresh 30]"); sys.exit(1)
    return sym, refresh


def main():
    sym, ref = parse_args(); draw_fenshi(sym, ref)

if __name__ == "__main__": main()