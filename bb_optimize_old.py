"""
╔══════════════════════════════════════════════════════════════════════════════╗
║  Bollinger %B Strategy — Parameter Optimizer                               ║
║  Grid-searches all key parameters, ranks by Sharpe + PnL + Win Rate        ║
║  Automatically patches bb_backtest.py with the best found parameters       ║
╚══════════════════════════════════════════════════════════════════════════════╝

USAGE:
    python bb_optimize.py GOLD
    python bb_optimize.py NATURALGAS --tf 30
    python bb_optimize.py NTPC --tf 15 --days 180
    python bb_optimize.py --symbol GOLD --tf 45 --days 365
    python bb_optimize.py GOLD --quick          # fast mode (fewer combos)
    python bb_optimize.py GOLD --no-patch       # show best params but don't update bb_backtest.py

HOW IT WORKS:
    1. Fetches data from Zerodha (same as bb_backtest.py)
    2. Runs hundreds of backtests across all parameter combinations
    3. Scores each run:  Score = Sharpe*40 + ProfitFactor*30 + WinRate*20 + CAGR*10
    4. Prints top-10 parameter sets ranked by score
    5. Auto-patches bb_backtest.py with the best parameters
"""

import os, sys, time, math, argparse, itertools
from datetime import datetime, timedelta, timezone
import subprocess

def _pip(pkg):
    try: __import__(pkg.split("[")[0].replace("-","_"))
    except ImportError:
        subprocess.run([sys.executable,"-m","pip","install",pkg,
                        "--quiet","--break-system-packages"], check=True)

for p in ["kiteconnect","pyotp","pandas","numpy","tabulate","requests"]:
    _pip(p)

import requests
import pyotp
import pandas as pd
import numpy as np
from kiteconnect import KiteConnect
from tabulate import tabulate

# ══════════════════════════════════════════════════════════════════════════════
#  CREDENTIALS
# ══════════════════════════════════════════════════════════════════════════════
API_KEY    = os.getenv("KITE_API_KEY",  "4tl671rr7bwffw7b")
API_SECRET = os.getenv("KITE_SECRET",   "4gesk7v5vsbx9us4t8j3gh229zwzwf9t")
USER_ID    = os.getenv("KITE_USER_ID",  "QWK225")
PASSWORD   = os.getenv("KITE_PASSWORD", "Dec2025!")
TOTP_KEY   = os.getenv("KITE_TOTP_KEY", "VV2ZTNC3LG4V7EG7ECFLJIURPGVERJL7")

IST = timezone(timedelta(hours=5, minutes=30))
BROKERAGE_PCT = 0.0003
SLIPPAGE_PCT  = 0.001

# ══════════════════════════════════════════════════════════════════════════════
#  INSTRUMENT REGISTRY  (same as bb_backtest.py)
# ══════════════════════════════════════════════════════════════════════════════
INSTRUMENT_MAP = {
    "GOLD":       ("MCX","GOLD","FUT",["GOLDM","GOLDTEN","GOLDPETAL","GOLDGUINEA"]),
    "GOLDM":      ("MCX","GOLDM","FUT",["GOLDTEN","GOLDPETAL","GOLDGUINEA"]),
    "SILVER":     ("MCX","SILVER","FUT",["SILVERM","SILVERMIC"]),
    "SILVERM":    ("MCX","SILVERM","FUT",["SILVERMIC"]),
    "NATURALGAS": ("MCX","NATURALGAS","FUT",["NATURALGASM"]),
    "CRUDEOIL":   ("MCX","CRUDEOIL","FUT",["CRUDEOILM"]),
    "COPPER":     ("MCX","COPPER","FUT",["COPPERM"]),
    "ZINC":       ("MCX","ZINC","FUT",["ZINCM"]),
    "ALUMINIUM":  ("MCX","ALUMINIUM","FUT",["ALUMM","ALUMINIUMM"]),
    "NTPC":       ("NSE","NTPC","EQ",[]),
    "RELIANCE":   ("NSE","RELIANCE","EQ",[]),
    "TCS":        ("NSE","TCS","EQ",[]),
    "INFY":       ("NSE","INFY","EQ",[]),
    "HDFCBANK":   ("NSE","HDFCBANK","EQ",[]),
    "ICICIBANK":  ("NSE","ICICIBANK","EQ",[]),
    "SBIN":       ("NSE","SBIN","EQ",[]),
    "TATASTEEL":  ("NSE","TATASTEEL","EQ",[]),
    "ONGC":       ("NSE","ONGC","EQ",[]),
    "BHARTIARTL": ("NSE","BHARTIARTL","EQ",[]),
}

# ══════════════════════════════════════════════════════════════════════════════
#  PARAMETER SEARCH SPACE
#  Full mode  → all combinations  (~1500-2000 combos, ~5-10 min)
#  Quick mode → reduced grid      (~200-400 combos,   ~1-2 min)
#
#  Key insight: RSI thresholds 35/65 are too tight → only ~6-10 trades/year
#  Wider RSI (45/55 or 50/50) → 20-40 trades/year with still-good quality
# ══════════════════════════════════════════════════════════════════════════════
PARAM_GRID_FULL = {
    "bb_length":        [10, 14, 20, 25],
    "bb_mult":          [1.5, 2.0, 2.5],
    "call_lower":       [-0.30, -0.20, -0.10],
    "call_upper":       [0.05, 0.10, 0.15],
    "put_lower":        [0.85, 0.90, 0.95, 1.00],
    "rsi_call_max":     [40, 45, 50, 55],     # wider — was [35,40,45]
    "rsi_put_min":      [45, 50, 55, 60],     # wider — was [55,60,65]
    "trail_stop_pct":   [0.010, 0.015, 0.020],
    "cooldown":         [1, 2, 3],
    "min_atr_pct":      [0.002, 0.004, 0.006],
}

PARAM_GRID_QUICK = {
    "bb_length":        [14, 20],
    "bb_mult":          [1.5, 2.0, 2.5],
    "call_lower":       [-0.25, -0.10],
    "call_upper":       [0.05, 0.15],
    "put_lower":        [0.85, 0.95],
    "rsi_call_max":     [45, 55],             # wider — was [35,45]
    "rsi_put_min":      [45, 55],             # wider — was [55,65]
    "trail_stop_pct":   [0.010, 0.020],
    "cooldown":         [1, 2],
    "min_atr_pct":      [0.002, 0.005],
}

# Fixed exit trigger levels (not optimised — these are structural)
CALL_EXIT_TRIG_PREV  = 0.9
CALL_EXIT_EXTRA_PREV = 0.5
CALL_EXIT_FORCE      = 1.0
PUT_EXIT_TRIG_PREV   = 0.1
PUT_EXIT_FORCE       = -0.2
RSI_PERIOD           = 14
INITIAL_CAPITAL      = 100_000


# ══════════════════════════════════════════════════════════════════════════════
#  CLI
# ══════════════════════════════════════════════════════════════════════════════
def parse_args():
    p = argparse.ArgumentParser(description="BB Strategy Parameter Optimizer")
    p.add_argument("symbol_pos", nargs="?", default=None, metavar="SYMBOL")
    p.add_argument("--symbol",   type=str, default=None)
    p.add_argument("--tf",       type=int, default=45, choices=[15,30,45,60])
    p.add_argument("--days",     type=int, default=365)
    p.add_argument("--quick",    action="store_true",
                   help="Faster run with smaller grid (~80 combos)")
    p.add_argument("--no-patch", action="store_true",
                   help="Print best params but do NOT update bb_backtest.py")
    p.add_argument("--backtest-file", type=str, default="bb_backtest.py",
                   help="Path to bb_backtest.py to patch (default: bb_backtest.py)")
    args = p.parse_args()
    if args.symbol:
        args.resolved_symbol = args.symbol.upper()
    elif args.symbol_pos:
        args.resolved_symbol = args.symbol_pos.upper()
    else:
        args.resolved_symbol = "GOLD"
    return args


# ══════════════════════════════════════════════════════════════════════════════
#  ZERODHA LOGIN
# ══════════════════════════════════════════════════════════════════════════════
def zerodha_login() -> KiteConnect:
    print("Logging in to Zerodha ...")
    kite = KiteConnect(api_key=API_KEY)
    login_url = kite.login_url()
    session = requests.Session()
    r1 = session.post("https://kite.zerodha.com/api/login",
                      data={"user_id":USER_ID,"password":PASSWORD},
                      headers={"Content-Type":"application/x-www-form-urlencoded"})
    r1.raise_for_status()
    request_id = r1.json()["data"]["request_id"]
    totp = pyotp.TOTP(TOTP_KEY).now()
    r2 = session.post("https://kite.zerodha.com/api/twofa",
                      data={"user_id":USER_ID,"request_id":request_id,
                            "twofa_value":totp,"twofa_type":"totp"},
                      headers={"Content-Type":"application/x-www-form-urlencoded"})
    r2.raise_for_status()
    r3 = session.get(login_url, allow_redirects=False)
    location = r3.headers.get("Location","")
    if "request_token=" not in location:
        r3 = session.get(login_url, allow_redirects=True)
        location = r3.url
    request_token = location.split("request_token=")[1].split("&")[0]
    data = kite.generate_session(request_token, api_secret=API_SECRET)
    kite.set_access_token(data["access_token"])
    print("Login successful!")
    return kite


# ══════════════════════════════════════════════════════════════════════════════
#  INSTRUMENT LOOKUP
# ══════════════════════════════════════════════════════════════════════════════
def get_instrument_token(kite, symbol):
    sym = symbol.upper()
    if sym in INSTRUMENT_MAP:
        exchange, prefix, inst_type, excludes = INSTRUMENT_MAP[sym]
    else:
        exchange, prefix, inst_type, excludes = ("NSE", sym, "EQ", [])

    if isinstance(excludes, str): excludes = [excludes]
    if excludes is None: excludes = []

    instruments = kite.instruments(exchange)
    df = pd.DataFrame(instruments)

    if inst_type == "FUT":
        mask = (df["tradingsymbol"].str.startswith(prefix) &
                (df["instrument_type"] == "FUT"))
        for ex in excludes:
            mask &= ~df["tradingsymbol"].str.startswith(ex)
        candidates = df[mask].copy()
        candidates["expiry"] = pd.to_datetime(candidates["expiry"])
        cutoff = pd.Timestamp.today() - pd.Timedelta(days=400)
        active = candidates[candidates["expiry"] >= cutoff].sort_values("expiry")
        if active.empty:
            raise RuntimeError(f"No {sym} futures on {exchange}")
        if "lot_size" in active.columns:
            active = (active.sort_values(["expiry","lot_size"], ascending=[True,False])
                            .drop_duplicates(subset="expiry", keep="first"))
        for _, r in active.iterrows():
            print(f"    {r['tradingsymbol']:30s}  expiry={r['expiry'].date()}  lot={r.get('lot_size','?')}")
        tokens_list = [(int(r["instrument_token"]), r["tradingsymbol"]) for _, r in active.iterrows()]
        display_sym = active.iloc[-1]["tradingsymbol"]
    else:
        mask = (df["tradingsymbol"] == prefix) & (df["instrument_type"] == "EQ")
        candidates = df[mask]
        if candidates.empty:
            raise RuntimeError(f"No EQ for {sym} on {exchange}")
        row = candidates.iloc[0]
        tokens_list = [(int(row["instrument_token"]), row["tradingsymbol"])]
        display_sym = row["tradingsymbol"]
        print(f"  Instrument: {display_sym}  Token: {row['instrument_token']}")

    return tokens_list, display_sym


# ══════════════════════════════════════════════════════════════════════════════
#  FETCH + RESAMPLE
# ══════════════════════════════════════════════════════════════════════════════
def fetch_ohlc(kite, tokens_list, days=365, tf=45):
    FETCH_BASE = {15:"15minute", 30:"30minute", 45:"15minute", 60:"60minute"}
    CHUNK_STEP = {15:timedelta(minutes=15), 30:timedelta(minutes=30),
                  45:timedelta(minutes=15), 60:timedelta(hours=1)}
    native_interval = FETCH_BASE[tf]
    needs_resample  = (tf == 45)
    step            = CHUNK_STEP[tf]

    end_date   = datetime.now(IST).replace(hour=23,minute=59,second=0,microsecond=0)
    start_date = end_date - timedelta(days=days)
    all_frames = []

    for idx, (token, sym) in enumerate(tokens_list):
        print(f"\n  Contract [{idx+1}/{len(tokens_list)}]: {sym}")
        seg_candles = []
        chunk_start = start_date
        while chunk_start < end_date:
            chunk_end = min(chunk_start + timedelta(days=58), end_date)
            print(f"    {chunk_start.date()} -> {chunk_end.date()} ...", end=" ")
            try:
                candles = kite.historical_data(token,
                    chunk_start.strftime("%Y-%m-%d %H:%M:%S"),
                    chunk_end.strftime("%Y-%m-%d %H:%M:%S"),
                    native_interval)
                seg_candles.extend(candles)
                print(f"{len(candles)} bars")
            except Exception as e:
                print(f"WARNING: {e}")
            chunk_start = chunk_end + step
            time.sleep(0.35)
        if seg_candles:
            seg_df = pd.DataFrame(seg_candles)
            seg_df["date"] = pd.to_datetime(seg_df["date"]).dt.tz_localize(None)
            seg_df = seg_df.set_index("date").sort_index()
            all_frames.append(seg_df)

    if not all_frames:
        raise RuntimeError("No data returned.")

    df = pd.concat(all_frames)
    df = df[~df.index.duplicated(keep="last")].sort_index()
    df = df[df.index >= pd.Timestamp(start_date.date())]

    if needs_resample:
        df = (df.resample(f"{tf}min", origin="start_day")
                .agg({"open":"first","high":"max","low":"min","close":"last","volume":"sum"})
                .dropna(subset=["open","close"]))
    else:
        df = df.dropna(subset=["open","close"])

    print(f"\n  Total: {len(df)} bars at {tf}-min")
    return df


# ══════════════════════════════════════════════════════════════════════════════
#  INDICATORS  (pre-computed once, reused across all param combos)
# ══════════════════════════════════════════════════════════════════════════════
def precompute_base(df: pd.DataFrame) -> pd.DataFrame:
    """Compute RSI and ATR once (these don't change with BB params)."""
    c = df["close"]
    h = df["high"]
    lw = df["low"]
    # ATR
    prev_c = c.shift(1)
    tr  = pd.concat([h-lw,(h-prev_c).abs(),(lw-prev_c).abs()],axis=1).max(axis=1)
    atr = tr.ewm(span=14,adjust=False).mean()
    df = df.copy()
    df["atr"]     = atr
    df["atr_pct"] = atr / c
    # RSI
    delta = c.diff()
    gain  = delta.clip(lower=0).ewm(alpha=1/RSI_PERIOD,adjust=False).mean()
    loss  = (-delta.clip(upper=0)).ewm(alpha=1/RSI_PERIOD,adjust=False).mean()
    rs    = gain / loss.replace(0, np.nan)
    df["rsi"] = 100 - (100/(1+rs))
    df["bullish"] = (c > df["open"]).astype(int)
    df["bearish"] = (c < df["open"]).astype(int)
    return df


def add_bb(df: pd.DataFrame, bb_length: int, bb_mult: float) -> pd.DataFrame:
    """Add Bollinger Band columns for a specific length/mult."""
    c = df["close"]
    o = df["open"]
    basis = c.rolling(bb_length).mean()
    dev   = c.rolling(bb_length).std(ddof=0)
    upper = basis + bb_mult * dev
    lower = basis - bb_mult * dev
    df = df.copy()
    df["pct_b"]     = (c - lower) / (upper - lower)
    df["open_pctb"] = (o - lower) / (upper - lower)
    df["vol_filter"]= (df["atr"] > df["atr"].rolling(14).mean()).astype(int)
    return df.dropna(subset=["pct_b","rsi","vol_filter"])


# ══════════════════════════════════════════════════════════════════════════════
#  FAST BACKTEST CORE  (no closures, optimised for speed in tight loop)
# ══════════════════════════════════════════════════════════════════════════════
def fast_backtest(df: pd.DataFrame, p: dict) -> dict:
    """
    Run one backtest with parameter dict p.
    Returns a flat dict of metrics, or None if too few trades.
    """
    call_lower    = p["call_lower"]
    call_upper    = p["call_upper"]
    put_lower     = p["put_lower"]
    rsi_call_max  = p["rsi_call_max"]
    rsi_put_min   = p["rsi_put_min"]
    trail_stop    = p["trail_stop_pct"]
    cooldown      = p["cooldown"]
    min_atr_pct   = p["min_atr_pct"]

    pct_b_arr  = df["pct_b"].values
    opb_arr    = df["open_pctb"].values
    close_arr  = df["close"].values
    bull_arr   = df["bullish"].values
    bear_arr   = df["bearish"].values
    vf_arr     = df["vol_filter"].values
    rsi_arr    = df["rsi"].values
    atr_arr    = df["atr_pct"].values
    ts_arr     = df.index

    equity          = INITIAL_CAPITAL
    call_open       = False
    put_open        = False
    call_entry      = 0.0
    call_peak       = 0.0
    put_entry       = 0.0
    put_trough      = 0.0
    last_trade_bar  = -999
    hold_call       = False
    hold_put        = False

    pnl_list = []
    win_list  = []
    n = len(df)

    for i in range(1, n):
        pct_b     = pct_b_arr[i]
        pct_b_1   = pct_b_arr[i-1]
        open_pctb = opb_arr[i]
        close     = close_arr[i]
        bull      = bull_arr[i]
        bear      = bear_arr[i]
        vf        = vf_arr[i]
        rsi       = rsi_arr[i]
        atr_pct   = atr_arr[i]
        can_trade = (i - last_trade_bar) > cooldown

        # Update trailing extremes
        if call_open: call_peak   = max(call_peak, close)
        if put_open:  put_trough  = min(put_trough, close)

        # Entry conditions
        atr_ok   = atr_pct >= min_atr_pct
        buy_call = (call_lower <= pct_b <= call_upper and bull and
                    not call_open and not put_open and
                    vf and can_trade and atr_ok and rsi < rsi_call_max)
        buy_put  = (pct_b >= put_lower and bear and
                    not put_open and not call_open and
                    vf and can_trade and atr_ok and rsi > rsi_put_min)

        # Exit triggers
        ce_trig  = pct_b_1 >= CALL_EXIT_TRIG_PREV  and open_pctb < CALL_EXIT_TRIG_PREV
        ce_extra = pct_b_1 >= CALL_EXIT_EXTRA_PREV and open_pctb < CALL_EXIT_EXTRA_PREV
        cf_now   = pct_b > CALL_EXIT_FORCE
        pe_trig  = pct_b_1 <= PUT_EXIT_TRIG_PREV  and open_pctb > PUT_EXIT_TRIG_PREV
        pf_now   = pct_b < PUT_EXIT_FORCE

        c_trail  = call_open and close < call_peak  * (1 - trail_stop)
        p_trail  = put_open  and close > put_trough * (1 + trail_stop)

        def close_call(px):
            nonlocal equity, call_open, hold_call, call_peak
            cost    = call_entry * (1 + SLIPPAGE_PCT + BROKERAGE_PCT)
            revenue = px         * (1 - SLIPPAGE_PCT - BROKERAGE_PCT)
            pnl_pct = (revenue - cost) / cost
            pnl     = equity * pnl_pct
            equity += pnl
            pnl_list.append(pnl_pct * 100)
            win_list.append(pnl > 0)
            call_open = False; hold_call = False; call_peak = 0.0

        def close_put(px):
            nonlocal equity, put_open, hold_put, put_trough
            price_move = (put_entry - px) / put_entry
            pnl_pct    = price_move - SLIPPAGE_PCT*2 - BROKERAGE_PCT*2
            pnl        = equity * pnl_pct
            equity    += pnl
            pnl_list.append(pnl_pct * 100)
            win_list.append(pnl > 0)
            put_open = False; hold_put = False; put_trough = 0.0

        # CALL management
        if call_open:
            if c_trail:
                close_call(close)
            elif ce_trig or ce_extra:
                close_call(close)
                if rsi > rsi_put_min:
                    put_open = True; put_entry = close*(1+SLIPPAGE_PCT)
                    put_trough = close; last_trade_bar = i; hold_put = False
            elif open_pctb >= CALL_EXIT_TRIG_PREV:
                hold_call = True
            elif hold_call and cf_now:
                close_call(close)
                if rsi > rsi_put_min:
                    put_open = True; put_entry = close*(1+SLIPPAGE_PCT)
                    put_trough = close; last_trade_bar = i; hold_put = False

        # PUT management
        elif put_open:
            if p_trail:
                close_put(close)
            elif pe_trig:
                close_put(close)
                if rsi < rsi_call_max:
                    call_open = True; call_entry = close*(1+SLIPPAGE_PCT)
                    call_peak = close; last_trade_bar = i; hold_call = False
            elif open_pctb <= PUT_EXIT_TRIG_PREV:
                hold_put = True
            elif hold_put and pf_now:
                close_put(close)
                if rsi < rsi_call_max:
                    call_open = True; call_entry = close*(1+SLIPPAGE_PCT)
                    call_peak = close; last_trade_bar = i; hold_call = False

        # Fresh entries
        else:
            if buy_call:
                call_open = True; call_entry = close*(1+SLIPPAGE_PCT)
                call_peak = close; last_trade_bar = i; hold_call = False
            elif buy_put:
                put_open = True; put_entry = close*(1+SLIPPAGE_PCT)
                put_trough = close; last_trade_bar = i; hold_put = False

    # Close open trade at end
    last_close = close_arr[-1]
    if call_open: 
        pnl_pct = (last_close - call_entry) / call_entry - SLIPPAGE_PCT - BROKERAGE_PCT
        pnl = equity * pnl_pct; equity += pnl
        pnl_list.append(pnl_pct*100); win_list.append(pnl>0)
    if put_open:
        pnl_pct = (put_entry - last_close)/put_entry - SLIPPAGE_PCT*2 - BROKERAGE_PCT*2
        pnl = equity * pnl_pct; equity += pnl
        pnl_list.append(pnl_pct*100); win_list.append(pnl>0)

    total = len(pnl_list)
    if total < 8:
        return None   # require at least 8 trades (~1 trade per 6 weeks) to evaluate

    wins     = sum(win_list)
    win_rate = wins / total * 100
    pnl_arr  = np.array(pnl_list) / 100
    net_pnl  = (equity - INITIAL_CAPITAL)

    gross_pos = sum(x for x in pnl_arr if x > 0)
    gross_neg = abs(sum(x for x in pnl_arr if x < 0))
    pf        = gross_pos / gross_neg if gross_neg > 0 else gross_pos * 10

    sharpe    = (pnl_arr.mean() / pnl_arr.std() * math.sqrt(total)
                 if pnl_arr.std() > 0 else 0.0)

    days_span = (df.index[-1] - df.index[0]).days
    years     = max(days_span / 365, 0.01)
    cagr      = ((equity / INITIAL_CAPITAL)**(1/years) - 1) * 100

    # Drawdown
    eq_curve = [INITIAL_CAPITAL]
    eq = INITIAL_CAPITAL
    for pp in pnl_arr:
        eq += eq * pp
        eq_curve.append(eq)
    peak = INITIAL_CAPITAL; max_dd_pct = 0
    for eq in eq_curve:
        peak = max(peak, eq)
        dd = (peak - eq) / peak * 100
        if dd > max_dd_pct: max_dd_pct = dd

    total_return = (equity - INITIAL_CAPITAL) / INITIAL_CAPITAL * 100

    # Trades per month (ideal range: 3-8 trades/month)
    months       = max(days_span / 30, 1)
    trades_month = total / months

    # ── Composite score (higher = better) ─────────────────────────────────
    # Core components
    sharpe_score  = sharpe * 35
    pf_score      = min(pf, 6) * 15           # cap PF at 6 to avoid tiny-sample bias
    wr_score      = win_rate * 0.4
    cagr_score    = min(cagr, 120) * 0.25
    ret_score     = total_return * 0.15

    # Frequency bonus: reward 3-10 trades/month, penalise < 2 or > 15
    if trades_month >= 3:
        freq_bonus = min(trades_month, 10) * 2.0   # up to +20
    elif trades_month >= 2:
        freq_bonus = trades_month * 1.0             # small bonus
    else:
        freq_bonus = -15                            # heavy penalty for < 2/month

    # Penalties
    dd_penalty = max(0, max_dd_pct - 25) * 2.5     # penalise DD > 25%
    wr_penalty = max(0, 45 - win_rate) * 1.5        # penalise WR < 45%
    low_trade_penalty = max(0, 10 - total) * 3      # penalise < 10 total trades

    score = (sharpe_score + pf_score + wr_score + cagr_score + ret_score
             + freq_bonus - dd_penalty - wr_penalty - low_trade_penalty)

    return {
        "score":          round(score, 3),
        "total_trades":   total,
        "trades_month":   round(trades_month, 1),
        "win_rate":       round(win_rate, 1),
        "net_pnl":        round(net_pnl, 0),
        "total_return":   round(total_return, 2),
        "cagr":           round(cagr, 2),
        "sharpe":         round(sharpe, 3),
        "profit_factor":  round(pf, 3),
        "max_dd_pct":     round(max_dd_pct, 2),
        "final_equity":   round(equity, 0),
        # params
        "bb_length":      p["bb_length"],
        "bb_mult":        p["bb_mult"],
        "call_lower":     p["call_lower"],
        "call_upper":     p["call_upper"],
        "put_lower":      p["put_lower"],
        "rsi_call_max":   p["rsi_call_max"],
        "rsi_put_min":    p["rsi_put_min"],
        "trail_stop_pct": p["trail_stop_pct"],
        "cooldown":       p["cooldown"],
        "min_atr_pct":    p["min_atr_pct"],
    }


# ══════════════════════════════════════════════════════════════════════════════
#  OPTIMIZER RUNNER
# ══════════════════════════════════════════════════════════════════════════════
def run_optimizer(df_base: pd.DataFrame, grid: dict) -> list:
    """
    Grid-search all parameter combinations.
    Returns list of result dicts sorted by score descending.
    """
    keys   = list(grid.keys())
    values = list(grid.values())
    combos = list(itertools.product(*values))
    total  = len(combos)

    print(f"\n  Grid size : {total} combinations")
    print(f"  Started   : {datetime.now().strftime('%H:%M:%S')}")
    print()

    # Cache BB-precomputed frames to avoid recomputing same bb_length/bb_mult
    bb_cache = {}
    results  = []
    done     = 0
    skipped  = 0

    for combo in combos:
        p = dict(zip(keys, combo))

        # Get or compute BB for this length/mult
        bb_key = (p["bb_length"], p["bb_mult"])
        if bb_key not in bb_cache:
            bb_cache[bb_key] = add_bb(df_base, p["bb_length"], p["bb_mult"])
        df_bb = bb_cache[bb_key]

        r = fast_backtest(df_bb, p)
        done += 1

        if r is None:
            skipped += 1
        else:
            results.append(r)

        # Progress bar every 50 combos
        if done % 50 == 0 or done == total:
            pct = done / total * 100
            bar = "█" * int(pct / 5) + "░" * (20 - int(pct / 5))
            print(f"\r  [{bar}] {done}/{total} ({pct:.0f}%)  "
                  f"valid={len(results)}  skipped={skipped}", end="", flush=True)

    print(f"\n\n  Done at {datetime.now().strftime('%H:%M:%S')}")
    results.sort(key=lambda x: x["score"], reverse=True)
    return results


# ══════════════════════════════════════════════════════════════════════════════
#  PRINT RESULTS TABLE
# ══════════════════════════════════════════════════════════════════════════════
def print_results(results: list, symbol: str, tf: int, top_n: int = 10):
    W = 80
    print("\n" + "=" * W)
    print(f"  OPTIMIZATION RESULTS  --  {symbol}  ({tf}-min)  |  Top {top_n}")
    print("=" * W)

    if not results:
        print("  No valid parameter combinations found.")
        return

    display = results[:top_n]
    rows = []
    for rank, r in enumerate(display, 1):
        rows.append([
            rank,
            f"{r['score']:.1f}",
            r["total_trades"],
            f"{r.get('trades_month', '?')}/mo",
            f"{r['win_rate']:.0f}%",
            f"Rs {r['net_pnl']:>9,.0f}",
            f"{r['total_return']:>+.1f}%",
            f"{r['cagr']:>+.1f}%",
            f"{r['sharpe']:.2f}",
            f"{r['profit_factor']:.2f}",
            f"{r['max_dd_pct']:.1f}%",
        ])
    headers = ["Rank","Score","Trades","Freq","WinRate","Net PnL","Return%","CAGR",
               "Sharpe","PF","MaxDD%"]
    print("\n[Performance Ranking]")
    print(tabulate(rows, headers=headers, tablefmt="rounded_outline"))

    # Best param detail
    best = results[0]
    print("\n[Best Parameter Set  (#1)]")
    param_rows = [
        ["BB Length",       best["bb_length"]],
        ["BB Multiplier",   best["bb_mult"]],
        ["CALL %B Lower",   best["call_lower"]],
        ["CALL %B Upper",   best["call_upper"]],
        ["PUT  %B Lower",   best["put_lower"]],
        ["RSI CALL Max",    best["rsi_call_max"]],
        ["RSI PUT  Min",    best["rsi_put_min"]],
        ["Trailing Stop",   f"{best['trail_stop_pct']*100:.1f}%"],
        ["Cooldown Bars",   best["cooldown"]],
        ["Min ATR %",       f"{best['min_atr_pct']*100:.2f}%"],
    ]
    print(tabulate(param_rows, tablefmt="rounded_outline"))

    print(f"\n[Best Result Summary]")
    perf_rows = [
        ["Score",          f"{best['score']:.3f}"],
        ["Total Trades",   best["total_trades"]],
        ["Win Rate",       f"{best['win_rate']:.1f}%"],
        ["Net PnL",        f"Rs {best['net_pnl']:>12,.0f}"],
        ["Total Return",   f"{best['total_return']:>+.2f}%"],
        ["CAGR",           f"{best['cagr']:>+.2f}%"],
        ["Sharpe Ratio",   f"{best['sharpe']:.3f}"],
        ["Profit Factor",  f"{best['profit_factor']:.3f}"],
        ["Max Drawdown",   f"{best['max_dd_pct']:.2f}%"],
        ["Final Equity",   f"Rs {best['final_equity']:>12,.0f}"],
    ]
    print(tabulate(perf_rows, tablefmt="rounded_outline"))
    print("=" * W)


# ══════════════════════════════════════════════════════════════════════════════
#  PATCH bb_backtest.py WITH BEST PARAMETERS
# ══════════════════════════════════════════════════════════════════════════════
def patch_backtest_file(best: dict, filepath: str):
    """
    Overwrites the parameter constants in bb_backtest.py with optimal values.
    Targets the section between the two comment markers.
    """
    if not os.path.exists(filepath):
        print(f"\n  WARNING: {filepath} not found — skipping patch.")
        return

    with open(filepath, "r") as f:
        content = f.read()

    replacements = {
        "DEFAULT_BB_LENGTH":     str(best["bb_length"]),
        "DEFAULT_BB_MULT":       str(float(best["bb_mult"])),
        "DEFAULT_COOLDOWN_BARS": str(best["cooldown"]),
        "CALL_LOWER":            str(best["call_lower"]),
        "CALL_UPPER":            str(best["call_upper"]),
        "PUT_LOWER":             str(best["put_lower"]),
        "RSI_CALL_MAX":          str(best["rsi_call_max"]),
        "RSI_PUT_MIN":           str(best["rsi_put_min"]),
        "TRAIL_STOP_PCT":        str(best["trail_stop_pct"]),
        "MIN_ATR_PCT":           str(best["min_atr_pct"]),
    }

    import re
    patched = content
    changed = []
    for var, val in replacements.items():
        # Match: VAR_NAME = <old_value>  # optional comment
        pattern = rf"^({re.escape(var)}\s*=\s*)([^\s#\n]+)"
        replacement = rf"\g<1>{val}"
        new_content, count = re.subn(pattern, replacement, patched, flags=re.MULTILINE)
        if count > 0:
            changed.append(f"  {var} = {val}")
            patched = new_content

    if changed:
        with open(filepath, "w") as f:
            f.write(patched)
        print(f"\n  Patched {filepath} with {len(changed)} parameter(s):")
        for c in changed:
            print(c)
        print(f"\n  Run the updated backtest:")
        print(f"    python {filepath} <SYMBOL> --tf <TF>")
    else:
        print(f"\n  WARNING: No parameters were patched in {filepath}.")
        print("  Check that the variable names match exactly.")


# ══════════════════════════════════════════════════════════════════════════════
#  MAIN
# ══════════════════════════════════════════════════════════════════════════════
def main():
    args   = parse_args()
    symbol = args.resolved_symbol
    tf     = args.tf
    days   = args.days
    grid   = PARAM_GRID_QUICK if args.quick else PARAM_GRID_FULL

    print("\n" + "=" * 60)
    print("  Bollinger %B Strategy — Parameter Optimizer")
    print("=" * 60)
    print(f"  Symbol    : {symbol}")
    print(f"  Timeframe : {tf}-min")
    print(f"  Lookback  : {days} days")
    print(f"  Grid mode : {'QUICK' if args.quick else 'FULL'}")

    keys = list(grid.keys())
    total_combos = 1
    for v in grid.values(): total_combos *= len(v)
    print(f"  Combos    : {total_combos}")
    print(f"  Patch file: {'NO (--no-patch)' if args.no_patch else args.backtest_file}")
    print("=" * 60 + "\n")

    kite = zerodha_login()
    tokens_list, display_sym = get_instrument_token(kite, symbol)

    print(f"\nFetching {days} days of {tf}-min data for {display_sym} ...")
    df_raw = fetch_ohlc(kite, tokens_list, days=days, tf=tf)

    print("\nPre-computing base indicators (RSI, ATR) ...")
    df_base = precompute_base(df_raw)

    print("\nRunning grid search ...")
    results = run_optimizer(df_base, grid)

    if not results:
        print("\n  No valid results found. Try --quick or increase --days.")
        return

    print_results(results, display_sym, tf, top_n=10)

    if not args.no_patch:
        best = results[0]
        bt_path = args.backtest_file
        # Try to find bb_backtest.py in the same directory
        if not os.path.exists(bt_path):
            same_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), bt_path)
            if os.path.exists(same_dir):
                bt_path = same_dir
        patch_backtest_file(best, bt_path)
    else:
        print("\n  (--no-patch set: bb_backtest.py was NOT modified)")

    print("\n  Optimization complete!")
    print(f"  Now run: python bb_backtest.py {symbol} --tf {tf}")


if __name__ == "__main__":
    main()
