"""
╔══════════════════════════════════════════════════════════════════════════════╗
║  Universal Bollinger %B Option Strategy Backtester  v4                     ║
║  Data Source : Zerodha Kite API  (30-min fetched, resampled to 45-min)     ║
║  Strategy    : %B + RSI filter + Bull Market Band + CALL<->PUT Flip        ║
╚══════════════════════════════════════════════════════════════════════════════╝

USAGE:
    python bb_backtest.py GOLD
    python bb_backtest.py NATURALGAS
    python bb_backtest.py NTPC
    python bb_backtest.py SILVER
    python bb_backtest.py RELIANCE
    python bb_backtest.py --symbol NTPC --days 180
    python bb_backtest.py --symbol GOLD --days 365 --capital 200000

SUPPORTED SYMBOLS:
    MCX Futures  : GOLD, GOLDM, SILVER, SILVERM, NATURALGAS, CRUDEOIL, COPPER, ZINC, ALUMINIUM
    NSE Equities : NTPC, RELIANCE, TCS, INFY, HDFCBANK, ICICIBANK, SBIN, TATASTEEL, ONGC, BHARTIARTL
                   (or any valid NSE symbol)

FLAGS:
    --symbol   / positional  : instrument name (default: GOLD)
    --days     : lookback days for data  (default: 365)
    --capital  : starting capital in Rs  (default: 100000)
    --bb-len   : Bollinger Band length   (default: 20)
    --bb-mult  : Bollinger Band multiplier (default: 2.0)
    --cooldown : bars cooldown between trades (default: 3)
    --tf       : candle timeframe in minutes — 15, 30, 45, 60 (default: 45)

TIMEFRAME EXAMPLES:
    python bb_backtest.py GOLD --tf 30
    python bb_backtest.py NATURALGAS --tf 45
    python bb_backtest.py NTPC --tf 15
    python bb_backtest.py --symbol SILVER --tf 60 --days 180
"""

import os, sys, time, math, argparse
from datetime import datetime, timedelta, timezone
import subprocess

# ── auto-install deps ──────────────────────────────────────────────────────────
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

# ══════════════════════════════════════════════════════════════════════════════
#  INSTRUMENT REGISTRY
#  Maps keyword → (exchange, prefix/symbol, instrument_type, exclude_prefix)
#  instrument_type: "FUT" for futures, "EQ" for NSE equity
# ══════════════════════════════════════════════════════════════════════════════
INSTRUMENT_MAP = {
    # ── NSE Index Futures (NFO) ───────────────────────────────────────────
    "NIFTY":       ("NFO", "NIFTY",      "FUT", ["NIFTYIT","NIFTYMID","NIFTYNXT","NIFTYBANK",
                                                  "NIFTYPVTBANK","NIFTYINDIABANK"]),
    "BANKNIFTY":   ("NFO", "BANKNIFTY",  "FUT", []),
    "FINNIFTY":    ("NFO", "FINNIFTY",   "FUT", []),
    "MIDCPNIFTY":  ("NFO", "MIDCPNIFTY", "FUT", []),
    "NIFTYNXT50":  ("NFO", "NIFTYNXT50", "FUT", []),
    # ── BSE Index Futures (BFO) ───────────────────────────────────────────
    "SENSEX":      ("BFO", "SENSEX",     "FUT", ["SENSEX50"]),
    "BANKEX":      ("BFO", "BANKEX",     "FUT", []),
    "SENSEX50":    ("BFO", "SENSEX50",   "FUT", []),
    # ── MCX Futures ───────────────────────────────────────────────────────
    "GOLD":        ("MCX", "GOLD",       "FUT", ["GOLDM","GOLDTEN","GOLDPETAL","GOLDGUINEA"]),
    "GOLDM":       ("MCX", "GOLDM",      "FUT", ["GOLDTEN","GOLDPETAL","GOLDGUINEA"]),
    "SILVER":      ("MCX", "SILVER",     "FUT", ["SILVERM","SILVERMIC"]),
    "SILVERM":     ("MCX", "SILVERM",    "FUT", ["SILVERMIC"]),
    "NATURALGAS":  ("MCX", "NATURALGAS", "FUT", ["NATURALGASM"]),
    "CRUDEOIL":    ("MCX", "CRUDEOIL",   "FUT", ["CRUDEOILM"]),
    "COPPER":      ("MCX", "COPPER",     "FUT", ["COPPERM"]),
    "ZINC":        ("MCX", "ZINC",       "FUT", ["ZINCM"]),
    "ALUMINIUM":   ("MCX", "ALUMINIUM",  "FUT", ["ALUMM","ALUMINIUMM"]),
    # ── NSE Equities (spot, no futures needed) ────────────────────────────
    "NTPC":        ("NSE", "NTPC",       "EQ",  []),
    "RELIANCE":    ("NSE", "RELIANCE",   "EQ",  []),
    "TCS":         ("NSE", "TCS",        "EQ",  []),
    "INFY":        ("NSE", "INFY",       "EQ",  []),
    "HDFCBANK":    ("NSE", "HDFCBANK",   "EQ",  []),
    "ICICIBANK":   ("NSE", "ICICIBANK",  "EQ",  []),
    "SBIN":        ("NSE", "SBIN",       "EQ",  []),
    "TATASTEEL":   ("NSE", "TATASTEEL",  "EQ",  []),
    "ONGC":        ("NSE", "ONGC",       "EQ",  []),
    "BHARTIARTL":  ("NSE", "BHARTIARTL", "EQ",  []),
}

# ══════════════════════════════════════════════════════════════════════════════
#  STRATEGY PARAMETERS
#  Balanced for ~3-6 trades/month while maintaining profitability.
#  Run bb_optimize.py to auto-tune these for your specific symbol + timeframe.
# ══════════════════════════════════════════════════════════════════════════════
DEFAULT_BB_LENGTH     = 14
DEFAULT_BB_MULT       = 1.5
DEFAULT_COOLDOWN_BARS = 1

# Entry thresholds — wider window = more trades
CALL_LOWER    = -0.1           # wider: catches more oversold bounces
CALL_UPPER    =  0.15           # wider: was 0.02
PUT_LOWER     =  0.85           # lower: was 1.05 — catches earlier breakdowns

# RSI filter — balanced, not too strict
RSI_CALL_MAX  = 45              # was 40 — too strict (only 6 trades/year)
RSI_PUT_MIN   = 45              # was 60 — too strict
RSI_PERIOD    = 14

# Exit triggers (structural — not optimised)
CALL_EXIT_TRIG_PREV  = 0.9
CALL_EXIT_EXTRA_PREV = 0.5
CALL_EXIT_FORCE      = 1.0
PUT_EXIT_TRIG_PREV   = 0.1
PUT_EXIT_FORCE       = -0.2

# Trailing stop
TRAIL_STOP_PCT = 0.02          # 1.5%

# Minimum ATR filter — lower threshold = fewer skips
MIN_ATR_PCT   = 0.002           # was 0.005

BROKERAGE_PCT = 0.0003
SLIPPAGE_PCT  = 0.001


# ══════════════════════════════════════════════════════════════════════════════
#  CLI ARGUMENT PARSER
# ══════════════════════════════════════════════════════════════════════════════
def parse_args():
    parser = argparse.ArgumentParser(
        description="Bollinger %%B Backtester — supports GOLD, NATURALGAS, NTPC, etc.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python bb_backtest.py GOLD
  python bb_backtest.py NATURALGAS
  python bb_backtest.py NTPC
  python bb_backtest.py --symbol SILVER --days 180
  python bb_backtest.py --symbol RELIANCE --days 365 --capital 500000
        """
    )
    # Positional (optional) — allows:  python bb_backtest.py GOLD
    parser.add_argument("symbol_pos", nargs="?", default=None,
                        metavar="SYMBOL",
                        help="Instrument name (e.g. GOLD, NATURALGAS, NTPC)")
    # Named flag — allows:  python bb_backtest.py --symbol GOLD
    parser.add_argument("--symbol",   type=str, default=None,
                        help="Instrument name (overrides positional)")
    parser.add_argument("--days",     type=int, default=365,
                        help="Lookback days (default: 365)")
    parser.add_argument("--capital",  type=float, default=100_000,
                        help="Initial capital in Rs (default: 100000)")
    parser.add_argument("--bb-len",   type=int,   default=DEFAULT_BB_LENGTH,
                        help="Bollinger Band length (default: 20)")
    parser.add_argument("--bb-mult",  type=float, default=DEFAULT_BB_MULT,
                        help="Bollinger Band multiplier (default: 2.0)")
    parser.add_argument("--cooldown", type=int,   default=DEFAULT_COOLDOWN_BARS,
                        help="Cooldown bars between trades (default: 3)")
    parser.add_argument("--tf",       type=int,   default=45,
                        choices=[15, 30, 45, 60],
                        help="Candle timeframe in minutes: 15, 30, 45, 60 (default: 45)")

    args = parser.parse_args()

    # Resolve symbol: --symbol wins over positional; default to GOLD
    if args.symbol:
        sym = args.symbol.upper()
    elif args.symbol_pos:
        sym = args.symbol_pos.upper()
    else:
        sym = "GOLD"
    args.resolved_symbol = sym
    return args


# ══════════════════════════════════════════════════════════════════════════════
#  ZERODHA LOGIN
# ══════════════════════════════════════════════════════════════════════════════
def zerodha_login() -> KiteConnect:
    print("Logging in to Zerodha ...")
    kite = KiteConnect(api_key=API_KEY)
    login_url = kite.login_url()
    session = requests.Session()

    r1 = session.post(
        "https://kite.zerodha.com/api/login",
        data={"user_id": USER_ID, "password": PASSWORD},
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    r1.raise_for_status()
    request_id = r1.json()["data"]["request_id"]

    totp = pyotp.TOTP(TOTP_KEY).now()
    r2 = session.post(
        "https://kite.zerodha.com/api/twofa",
        data={"user_id": USER_ID, "request_id": request_id,
              "twofa_value": totp, "twofa_type": "totp"},
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    r2.raise_for_status()

    r3 = session.get(login_url, allow_redirects=False)
    location = r3.headers.get("Location", "")
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
def get_instrument_token(kite: KiteConnect, symbol: str):
    """
    Returns (tokens_list, display_symbol) for any supported symbol.
    tokens_list is ordered oldest-expiry-first so fetch_ohlc can stitch them.
    For NSE EQ returns a single-element list.
    """
    sym_upper = symbol.upper()

    if sym_upper in INSTRUMENT_MAP:
        exchange, prefix, inst_type, excludes = INSTRUMENT_MAP[sym_upper]
    else:
        print(f"  '{sym_upper}' not in registry — trying NSE:EQ fallback ...")
        exchange, prefix, inst_type, excludes = ("NSE", sym_upper, "EQ", [])

    # normalise excludes to list
    if isinstance(excludes, str):
        excludes = [excludes]
    if excludes is None:
        excludes = []

    print(f"  Looking up {sym_upper} on {exchange} ({inst_type}) ...")
    instruments = kite.instruments(exchange)
    df = pd.DataFrame(instruments)

    if inst_type == "FUT":
        # exact prefix match: tradingsymbol must start with prefix
        # but NOT start with any of the exclude prefixes
        mask = (df["tradingsymbol"].str.startswith(prefix) &
                (df["instrument_type"] == "FUT"))
        for ex in excludes:
            mask &= ~df["tradingsymbol"].str.startswith(ex)

        candidates = df[mask].copy()
        candidates["expiry"] = pd.to_datetime(candidates["expiry"])

        # Only keep contracts whose expiry is in the future or near-past (last 400 days)
        cutoff = pd.Timestamp.today() - pd.Timedelta(days=400)
        active = candidates[candidates["expiry"] >= cutoff].sort_values("expiry")

        if active.empty:
            alt_cols = [c for c in df.columns if c in ("name","underlying","underlying_symbol")]
            if alt_cols:
                col = alt_cols[0]
                mask2 = (df[col].str.upper() == prefix.upper()) & (df["instrument_type"] == "FUT")
                candidates2 = df[mask2].copy()
                candidates2["expiry"] = pd.to_datetime(candidates2["expiry"])
                active = candidates2[candidates2["expiry"] >= cutoff].sort_values("expiry")
            if active.empty:
                sample = df[df["instrument_type"]=="FUT"]["tradingsymbol"].str[:len(prefix)+2].unique()[:10].tolist()
                raise RuntimeError(
                    f"No {sym_upper} futures found on {exchange}. "
                    f"Sample FUT symbols on {exchange}: {sample}. "
                    f"Check that '{prefix}' matches the tradingsymbol prefix exactly."
                )

        # Among contracts with same expiry, prefer largest lot_size (1kg GOLD > 10gm GOLDTEN)
        # Group by expiry, pick max lot_size row in each group
        if "lot_size" in active.columns:
            active = (active.sort_values(["expiry","lot_size"], ascending=[True,False])
                            .drop_duplicates(subset="expiry", keep="first"))
        else:
            active = active.drop_duplicates(subset="expiry", keep="first")

        # Print what we found
        for _, r in active.iterrows():
            lot = r.get("lot_size","?")
            print(f"    {r['tradingsymbol']:30s}  expiry={r['expiry'].date()}  lot={lot}")

        # Return all contracts sorted oldest→newest for stitching
        tokens_list = [(int(r["instrument_token"]), r["tradingsymbol"])
                       for _, r in active.iterrows()]
        display_sym = active.iloc[-1]["tradingsymbol"]   # most recent = display name

    else:  # EQ
        mask = ((df["tradingsymbol"] == prefix) &
                (df["instrument_type"] == "EQ"))
        candidates = df[mask]
        if candidates.empty:
            index_hints = {"NIFTY","BANKNIFTY","FINNIFTY","SENSEX","BANKEX",
                           "MIDCPNIFTY","NIFTYNXT50","SENSEX50"}
            if sym_upper in index_hints:
                raise RuntimeError(
                    f"'{sym_upper}' is an index — it cannot be looked up as EQ. "
                    f"It should be in INSTRUMENT_MAP with inst_type='FUT'."
                )
            raise RuntimeError(f"No EQ instrument found for {sym_upper} on {exchange}")
        row = candidates.iloc[0]
        tokens_list = [(int(row["instrument_token"]), row["tradingsymbol"])]
        display_sym = row["tradingsymbol"]
        print(f"  Instrument : {display_sym}  |  Token: {row['instrument_token']}")

    return tokens_list, display_sym


# ══════════════════════════════════════════════════════════════════════════════
#  FETCH + RESAMPLE OHLC  (stitches multiple futures contracts automatically)
#  Kite natively supports: 1min, 3min, 5min, 10min, 15min, 30min, 60min, day
#  For 45min: fetch 15min and resample  |  For 30/15/60min: fetch natively
# ══════════════════════════════════════════════════════════════════════════════
def fetch_ohlc(kite: KiteConnect, tokens_list: list, days: int = 365, tf: int = 45) -> pd.DataFrame:
    """
    tokens_list : [(token, symbol), ...] sorted oldest-expiry-first
    Fetches each contract for its valid date window, then concatenates.
    """
    FETCH_BASE = {15: "15minute", 30: "30minute", 45: "15minute", 60: "60minute"}
    CHUNK_STEP = {15: timedelta(minutes=15), 30: timedelta(minutes=30),
                  45: timedelta(minutes=15), 60: timedelta(hours=1)}

    native_interval = FETCH_BASE[tf]
    needs_resample  = (tf == 45)
    step            = CHUNK_STEP[tf]

    end_date   = datetime.now(IST).replace(hour=23, minute=59, second=0, microsecond=0)
    start_date = end_date - timedelta(days=days)

    all_frames = []

    for idx, (token, sym) in enumerate(tokens_list):
        # Each contract is valid from start_date (or its own start) to its expiry
        # We fetch all contracts in the date window; dedup later
        seg_start = start_date
        seg_end   = end_date

        print(f"\n  Contract [{idx+1}/{len(tokens_list)}]: {sym}  (token={token})")
        seg_candles = []
        chunk_start = seg_start

        while chunk_start < seg_end:
            chunk_end = min(chunk_start + timedelta(days=58), seg_end)
            print(f"    {chunk_start.date()} -> {chunk_end.date()} [{native_interval}] ...", end=" ")
            try:
                candles = kite.historical_data(
                    token,
                    chunk_start.strftime("%Y-%m-%d %H:%M:%S"),
                    chunk_end.strftime("%Y-%m-%d %H:%M:%S"),
                    native_interval,
                )
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
            print(f"    Collected {len(seg_df)} bars for {sym}")

    if not all_frames:
        raise RuntimeError("No data returned from any contract — check symbol or date range.")

    # Concatenate all contracts, keep last (most recent) value for duplicate timestamps
    df = pd.concat(all_frames)
    df = df[~df.index.duplicated(keep="last")].sort_index()

    # Keep only rows within requested date range
    df = df[df.index >= pd.Timestamp(start_date.date())]

    if needs_resample:
        df = (df.resample(f"{tf}min", origin="start_day")
                .agg({"open": "first", "high": "max",
                      "low":  "min",   "close": "last", "volume": "sum"})
                .dropna(subset=["open", "close"]))
        print(f"\n  Resampled 15-min -> {tf}-min: {len(df)} bars total")
    else:
        df = df.dropna(subset=["open", "close"])
        print(f"\n  Native {tf}-min: {len(df)} bars total")

    return df

# ══════════════════════════════════════════════════════════════════════════════
#  WEEKLY BULL MARKET BAND
# ══════════════════════════════════════════════════════════════════════════════
def add_weekly_band(df: pd.DataFrame) -> pd.DataFrame:
    weekly_close = df["close"].resample("W").last().dropna()
    n_weeks = len(weekly_close)

    # Clamp the rolling window to available weekly bars (min 2 to be meaningful).
    # With a full year of data this is 20 as intended; with shorter windows it
    # gracefully degrades rather than producing all-NaN and wiping the backtest.
    w_window = max(2, min(20, n_weeks))
    if w_window < 20:
        print(f"  [weekly band] Only {n_weeks} weekly bars available — "
              f"using w_sma({w_window}) instead of w_sma(20). "
              f"Run with --days 365+ for full-strength signal.")

    w_sma = weekly_close.rolling(w_window, min_periods=2).mean()
    w_ema = weekly_close.ewm(span=min(21, n_weeks), adjust=False).mean()
    df = df.copy()
    df["w_sma"] = w_sma.reindex(df.index, method="ffill")
    df["w_ema"] = w_ema.reindex(df.index, method="ffill")
    return df


# ══════════════════════════════════════════════════════════════════════════════
#  INDICATORS  (BB + RSI + ATR)
# ══════════════════════════════════════════════════════════════════════════════
def calculate_indicators(df: pd.DataFrame, bb_length: int, bb_mult: float) -> pd.DataFrame:
    c  = df["close"]
    o  = df["open"]
    h  = df["high"]
    lw = df["low"]

    # Bollinger Bands
    basis = c.rolling(bb_length).mean()
    dev   = c.rolling(bb_length).std(ddof=0)
    upper = basis + bb_mult * dev
    lower = basis - bb_mult * dev
    pct_b     = (c - lower) / (upper - lower)
    open_pctb = (o - lower) / (upper - lower)

    # Candle direction
    bullish = (c > o).astype(int)
    bearish = (c < o).astype(int)

    # ATR
    prev_c = c.shift(1)
    tr     = pd.concat([h - lw, (h - prev_c).abs(), (lw - prev_c).abs()], axis=1).max(axis=1)
    atr    = tr.ewm(span=14, adjust=False).mean()
    vol_filter = (atr > atr.rolling(14).mean()).astype(int)

    # ATR as % of price (min-ATR filter)
    atr_pct = atr / c

    # RSI(14) — Wilder's smoothing
    delta  = c.diff()
    gain   = delta.clip(lower=0).ewm(alpha=1/RSI_PERIOD, adjust=False).mean()
    loss   = (-delta.clip(upper=0)).ewm(alpha=1/RSI_PERIOD, adjust=False).mean()
    rs     = gain / loss.replace(0, np.nan)
    rsi    = 100 - (100 / (1 + rs))

    df = df.copy()
    df["basis"]      = basis
    df["upper"]      = upper
    df["lower"]      = lower
    df["pct_b"]      = pct_b
    df["open_pctb"]  = open_pctb
    df["bullish"]    = bullish
    df["bearish"]    = bearish
    df["vol_filter"] = vol_filter
    df["atr_pct"]    = atr_pct
    df["rsi"]        = rsi
    return df


# ══════════════════════════════════════════════════════════════════════════════
#  BACKTEST ENGINE  v4
#
#  Profitability improvements vs v3:
#  [1] RSI confirmation — CALL only when RSI < RSI_CALL_MAX (oversold)
#                        PUT  only when RSI > RSI_PUT_MIN  (overbought)
#  [2] Tighter %B entry window for CALL  (-0.15 to 0.02 vs -0.20 to 0.05)
#  [3] Trailing stop (1.5%) — locks in profits after move, cuts losers early
#  [4] Min-ATR filter — skip flat/sideways entries
#  [5] Cooldown reduced 5→3 bars
# ══════════════════════════════════════════════════════════════════════════════
def run_backtest(df: pd.DataFrame, initial_capital: float,
                 cooldown_bars: int) -> dict:
    df = add_weekly_band(df)
    df = df.dropna(subset=["pct_b", "vol_filter", "rsi", "w_sma"]).copy()

    if df.empty:
        raise RuntimeError(
            "No usable bars after indicator warm-up (dropna removed everything). "
            "Try increasing --days (e.g. --days 365) or reducing --bb-len."
        )

    equity          = initial_capital
    call_open       = False
    put_open        = False
    call_entry      = None
    call_entry_time = None
    call_peak       = None    # for trailing stop
    put_entry       = None
    put_entry_time  = None
    put_trough      = None    # for trailing stop
    last_trade_bar  = None
    hold_call       = False
    hold_put        = False

    trades = []

    def _close_call(exit_px, exit_ts, reason):
        nonlocal equity, call_open, hold_call, call_peak
        cost    = call_entry * (1 + SLIPPAGE_PCT + BROKERAGE_PCT)
        revenue = exit_px   * (1 - SLIPPAGE_PCT - BROKERAGE_PCT)
        pnl_pct = (revenue - cost) / cost
        pnl     = equity * pnl_pct
        equity += pnl
        trades.append({
            "type": "CALL", "reason": reason,
            "entry_time": call_entry_time, "exit_time": exit_ts,
            "entry_px": round(call_entry, 2), "exit_px": round(exit_px, 2),
            "pnl": round(pnl, 2), "pnl_pct": round(pnl_pct * 100, 3),
            "equity": round(equity, 2), "win": pnl > 0,
        })
        call_open = False; hold_call = False; call_peak = None

    def _close_put(exit_px, exit_ts, reason):
        nonlocal equity, put_open, hold_put, put_trough
        price_move = (put_entry - exit_px) / put_entry
        pnl_pct    = price_move - SLIPPAGE_PCT * 2 - BROKERAGE_PCT * 2
        pnl        = equity * pnl_pct
        equity    += pnl
        trades.append({
            "type": "PUT", "reason": reason,
            "entry_time": put_entry_time, "exit_time": exit_ts,
            "entry_px": round(put_entry, 2), "exit_px": round(exit_px, 2),
            "pnl": round(pnl, 2), "pnl_pct": round(pnl_pct * 100, 3),
            "equity": round(equity, 2), "win": pnl > 0,
        })
        put_open = False; hold_put = False; put_trough = None

    rows      = list(df.iterrows())
    pct_b_arr = df["pct_b"].values
    opb_arr   = df["open_pctb"].values
    print(f"  Usable bars after warm-up: {len(rows)}")

    for i, (ts, row) in enumerate(rows):
        if i == 0:
            continue

        pct_b     = pct_b_arr[i]
        pct_b_1   = pct_b_arr[i - 1]
        open_pctb = opb_arr[i]
        bull      = row["bullish"]
        bear      = row["bearish"]
        vf        = row["vol_filter"]
        close     = row["close"]
        rsi       = row["rsi"]
        atr_pct   = row["atr_pct"]
        can_trade = (last_trade_bar is None) or (i - last_trade_bar > cooldown_bars)

        # Update trailing peaks/troughs while trade is open
        if call_open and call_peak is not None:
            call_peak = max(call_peak, close)
        if put_open and put_trough is not None:
            put_trough = min(put_trough, close)

        # ── Entry conditions (v4) ─────────────────────────────────────────
        # RSI filter + min-ATR + tighter %B window
        atr_ok   = atr_pct >= MIN_ATR_PCT
        buy_call = (CALL_LOWER <= pct_b <= CALL_UPPER and
                    bull and not call_open and not put_open and
                    vf and can_trade and atr_ok and
                    rsi < RSI_CALL_MAX)       # NEW: oversold confirmation

        buy_put  = (pct_b >= PUT_LOWER and
                    bear and not put_open and not call_open and
                    vf and can_trade and atr_ok and
                    rsi > RSI_PUT_MIN)         # NEW: overbought confirmation

        # ── Exit triggers ─────────────────────────────────────────────────
        call_exit_trig  = (pct_b_1 >= CALL_EXIT_TRIG_PREV  and open_pctb < CALL_EXIT_TRIG_PREV)
        call_exit_extra = (pct_b_1 >= CALL_EXIT_EXTRA_PREV and open_pctb < CALL_EXIT_EXTRA_PREV)
        call_force_now  = pct_b > CALL_EXIT_FORCE
        put_exit_trig   = (pct_b_1 <= PUT_EXIT_TRIG_PREV and open_pctb > PUT_EXIT_TRIG_PREV)
        put_force_now   = pct_b < PUT_EXIT_FORCE

        # Trailing stop
        call_trail_hit  = (call_open and call_peak is not None and
                           close < call_peak * (1 - TRAIL_STOP_PCT))
        put_trail_hit   = (put_open and put_trough is not None and
                           close > put_trough * (1 + TRAIL_STOP_PCT))

        # ══════════ CALL MANAGEMENT ══════════════════════════════════════
        if call_open:
            if call_trail_hit:
                _close_call(close, ts, "TrailingStop")

            elif call_exit_trig or call_exit_extra:
                reason = "ExitTrig->FlipPUT" if call_exit_trig else "ExtraExit->FlipPUT"
                _close_call(close, ts, reason)
                if rsi > RSI_PUT_MIN:   # only flip if PUT entry is valid
                    put_open = True; put_entry = close * (1 + SLIPPAGE_PCT)
                    put_entry_time = ts; put_trough = close
                    last_trade_bar = i; hold_put = False

            elif open_pctb >= CALL_EXIT_TRIG_PREV:
                hold_call = True

            elif hold_call and call_force_now:
                _close_call(close, ts, "ForceExit->FlipPUT")
                if rsi > RSI_PUT_MIN:
                    put_open = True; put_entry = close * (1 + SLIPPAGE_PCT)
                    put_entry_time = ts; put_trough = close
                    last_trade_bar = i; hold_put = False

        # ══════════ PUT MANAGEMENT ═══════════════════════════════════════
        elif put_open:
            if put_trail_hit:
                _close_put(close, ts, "TrailingStop")

            elif put_exit_trig:
                _close_put(close, ts, "ExitTrig->FlipCALL")
                if rsi < RSI_CALL_MAX:  # only flip if CALL entry is valid
                    call_open = True; call_entry = close * (1 + SLIPPAGE_PCT)
                    call_entry_time = ts; call_peak = close
                    last_trade_bar = i; hold_call = False

            elif open_pctb <= PUT_EXIT_TRIG_PREV:
                hold_put = True

            elif hold_put and put_force_now:
                _close_put(close, ts, "ForceExit->FlipCALL")
                if rsi < RSI_CALL_MAX:
                    call_open = True; call_entry = close * (1 + SLIPPAGE_PCT)
                    call_entry_time = ts; call_peak = close
                    last_trade_bar = i; hold_call = False

        # ══════════ FRESH ENTRIES ════════════════════════════════════════
        else:
            if buy_call:
                call_open = True; call_entry = close * (1 + SLIPPAGE_PCT)
                call_entry_time = ts; call_peak = close
                last_trade_bar = i; hold_call = False

            elif buy_put:
                put_open = True; put_entry = close * (1 + SLIPPAGE_PCT)
                put_entry_time = ts; put_trough = close
                last_trade_bar = i; hold_put = False

    # Close any open trade at end of data
    if not rows:
        return {"trades": trades, "final_equity": equity, "df": df}
    last_ts    = rows[-1][0]
    last_close = rows[-1][1]["close"]
    if call_open:
        _close_call(last_close, last_ts, "EndOfData")
    if put_open:
        _close_put(last_close, last_ts, "EndOfData")

    return {"trades": trades, "final_equity": equity, "df": df}


# ══════════════════════════════════════════════════════════════════════════════
#  PERFORMANCE METRICS
# ══════════════════════════════════════════════════════════════════════════════
def compute_metrics(result: dict, initial_capital: float, tf: int = 45) -> dict:
    trades       = result["trades"]
    final_equity = result["final_equity"]
    df           = result["df"]

    if not trades:
        print("WARNING: No trades generated — try --days 365 or check symbol.")
        return {}

    tdf = pd.DataFrame(trades)

    total_trades   = len(tdf)
    winning_trades = int(tdf["win"].sum())
    losing_trades  = total_trades - winning_trades
    win_rate       = winning_trades / total_trades * 100

    gross_profit  = tdf[tdf["pnl"] > 0]["pnl"].sum()
    gross_loss    = tdf[tdf["pnl"] < 0]["pnl"].sum()
    net_pnl       = tdf["pnl"].sum()
    profit_factor = abs(gross_profit / gross_loss) if gross_loss else float("inf")

    avg_win    = tdf[tdf["pnl"] > 0]["pnl"].mean() if winning_trades else 0
    avg_loss   = tdf[tdf["pnl"] < 0]["pnl"].mean() if losing_trades  else 0
    expectancy = (win_rate / 100 * avg_win) + ((1 - win_rate / 100) * avg_loss)

    # Drawdown
    equity_curve = [initial_capital] + list(tdf["equity"].values)
    peak = initial_capital; max_dd = 0; max_dd_pct = 0
    for eq in equity_curve:
        peak = max(peak, eq)
        dd = peak - eq; dd_pct = dd / peak * 100
        if dd > max_dd:
            max_dd = dd; max_dd_pct = dd_pct

    # Sharpe / Sortino
    pnl_series = tdf["pnl_pct"].values / 100
    sharpe     = (pnl_series.mean() / pnl_series.std() * math.sqrt(total_trades)
                  if pnl_series.std() > 0 else 0.0)
    downside   = pnl_series[pnl_series < 0]
    sortino_d  = downside.std() if len(downside) > 1 else 1e-9
    sortino    = pnl_series.mean() / sortino_d * math.sqrt(total_trades)

    # CAGR / Calmar
    days_in_data = (df.index[-1] - df.index[0]).days
    years        = max(days_in_data / 365, 0.01)
    cagr         = ((final_equity / initial_capital) ** (1 / years) - 1) * 100
    calmar       = cagr / max_dd_pct if max_dd_pct else 0

    tdf["bars_held"] = (tdf["exit_time"] - tdf["entry_time"]).dt.total_seconds() / (tf * 60)
    avg_bars_held    = tdf["bars_held"].mean()

    # Streaks
    max_w = max_l = ws = ls = 0
    for w in tdf["win"]:
        if w:  ws += 1; ls = 0
        else:  ls += 1; ws = 0
        max_w = max(max_w, ws); max_l = max(max_l, ls)

    calls = tdf[tdf["type"] == "CALL"]
    puts  = tdf[tdf["type"] == "PUT"]

    return {
        "total_trades":      total_trades,
        "winning_trades":    winning_trades,
        "losing_trades":     losing_trades,
        "win_rate_pct":      round(win_rate, 2),
        "net_pnl":           round(net_pnl, 2),
        "gross_profit":      round(gross_profit, 2),
        "gross_loss":        round(gross_loss, 2),
        "profit_factor":     round(profit_factor, 3),
        "avg_win":           round(avg_win, 2),
        "avg_loss":          round(avg_loss, 2),
        "expectancy":        round(expectancy, 2),
        "max_drawdown":      round(max_dd, 2),
        "max_drawdown_pct":  round(max_dd_pct, 2),
        "sharpe_ratio":      round(sharpe, 3),
        "sortino_ratio":     round(sortino, 3),
        "calmar_ratio":      round(calmar, 3),
        "cagr_pct":          round(cagr, 2),
        "initial_capital":   initial_capital,
        "final_equity":      round(final_equity, 2),
        "total_return_pct":  round((final_equity - initial_capital) / initial_capital * 100, 2),
        "max_consec_wins":   max_w,
        "max_consec_losses": max_l,
        "avg_bars_held":     round(avg_bars_held, 1),
        "call_trades":       len(calls),
        "call_wins":         int(calls["win"].sum()) if len(calls) else 0,
        "put_trades":        len(puts),
        "put_wins":          int(puts["win"].sum()) if len(puts) else 0,
        "data_start":        str(df.index[0].date()),
        "data_end":          str(df.index[-1].date()),
        "tf_min":            tf,
        "tdf":               tdf,
    }


# ══════════════════════════════════════════════════════════════════════════════
#  PRINT REPORT
# ══════════════════════════════════════════════════════════════════════════════
def print_report(m: dict, symbol: str, days: int):
    tdf = m.pop("tdf")
    tf  = m.get("tf_min", 45)
    W = 70

    print("\n" + "=" * W)
    print(f"  BACKTEST REPORT  --  {symbol}  ({tf}-min | Bollinger %B v4)")
    print(f"  Filters: RSI({RSI_PERIOD}) | ATR>{MIN_ATR_PCT*100:.1f}% | Trail-Stop {TRAIL_STOP_PCT*100:.1f}%")
    print("=" * W)

    overview = [
        ["Symbol",          symbol],
        ["Data Period",     f"{m['data_start']}  ->  {m['data_end']}"],
        ["Lookback",        f"{days} days"],
        ["Initial Capital", f"Rs {m['initial_capital']:>12,.0f}"],
        ["Final Equity",    f"Rs {m['final_equity']:>12,.2f}"],
        ["Net P&L",         f"Rs {m['net_pnl']:>12,.2f}"],
        ["Total Return",    f"{m['total_return_pct']:>+.2f}%"],
        ["CAGR",            f"{m['cagr_pct']:>+.2f}%"],
    ]
    print("\n[Overview]")
    print(tabulate(overview, tablefmt="rounded_outline"))

    cwr = f"{m['call_wins']}/{m['call_trades']}" if m['call_trades'] else "0/0"
    pwr = f"{m['put_wins']}/{m['put_trades']}"   if m['put_trades']  else "0/0"
    trade_stats = [
        ["Total Trades",        m["total_trades"]],
        ["  Winning",           m["winning_trades"]],
        ["  Losing",            m["losing_trades"]],
        ["Win Rate",            f"{m['win_rate_pct']:.2f}%"],
        ["  CALL  Wins/Total",  cwr],
        ["  PUT   Wins/Total",  pwr],
        ["Avg Win  (Rs)",       f"Rs {m['avg_win']:>10,.2f}"],
        ["Avg Loss (Rs)",       f"Rs {m['avg_loss']:>10,.2f}"],
        ["Profit Factor",       f"{m['profit_factor']:.3f}"],
        ["Expectancy / Trade",  f"Rs {m['expectancy']:>10,.2f}"],
        ["Avg Hold (bars/hrs)", f"{m['avg_bars_held']} bars  (~{m['avg_bars_held'] * m['tf_min'] / 60:.1f} hrs)"],
        ["Max Consec. Wins",    m["max_consec_wins"]],
        ["Max Consec. Losses",  m["max_consec_losses"]],
    ]
    print("\n[Trade Statistics]")
    print(tabulate(trade_stats, tablefmt="rounded_outline"))

    risk_stats = [
        ["Max Drawdown",    f"Rs {m['max_drawdown']:,.2f}  ({m['max_drawdown_pct']:.2f}%)"],
        ["Sharpe Ratio",    f"{m['sharpe_ratio']:.3f}"],
        ["Sortino Ratio",   f"{m['sortino_ratio']:.3f}"],
        ["Calmar Ratio",    f"{m['calmar_ratio']:.3f}"],
        ["Gross Profit",    f"Rs {m['gross_profit']:>12,.2f}"],
        ["Gross Loss",      f"Rs {m['gross_loss']:>12,.2f}"],
    ]
    print("\n[Risk Metrics]")
    print(tabulate(risk_stats, tablefmt="rounded_outline"))

    # Exit reason breakdown
    reasons = tdf.groupby("reason").agg(
        Count=("pnl","count"),
        TotalPnL=("pnl","sum"),
        Wins=("win","sum")
    ).reset_index()
    reasons["WinRate%"] = (reasons["Wins"] / reasons["Count"] * 100).round(1)
    reasons["TotalPnL"] = reasons["TotalPnL"].round(2)
    print("\n[Exit Reason Breakdown]")
    print(tabulate(reasons, headers="keys", tablefmt="rounded_outline",
                   showindex=False, floatfmt=".2f"))

    # Last 25 trades
    last25 = tdf.tail(25)[["type","reason","entry_time","exit_time",
                            "entry_px","exit_px","pnl","pnl_pct","win"]].copy()
    last25.columns = ["Type","Reason","Entry Time","Exit Time",
                      "Entry Rs","Exit Rs","PnL Rs","PnL%","Win?"]
    last25["Win?"] = last25["Win?"].map({True: "YES", False: "NO"})
    print("\n[Last 25 Trades]")
    print(tabulate(last25, headers="keys", tablefmt="rounded_outline",
                   showindex=False, floatfmt=".2f"))

    print("\n" + "=" * W)


# ══════════════════════════════════════════════════════════════════════════════
#  MAIN
# ══════════════════════════════════════════════════════════════════════════════
def main():
    args   = parse_args()
    symbol = args.resolved_symbol
    days   = args.days
    capital = args.capital
    bb_len  = args.bb_len
    bb_mult = args.bb_mult
    cooldown = args.cooldown
    tf       = args.tf

    print("\n" + "=" * 60)
    print("  Bollinger %B Strategy Backtester  v4")
    print("=" * 60)
    print(f"  Symbol   : {symbol}")
    print(f"  Timeframe: {tf} min")
    print(f"  Lookback : {days} days")
    print(f"  Capital  : Rs {capital:,.0f}")
    print(f"  BB       : length={bb_len}  mult={bb_mult}")
    print(f"  Cooldown : {cooldown} bars")
    print(f"  RSI      : CALL<{RSI_CALL_MAX}  PUT>{RSI_PUT_MIN}")
    print(f"  Trail SL : {TRAIL_STOP_PCT*100:.1f}%")
    print("=" * 60 + "\n")

    kite = zerodha_login()
    tokens_list, display_sym = get_instrument_token(kite, symbol)

    print(f"\nFetching {days} days of data for {display_sym} [{tf}-min] ...")
    df = fetch_ohlc(kite, tokens_list, days=days, tf=tf)
    print(f"Loaded {len(df)} bars  ({df.index[0].date()} -> {df.index[-1].date()})")

    print("\nCalculating indicators ...")
    df = calculate_indicators(df, bb_len, bb_mult)

    print("Running backtest ...")
    result  = run_backtest(df, capital, cooldown)
    metrics = compute_metrics(result, capital, tf=tf)

    if metrics:
        print_report(metrics, display_sym, days)


if __name__ == "__main__":
    main()
