"""
╔══════════════════════════════════════════════════════════════════════════════╗
║  STOCK ANALYSIS TOOL  —  Indian Cash Market (NSE/BSE)                      ║
║  Fundamental + Technical + News + Risk Assessment                           ║
║  Data: Zerodha Kite API + yfinance + Yahoo Finance News                     ║
╚══════════════════════════════════════════════════════════════════════════════╝

Usage:
    python stock_analysis.py RELIANCE
    python stock_analysis.py TCS
    python stock_analysis.py INFY
    python stock_analysis.py HDFCBANK

Install:
    pip install kiteconnect pyotp pandas numpy tabulate requests yfinance \
                pandas-ta colorama --break-system-packages
"""

import os, sys, time, math, warnings
from datetime import datetime, timedelta, timezone
import subprocess

warnings.filterwarnings("ignore")

# ── auto-install ────────────────────────────────────────────────────────────
PACKAGES = ["kiteconnect", "pyotp", "pandas", "numpy", "tabulate",
            "requests", "yfinance", "pandas_ta", "colorama"]

def _pip(pkg):
    try:
        __import__(pkg.split("[")[0].replace("-", "_"))
    except ImportError:
        print(f"  Installing {pkg}...")
        subprocess.run([sys.executable, "-m", "pip", "install", pkg,
                        "--quiet", "--break-system-packages"], check=True)

print("Checking dependencies...")
for p in PACKAGES:
    _pip(p)

import requests
import pyotp
import pandas as pd
import numpy as np
import yfinance as yf
import pandas_ta as ta
from kiteconnect import KiteConnect
from tabulate import tabulate
from colorama import Fore, Style, init as colorama_init

colorama_init(autoreset=True)

# ══════════════════════════════════════════════════════════════════════════════
#  CREDENTIALS  (same as your backtest script)
# ══════════════════════════════════════════════════════════════════════════════
API_KEY    = os.getenv("KITE_API_KEY",  "4tl671rr7bwffw7b")
API_SECRET = os.getenv("KITE_SECRET",   "4gesk7v5vsbx9us4t8j3gh229zwzwf9t")
USER_ID    = os.getenv("KITE_USER_ID",  "QWK225")
PASSWORD   = os.getenv("KITE_PASSWORD", "Dec2025!")
TOTP_KEY   = os.getenv("KITE_TOTP_KEY", "VV2ZTNC3LG4V7EG7ECFLJIURPGVERJL7")

IST = timezone(timedelta(hours=5, minutes=30))

# ══════════════════════════════════════════════════════════════════════════════
#  HELPERS
# ══════════════════════════════════════════════════════════════════════════════
def hdr(title: str, width: int = 72):
    print(f"\n{Fore.CYAN}{'═' * width}")
    print(f"  {title}")
    print(f"{'═' * width}{Style.RESET_ALL}")

def sub(title: str):
    print(f"\n{Fore.YELLOW}  ▶  {title}{Style.RESET_ALL}")

def good(msg): return f"{Fore.GREEN}{msg}{Style.RESET_ALL}"
def bad(msg):  return f"{Fore.RED}{msg}{Style.RESET_ALL}"
def warn(msg): return f"{Fore.YELLOW}{msg}{Style.RESET_ALL}"
def bold(msg): return f"{Style.BRIGHT}{msg}{Style.RESET_ALL}"

def rating_color(score: float, thresholds: tuple) -> str:
    """thresholds = (bad_max, warn_max) — above warn_max is good."""
    if score <= thresholds[0]:   return bad(f"{score:.2f}")
    elif score <= thresholds[1]: return warn(f"{score:.2f}")
    else:                        return good(f"{score:.2f}")

def safe(val, fmt=".2f", fallback="N/A"):
    try:
        if val is None or (isinstance(val, float) and math.isnan(val)):
            return fallback
        return format(float(val), fmt)
    except Exception:
        return str(val) if val else fallback

def crore(val):
    try:
        return f"₹{float(val)/1e7:,.0f} Cr"
    except Exception:
        return "N/A"

# ══════════════════════════════════════════════════════════════════════════════
#  ZERODHA LOGIN  (exact same pattern as your backtest script)
# ══════════════════════════════════════════════════════════════════════════════
def zerodha_login() -> KiteConnect:
    print("  Logging in to Zerodha Kite...")
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
    print(good("  ✓ Zerodha login successful!"))
    return kite


def get_kite_price(kite: KiteConnect, symbol: str) -> dict:
    """Get live quote from Zerodha for NSE cash market."""
    try:
        q = kite.quote([f"NSE:{symbol}"])
        d = q.get(f"NSE:{symbol}", {})
        ohlc = d.get("ohlc", {})
        return {
            "ltp":       d.get("last_price"),
            "open":      ohlc.get("open"),
            "high":      ohlc.get("high"),
            "low":       ohlc.get("low"),
            "close":     ohlc.get("close"),
            "volume":    d.get("volume"),
            "buy_qty":   d.get("buy_quantity"),
            "sell_qty":  d.get("sell_quantity"),
            "avg_price": d.get("average_price"),
            "change":    d.get("net_change"),
            "change_pct": (d.get("net_change", 0) / ohlc.get("close", 1) * 100
                           if ohlc.get("close") else None),
        }
    except Exception as e:
        print(warn(f"  ⚠ Kite quote failed: {e}"))
        return {}


def get_kite_history(kite: KiteConnect, symbol: str, days: int = 365) -> pd.DataFrame:
    """Fetch daily OHLCV from Zerodha for NSE equities."""
    try:
        instruments = kite.instruments("NSE")
        df_inst = pd.DataFrame(instruments)
        row = df_inst[
            (df_inst["tradingsymbol"] == symbol) &
            (df_inst["instrument_type"] == "EQ")
        ]
        if row.empty:
            print(warn(f"  ⚠ {symbol} not found on NSE via Kite"))
            return pd.DataFrame()
        token = int(row.iloc[0]["instrument_token"])

        end   = datetime.now(IST)
        start = end - timedelta(days=days)
        all_c = []
        chunk = start
        while chunk < end:
            chunk_end = min(chunk + timedelta(days=58), end)
            try:
                candles = kite.historical_data(
                    token,
                    chunk.strftime("%Y-%m-%d %H:%M:%S"),
                    chunk_end.strftime("%Y-%m-%d %H:%M:%S"),
                    "day",
                )
                all_c.extend(candles)
            except Exception as e:
                print(warn(f"  ⚠ Chunk {chunk.date()} failed: {e}"))
            chunk = chunk_end + timedelta(days=1)
            time.sleep(0.35)

        if not all_c:
            return pd.DataFrame()

        df = pd.DataFrame(all_c)
        df["date"] = pd.to_datetime(df["date"]).dt.tz_localize(None)
        df = df.set_index("date").sort_index().drop_duplicates()
        print(good(f"  ✓ Kite history: {len(df)} days loaded"))
        return df

    except Exception as e:
        print(warn(f"  ⚠ Kite history failed: {e}"))
        return pd.DataFrame()


# ══════════════════════════════════════════════════════════════════════════════
#  YFINANCE — FUNDAMENTAL DATA
# ══════════════════════════════════════════════════════════════════════════════
def get_yf_data(symbol: str) -> dict:
    """Fetch comprehensive fundamental data from Yahoo Finance."""
    ticker_ns = symbol + ".NS"   # NSE
    ticker_bo = symbol + ".BO"   # BSE fallback

    ticker = yf.Ticker(ticker_ns)
    info   = ticker.info or {}

    # If NSE failed, try BSE
    if not info.get("regularMarketPrice") and not info.get("currentPrice"):
        ticker = yf.Ticker(ticker_bo)
        info   = ticker.info or {}

    hist_1y  = ticker.history(period="1y",  auto_adjust=True)
    hist_5y  = ticker.history(period="5y",  auto_adjust=True)
    hist_10y = ticker.history(period="10y", auto_adjust=True)

    try: news = ticker.news or []
    except Exception: news = []

    try: financials = ticker.financials
    except Exception: financials = pd.DataFrame()

    try: balance_sheet = ticker.balance_sheet
    except Exception: balance_sheet = pd.DataFrame()

    try: cash_flow = ticker.cashflow
    except Exception: cash_flow = pd.DataFrame()

    try: institutional_holders = ticker.institutional_holders
    except Exception: institutional_holders = pd.DataFrame()

    try: dividends = ticker.dividends
    except Exception: dividends = pd.Series()

    return {
        "info":                 info,
        "hist_1y":              hist_1y,
        "hist_5y":              hist_5y,
        "hist_10y":             hist_10y,
        "news":                 news,
        "financials":           financials,
        "balance_sheet":        balance_sheet,
        "cash_flow":            cash_flow,
        "institutional_holders": institutional_holders,
        "dividends":            dividends,
    }


# ══════════════════════════════════════════════════════════════════════════════
#  TECHNICAL INDICATORS
# ══════════════════════════════════════════════════════════════════════════════
def compute_technicals(df: pd.DataFrame) -> dict:
    """Compute all major technical indicators on daily OHLCV."""
    if df.empty or len(df) < 30:
        return {}

    c = df["close"]
    h = df["high"]
    l = df["low"]
    v = df["volume"]

    results = {}

    # ── Moving Averages ──────────────────────────────────────────────────────
    for p in [20, 50, 100, 200]:
        results[f"sma_{p}"] = c.rolling(p).mean().iloc[-1] if len(c) >= p else None
        results[f"ema_{p}"] = c.ewm(span=p, adjust=False).mean().iloc[-1]

    # ── RSI ──────────────────────────────────────────────────────────────────
    delta = c.diff()
    gain  = delta.clip(lower=0).rolling(14).mean()
    loss  = (-delta.clip(upper=0)).rolling(14).mean()
    rs    = gain / loss.replace(0, np.nan)
    results["rsi_14"] = (100 - 100 / (1 + rs)).iloc[-1]

    # ── MACD ─────────────────────────────────────────────────────────────────
    ema12  = c.ewm(span=12, adjust=False).mean()
    ema26  = c.ewm(span=26, adjust=False).mean()
    macd   = ema12 - ema26
    signal = macd.ewm(span=9, adjust=False).mean()
    hist   = macd - signal
    results["macd"]        = macd.iloc[-1]
    results["macd_signal"] = signal.iloc[-1]
    results["macd_hist"]   = hist.iloc[-1]
    results["macd_crossover"] = (
        "BULLISH" if (hist.iloc[-1] > 0 and hist.iloc[-2] <= 0)
        else "BEARISH" if (hist.iloc[-1] < 0 and hist.iloc[-2] >= 0)
        else "NEUTRAL"
    )

    # ── Bollinger Bands ──────────────────────────────────────────────────────
    bb_mid   = c.rolling(20).mean()
    bb_std   = c.rolling(20).std(ddof=0)
    bb_upper = bb_mid + 2 * bb_std
    bb_lower = bb_mid - 2 * bb_std
    bb_pct_b = (c - bb_lower) / (bb_upper - bb_lower)
    bb_bw    = (bb_upper - bb_lower) / bb_mid * 100

    results["bb_upper"]  = bb_upper.iloc[-1]
    results["bb_mid"]    = bb_mid.iloc[-1]
    results["bb_lower"]  = bb_lower.iloc[-1]
    results["bb_pct_b"]  = bb_pct_b.iloc[-1]
    results["bb_bwidth"] = bb_bw.iloc[-1]

    # ── Stochastic ───────────────────────────────────────────────────────────
    low14  = l.rolling(14).min()
    high14 = h.rolling(14).max()
    k = (c - low14) / (high14 - low14) * 100
    d = k.rolling(3).mean()
    results["stoch_k"] = k.iloc[-1]
    results["stoch_d"] = d.iloc[-1]

    # ── ADX ──────────────────────────────────────────────────────────────────
    try:
        adx_df = ta.adx(h, l, c, length=14)
        if adx_df is not None and not adx_df.empty:
            results["adx"]    = adx_df.iloc[-1, 0]
            results["dmi_plus"]  = adx_df.iloc[-1, 1]
            results["dmi_minus"] = adx_df.iloc[-1, 2]
    except Exception:
        results["adx"] = None

    # ── ATR ──────────────────────────────────────────────────────────────────
    tr = pd.concat([
        h - l,
        (h - c.shift()).abs(),
        (l - c.shift()).abs()
    ], axis=1).max(axis=1)
    results["atr_14"]     = tr.rolling(14).mean().iloc[-1]
    results["atr_pct"]    = results["atr_14"] / c.iloc[-1] * 100

    # ── Volume Analysis ──────────────────────────────────────────────────────
    results["vol_20d_avg"]  = v.rolling(20).mean().iloc[-1]
    results["vol_ratio"]    = v.iloc[-1] / results["vol_20d_avg"] if results["vol_20d_avg"] else None
    results["obv"]          = (v * np.sign(c.diff())).cumsum().iloc[-1]

    # ── Support / Resistance (52-week) ───────────────────────────────────────
    results["52w_high"]  = h.tail(252).max()
    results["52w_low"]   = l.tail(252).min()
    results["dist_52wh"] = (c.iloc[-1] - results["52w_high"]) / results["52w_high"] * 100
    results["dist_52wl"] = (c.iloc[-1] - results["52w_low"])  / results["52w_low"]  * 100

    # ── Trend Classification ──────────────────────────────────────────────────
    ltp = c.iloc[-1]
    s50  = results.get("sma_50")
    s200 = results.get("sma_200")
    if s50 and s200:
        if ltp > s50 > s200:
            results["trend"] = "STRONG UPTREND"
        elif ltp > s50 and s50 < s200:
            results["trend"] = "RECOVERING"
        elif ltp < s50 < s200:
            results["trend"] = "STRONG DOWNTREND"
        elif ltp < s50 and s50 > s200:
            results["trend"] = "WEAK / CORRECTION"
        else:
            results["trend"] = "SIDEWAYS"
    else:
        results["trend"] = "INSUFFICIENT DATA"

    # ── Golden / Death Cross ─────────────────────────────────────────────────
    if s50 and s200:
        prev_sma50  = c.rolling(50).mean().iloc[-2]
        prev_sma200 = c.rolling(200).mean().iloc[-2]
        if s50 > s200 and prev_sma50 <= prev_sma200:
            results["cross"] = "🟡 GOLDEN CROSS (Bullish)"
        elif s50 < s200 and prev_sma50 >= prev_sma200:
            results["cross"] = "💀 DEATH CROSS (Bearish)"
        else:
            results["cross"] = "None recently"
    else:
        results["cross"] = "N/A"

    # ── CAGR (price return) ───────────────────────────────────────────────────
    if len(c) >= 252:
        results["cagr_1y"] = (c.iloc[-1] / c.iloc[-252] - 1) * 100
    if len(c) >= 252 * 3:
        results["cagr_3y"] = ((c.iloc[-1] / c.iloc[-252*3]) ** (1/3) - 1) * 100
    if len(c) >= 252 * 5:
        results["cagr_5y"] = ((c.iloc[-1] / c.iloc[-252*5]) ** (1/5) - 1) * 100

    # ── Volatility ────────────────────────────────────────────────────────────
    log_ret = np.log(c / c.shift()).dropna()
    results["volatility_annual"] = log_ret.rolling(252).std().iloc[-1] * math.sqrt(252) * 100

    return results


# ══════════════════════════════════════════════════════════════════════════════
#  FUNDAMENTAL SCORING
# ══════════════════════════════════════════════════════════════════════════════
def score_fundamental(info: dict) -> list:
    """
    Return a list of [metric, value, benchmark, score, verdict] rows.
    Score: GREEN = good, YELLOW = average, RED = bad
    """
    rows = []

    def add(name, val, benchmark, verdict_fn, note="", display_override=None):
        if display_override is not None:
            v_str = display_override
        else:
            v_str = safe(val) if isinstance(val, (int, float)) else str(val or "N/A")
        verdict, colour = verdict_fn(val)
        display_val = colour(v_str) if colour else v_str
        rows.append([name, display_val, benchmark, verdict, note])

    pe  = info.get("trailingPE") or info.get("forwardPE")
    pb  = info.get("priceToBook")
    ps  = info.get("priceToSalesTrailing12Months")
    de  = info.get("debtToEquity")
    roe = info.get("returnOnEquity")
    roa = info.get("returnOnAssets")
    cr  = info.get("currentRatio")
    eps = info.get("trailingEps") or info.get("forwardEps")
    eps_growth = info.get("earningsGrowth")
    rev_growth = info.get("revenueGrowth")
    gm  = info.get("grossMargins")
    om  = info.get("operatingMargins")
    pm  = info.get("profitMargins")
    dy  = info.get("dividendYield")
    payout = info.get("payoutRatio")
    beta   = info.get("beta")
    fcf    = info.get("freeCashflow")
    mktcap = info.get("marketCap")

    # PE
    def pe_v(v):
        if v is None: return ("N/A", None)
        if v < 0:     return ("⚠ Negative EPS", bad)
        if v < 15:    return ("✅ Undervalued", good)
        if v < 25:    return ("✅ Fair", good)
        if v < 40:    return ("🟡 Slightly High", warn)
        return ("🔴 Overvalued", bad)
    add("P/E Ratio (TTM)", pe, "< 25 = fair; > 40 = expensive", pe_v,
        "For growth stocks, up to 40 is OK if EPS growth > 20%")

    # Forward PE
    fpe = info.get("forwardPE")
    def fpe_v(v):
        if v is None: return ("N/A", None)
        if v < 20: return ("✅ Attractive", good)
        if v < 35: return ("🟡 Moderate", warn)
        return ("🔴 High", bad)
    add("P/E Ratio (Forward)", fpe, "< 20 = cheap; > 35 = rich", fpe_v)

    # PB
    def pb_v(v):
        if v is None: return ("N/A", None)
        if v < 1:    return ("✅ Below Book", good)
        if v < 3:    return ("✅ Reasonable", good)
        if v < 6:    return ("🟡 Premium", warn)
        return ("🔴 Very High", bad)
    add("P/B Ratio", pb, "< 3 = good; < 1 = bargain", pb_v)

    # PS
    def ps_v(v):
        if v is None: return ("N/A", None)
        if v < 2:    return ("✅ Cheap", good)
        if v < 5:    return ("✅ Fair", good)
        if v < 10:   return ("🟡 Premium", warn)
        return ("🔴 Very Expensive", bad)
    add("P/S Ratio", ps, "< 5 = fair; > 10 = expensive", ps_v)

    # D/E
    def de_v(v):
        if v is None: return ("N/A", None)
        if v < 30:   return ("✅ Low Debt", good)
        if v < 100:  return ("✅ Manageable", good)
        if v < 200:  return ("🟡 High Debt", warn)
        return ("🔴 Very High Debt", bad)
    add("Debt / Equity (%)", de, "< 100% = safe; > 200% = risky", de_v,
        "Yfinance reports D/E as %. < 1x actual ratio = good")

    # ROE
    def roe_v(v):
        if v is None: return ("N/A", None)
        v *= 100
        if v >= 20:  return ("✅ Excellent", good)
        if v >= 12:  return ("✅ Good", good)
        if v >= 8:   return ("🟡 Average", warn)
        return ("🔴 Poor", bad)
    add("ROE (%)", roe * 100 if roe else None, "> 15% = good; > 20% = excellent", roe_v)

    # ROA
    def roa_v(v):
        if v is None: return ("N/A", None)
        v *= 100
        if v >= 10:  return ("✅ Excellent", good)
        if v >= 5:   return ("✅ Good", good)
        if v >= 2:   return ("🟡 Average", warn)
        return ("🔴 Poor", bad)
    add("ROA (%)", roa * 100 if roa else None, "> 5% = good; > 10% = excellent", roa_v)

    # Current Ratio
    def cr_v(v):
        if v is None: return ("N/A", None)
        if 1.5 <= v <= 3: return ("✅ Healthy", good)
        if 1.0 <= v < 1.5: return ("🟡 Tight", warn)
        if v > 3:   return ("🟡 Too High (idle cash?)", warn)
        return ("🔴 Liquidity Risk", bad)
    add("Current Ratio", cr, "1.5–3 = healthy; < 1 = risky", cr_v)

    # EPS Growth
    def eg_v(v):
        if v is None: return ("N/A", None)
        v *= 100
        if v >= 20:  return ("✅ Strong Growth", good)
        if v >= 10:  return ("✅ Good Growth", good)
        if v >= 0:   return ("🟡 Slow Growth", warn)
        return ("🔴 Earnings Decline", bad)
    add("EPS Growth (YoY %)", eps_growth * 100 if eps_growth else None,
        "> 15% = good; > 25% = excellent", eg_v)

    # Revenue Growth
    def rg_v(v):
        if v is None: return ("N/A", None)
        v *= 100
        if v >= 15:  return ("✅ Strong", good)
        if v >= 8:   return ("✅ Moderate", good)
        if v >= 0:   return ("🟡 Slow", warn)
        return ("🔴 Declining Revenue", bad)
    add("Revenue Growth (YoY %)", rev_growth * 100 if rev_growth else None,
        "> 10% = healthy; > 20% = excellent", rg_v)

    # Gross Margin
    def gm_v(v):
        if v is None: return ("N/A", None)
        v *= 100
        if v >= 40:  return ("✅ High Margin", good)
        if v >= 20:  return ("✅ Decent", good)
        if v >= 10:  return ("🟡 Thin", warn)
        return ("🔴 Very Thin", bad)
    add("Gross Margin (%)", gm * 100 if gm else None, "> 20% = decent; > 40% = great", gm_v)

    # Operating Margin
    def om_v(v):
        if v is None: return ("N/A", None)
        v *= 100
        if v >= 20:  return ("✅ Excellent", good)
        if v >= 10:  return ("✅ Good", good)
        if v >= 5:   return ("🟡 Average", warn)
        return ("🔴 Poor / Loss", bad)
    add("Operating Margin (%)", om * 100 if om else None, "> 10% = good; > 20% = excellent", om_v)

    # Net Margin
    def pm_v(v):
        if v is None: return ("N/A", None)
        v *= 100
        if v >= 15:  return ("✅ Strong", good)
        if v >= 8:   return ("✅ Good", good)
        if v >= 3:   return ("🟡 Thin", warn)
        return ("🔴 Very Thin / Loss", bad)
    add("Net Profit Margin (%)", pm * 100 if pm else None, "> 8% = good; > 15% = great", pm_v)

    # Dividend Yield
    def dy_v(v):
        if v is None: return ("No Dividend", warn)
        v *= 100
        if 1 <= v <= 5: return ("✅ Good Yield", good)
        if v < 1:       return ("🟡 Low Yield", warn)
        return ("🟡 Very High (check payout)", warn)
    add("Dividend Yield (%)", dy * 100 if dy else None, "1–5% = healthy; >6% check payout ratio", dy_v)

    # Beta
    def beta_v(v):
        if v is None: return ("N/A", None)
        if v < 0.8:   return ("✅ Low Volatility", good)
        if v <= 1.2:  return ("✅ Market-Like", good)
        if v <= 1.8:  return ("🟡 High Volatility", warn)
        return ("🔴 Very Volatile", bad)
    add("Beta", beta, "< 1 = less volatile; > 1.5 = risky", beta_v,
        "Beta vs Nifty 50")

    # Free Cash Flow
    def fcf_v(v):
        if v is None: return ("N/A", None)
        if v > 0:    return ("✅ Positive FCF", good)
        return ("🔴 Negative FCF", bad)
    add("Free Cash Flow", fcf,
        "Positive = company generates real cash", fcf_v,
        display_override=crore(fcf) if fcf else None)

    return rows


# ══════════════════════════════════════════════════════════════════════════════
#  OVERALL INVESTMENT SCORE
# ══════════════════════════════════════════════════════════════════════════════
def compute_investment_score(info: dict, tech: dict) -> tuple:
    """
    Returns (score_out_of_100, verdict, detailed_breakdown).
    """
    score = 0
    max_s = 100
    details = []

    def s(name, pts, earned, reason=""):
        details.append((name, earned, pts, reason))
        return earned

    # ── Valuation (30 pts) ────────────────────────────────────────────────────
    pe = info.get("trailingPE") or info.get("forwardPE")
    if pe:
        if pe < 15:   score += s("P/E Attractive",  10, 10)
        elif pe < 25: score += s("P/E Fair",         10, 7)
        elif pe < 40: score += s("P/E High",         10, 4)
        else:         score += s("P/E Very High",    10, 1)

    pb = info.get("priceToBook")
    if pb:
        if pb < 2:    score += s("P/B Attractive",  10, 10)
        elif pb < 4:  score += s("P/B Moderate",    10, 7)
        elif pb < 8:  score += s("P/B High",        10, 3)
        else:         score += s("P/B Very High",   10, 1)

    roe = info.get("returnOnEquity")
    if roe:
        r = roe * 100
        if r >= 20:   score += s("ROE Excellent",   10, 10)
        elif r >= 12: score += s("ROE Good",        10, 7)
        elif r >= 7:  score += s("ROE Average",     10, 4)
        else:         score += s("ROE Poor",        10, 1)

    # ── Growth (25 pts) ───────────────────────────────────────────────────────
    eg = info.get("earningsGrowth")
    if eg:
        e = eg * 100
        if e >= 25:   score += s("EPS Growth Strong",  10, 10)
        elif e >= 12: score += s("EPS Growth Good",    10, 7)
        elif e >= 0:  score += s("EPS Growth Slow",    10, 3)
        else:         score += s("EPS Declining",      10, 0)

    rg = info.get("revenueGrowth")
    if rg:
        r = rg * 100
        if r >= 15:   score += s("Rev Growth Strong",  8, 8)
        elif r >= 8:  score += s("Rev Growth Good",    8, 5)
        elif r >= 0:  score += s("Rev Growth Slow",    8, 2)
        else:         score += s("Rev Declining",      8, 0)

    pm = info.get("profitMargins")
    if pm:
        p = pm * 100
        if p >= 15:   score += s("Net Margin Excellent", 7, 7)
        elif p >= 8:  score += s("Net Margin Good",      7, 5)
        elif p >= 3:  score += s("Net Margin Thin",      7, 2)
        else:         score += s("Net Margin Negative",  7, 0)

    # ── Safety (25 pts) ───────────────────────────────────────────────────────
    de = info.get("debtToEquity")
    if de is not None:
        if de < 30:   score += s("Debt Very Low",    10, 10)
        elif de < 80: score += s("Debt Low",         10, 8)
        elif de < 150: score += s("Debt Moderate",   10, 5)
        elif de < 250: score += s("Debt High",       10, 2)
        else:          score += s("Debt Very High",  10, 0)

    cr = info.get("currentRatio")
    if cr:
        if 1.5 <= cr <= 4: score += s("Liquidity Healthy",  8, 8)
        elif 1 <= cr < 1.5: score += s("Liquidity Tight",   8, 4)
        else:               score += s("Liquidity Poor",    8, 0)

    fcf = info.get("freeCashflow")
    if fcf is not None:
        if fcf > 0:   score += s("FCF Positive",   7, 7)
        else:         score += s("FCF Negative",   7, 0)

    # ── Technical (20 pts) ────────────────────────────────────────────────────
    rsi = tech.get("rsi_14")
    if rsi:
        if 40 <= rsi <= 65: score += s("RSI Healthy",    5, 5)
        elif rsi < 30:      score += s("RSI Oversold",   5, 4, "Potential bounce")
        elif rsi > 75:      score += s("RSI Overbought", 5, 1, "Risk of pullback")
        else:               score += s("RSI Normal",     5, 3)

    trend = tech.get("trend", "")
    if "STRONG UPTREND" in trend:   score += s("Trend Strong Up",  5, 5)
    elif "RECOVERING" in trend:     score += s("Trend Recovering", 5, 3)
    elif "SIDEWAYS" in trend:       score += s("Trend Sideways",   5, 3)
    elif "CORRECTION" in trend:     score += s("Trend Weak",       5, 2)
    else:                           score += s("Trend Down",       5, 0)

    macd_c = tech.get("macd_crossover", "")
    if macd_c == "BULLISH":         score += s("MACD Bullish",    5, 5)
    elif macd_c == "NEUTRAL":       score += s("MACD Neutral",    5, 3)
    else:                           score += s("MACD Bearish",    5, 1)

    adx = tech.get("adx")
    if adx:
        if adx >= 25: score += s("ADX Strong Trend",  5, 5)
        else:         score += s("ADX Weak Trend",    5, 2)

    # ── Verdict ───────────────────────────────────────────────────────────────
    if score >= 75:    verdict = good("🟢 STRONG BUY")
    elif score >= 60:  verdict = good("✅ BUY")
    elif score >= 45:  verdict = warn("🟡 HOLD / WATCH")
    elif score >= 30:  verdict = warn("⚠ WEAK — Caution")
    else:              verdict = bad("🔴 AVOID / SELL")

    return score, verdict, details


# ══════════════════════════════════════════════════════════════════════════════
#  PRINT SECTIONS
# ══════════════════════════════════════════════════════════════════════════════
def print_company_overview(info: dict, symbol: str):
    hdr(f"COMPANY OVERVIEW  —  {symbol}")
    rows = [
        ["Company Name",    info.get("longName", symbol)],
        ["Sector",          info.get("sector", "N/A")],
        ["Industry",        info.get("industry", "N/A")],
        ["Exchange",        info.get("exchange", "NSE")],
        ["Market Cap",      crore(info.get("marketCap"))],
        ["Enterprise Value",crore(info.get("enterpriseValue"))],
        ["Employees",       f"{info.get('fullTimeEmployees', 'N/A'):,}" 
                            if info.get("fullTimeEmployees") else "N/A"],
        ["Website",         info.get("website", "N/A")],
        ["52-Week High",    f"₹{safe(info.get('fiftyTwoWeekHigh'))}"],
        ["52-Week Low",     f"₹{safe(info.get('fiftyTwoWeekLow'))}"],
    ]
    print(tabulate(rows, tablefmt="rounded_outline"))
    desc = info.get("longBusinessSummary", "")
    if desc:
        print(f"\n  📝 {desc[:400]}{'...' if len(desc) > 400 else ''}")


def print_price_info(ltp: dict, info: dict):
    hdr("LIVE PRICE (Zerodha Kite)")
    price  = ltp.get("ltp") or info.get("currentPrice") or info.get("regularMarketPrice")
    chg    = ltp.get("change") or 0
    chg_p  = ltp.get("change_pct") or 0
    chg_str = (good(f"+{chg:.2f} (+{chg_p:.2f}%)") if chg >= 0
               else bad(f"{chg:.2f} ({chg_p:.2f}%)"))

    rows = [
        ["LTP",             f"₹{safe(price)}" if price else "N/A"],
        ["Change",          chg_str],
        ["Open",            f"₹{safe(ltp.get('open') or info.get('open'))}"],
        ["High",            f"₹{safe(ltp.get('high') or info.get('dayHigh'))}"],
        ["Low",             f"₹{safe(ltp.get('low') or info.get('dayLow'))}"],
        ["Prev Close",      f"₹{safe(ltp.get('close') or info.get('previousClose'))}"],
        ["Volume",          f"{(ltp.get('volume') or info.get('volume') or 0):,}"],
        ["Avg Volume (3M)", f"{info.get('averageVolume3Month', 0):,}"],
    ]
    print(tabulate(rows, tablefmt="rounded_outline"))


def print_fundamentals(info: dict):
    hdr("FUNDAMENTAL ANALYSIS")
    rows = score_fundamental(info)
    headers = ["Metric", "Value", "Benchmark", "Verdict", "Note"]
    print(tabulate(rows, headers=headers, tablefmt="rounded_outline"))


def print_technicals(tech: dict, ltp: float):
    hdr("TECHNICAL ANALYSIS  (Daily Chart)")

    # Moving averages
    sub("Moving Averages")
    ma_rows = []
    for p in [20, 50, 100, 200]:
        sma = tech.get(f"sma_{p}")
        ema = tech.get(f"ema_{p}")
        if sma:
            pos = (good("▲ Above") if ltp > sma else bad("▼ Below"))
            ma_rows.append([f"SMA {p}", f"₹{safe(sma)}", pos])
        if ema:
            pos = (good("▲ Above") if ltp > ema else bad("▼ Below"))
            ma_rows.append([f"EMA {p}", f"₹{safe(ema)}", pos])
    print(tabulate(ma_rows, headers=["Indicator","Value","Price vs MA"],
                   tablefmt="rounded_outline"))

    # Oscillators
    sub("Oscillators")
    rsi = tech.get("rsi_14", 0)
    rsi_str = (good(f"{rsi:.1f} (Healthy)") if 40 <= rsi <= 65
               else bad(f"{rsi:.1f} (OVERSOLD)") if rsi < 30
               else bad(f"{rsi:.1f} (OVERBOUGHT)") if rsi > 75
               else warn(f"{rsi:.1f}"))

    macd   = tech.get("macd", 0)
    macd_s = tech.get("macd_signal", 0)
    macd_h = tech.get("macd_hist", 0)
    macd_str = good("Bullish") if macd_h > 0 else bad("Bearish")

    sk = tech.get("stoch_k", 0)
    sd = tech.get("stoch_d", 0)
    stoch_str = (bad("OVERBOUGHT") if sk > 80
                 else bad("OVERSOLD") if sk < 20
                 else good("Healthy"))

    adx = tech.get("adx")
    adx_str = (good(f"{adx:.1f} (Strong Trend)") if adx and adx >= 25
               else warn(f"{adx:.1f} (Weak Trend)") if adx else "N/A")
    dmi_p = tech.get("dmi_plus", 0) or 0
    dmi_m = tech.get("dmi_minus", 0) or 0

    osc_rows = [
        ["RSI (14)",           rsi_str,          "30–70 = normal; <30 oversold; >70 overbought"],
        ["MACD",               f"{safe(macd)} / Signal {safe(macd_s)}", macd_str],
        ["MACD Histogram",     safe(macd_h),     tech.get("macd_crossover","")],
        ["Stochastic %K/%D",   f"{safe(sk)}/{safe(sd)}", stoch_str],
        ["ADX (14)",           adx_str,          "< 20 weak; > 25 strong trend"],
        ["DMI+ / DMI-",        f"{safe(dmi_p)}/{safe(dmi_m)}",
         good("Bull") if dmi_p > dmi_m else bad("Bear")],
    ]
    print(tabulate(osc_rows, headers=["Indicator","Value","Signal"],
                   tablefmt="rounded_outline"))

    # Bollinger Bands
    sub("Bollinger Bands (20,2)")
    bb_pct = tech.get("bb_pct_b", 0.5)
    bb_pos = (bad("Near LOWER band — Oversold") if bb_pct < 0.2
              else bad("Near UPPER band — Overbought") if bb_pct > 0.8
              else good("Mid-band — Neutral"))
    bb_rows = [
        ["Upper Band",  f"₹{safe(tech.get('bb_upper'))}"],
        ["Middle Band", f"₹{safe(tech.get('bb_mid'))}"],
        ["Lower Band",  f"₹{safe(tech.get('bb_lower'))}"],
        ["%B Value",    f"{safe(bb_pct)} — {bb_pos}"],
        ["Bandwidth %", f"{safe(tech.get('bb_bwidth'))}% — " +
                        ("Squeeze (breakout likely?)" if (tech.get("bb_bwidth") or 10) < 5 else "Normal")],
    ]
    print(tabulate(bb_rows, headers=["Band","Value"], tablefmt="rounded_outline"))

    # Price levels
    sub("Support & Resistance / Levels")
    level_rows = [
        ["52-Week High",      f"₹{safe(tech.get('52w_high'))}",
         f"{safe(tech.get('dist_52wh'))}% from current"],
        ["52-Week Low",       f"₹{safe(tech.get('52w_low'))}",
         f"{safe(tech.get('dist_52wl'))}% from current"],
        ["ATR (14-day)",      f"₹{safe(tech.get('atr_14'))}",
         f"{safe(tech.get('atr_pct'))}% of price — daily risk range"],
        ["Trend",             bold(tech.get("trend","N/A")),    ""],
        ["Golden/Death Cross",tech.get("cross","N/A"),          ""],
        ["Annual Volatility", f"{safe(tech.get('volatility_annual'))}%",
         "< 25 low; 25–50 medium; > 50 high"],
    ]
    print(tabulate(level_rows, headers=["Metric","Value","Note"],
                   tablefmt="rounded_outline"))

    # CAGR
    sub("Price Return (CAGR)")
    cagr_rows = []
    for period, key in [("1 Year", "cagr_1y"), ("3 Years", "cagr_3y"), ("5 Years", "cagr_5y")]:
        val = tech.get(key)
        if val:
            col = good(f"+{val:.1f}%") if val > 0 else bad(f"{val:.1f}%")
            cagr_rows.append([period, col])
    if cagr_rows:
        print(tabulate(cagr_rows, headers=["Period","CAGR"], tablefmt="rounded_outline"))


def print_news(news_list: list, symbol: str):
    hdr(f"RECENT NEWS & UPCOMING EVENTS  —  {symbol}")
    if not news_list:
        print("  No news found.")
        return
    for i, item in enumerate(news_list[:10], 1):
        # yfinance >= 0.2.x nests fields inside item["content"]; older versions are flat
        content   = item.get("content", item)
        title     = content.get("title") or item.get("title", "No title")

        # publisher: new API uses content["provider"]["displayName"], old uses "publisher"
        provider  = content.get("provider", {})
        publisher = provider.get("displayName") if isinstance(provider, dict) else None
        publisher = publisher or content.get("publisher") or item.get("publisher", "")

        # timestamp: new API uses content["pubDate"] (ISO string), old uses providerPublishTime (epoch int)
        pub_date  = content.get("pubDate") or ""
        pub_time  = item.get("providerPublishTime", 0)
        if pub_date:
            try:
                dt_str = datetime.fromisoformat(pub_date.replace("Z", "+00:00")).strftime("%d %b %Y %H:%M")
            except Exception:
                dt_str = pub_date[:16]
        elif pub_time:
            dt_str = datetime.utcfromtimestamp(pub_time).strftime("%d %b %Y %H:%M")
        else:
            dt_str = ""

        # link: new API uses content["canonicalUrl"]["url"], old uses "link"
        canon_url = content.get("canonicalUrl", {})
        link      = canon_url.get("url") if isinstance(canon_url, dict) else None
        link      = link or content.get("link") or item.get("link", "")

        print(f"\n  {Fore.CYAN}{i}. {title}{Style.RESET_ALL}")
        print(f"     📰 {publisher}  |  📅 {dt_str}")
        if link:
            print(f"     🔗 {link[:80]}")


def print_dividends(dividends: pd.Series):
    hdr("DIVIDEND HISTORY (Last 10 Payouts)")
    if dividends.empty:
        print("  No dividend history found.")
        return
    recent = dividends.tail(10)
    rows = [[str(d.date()), f"₹{v:.2f}"] for d, v in recent.items()]
    print(tabulate(rows, headers=["Date","Dividend (₹)"], tablefmt="rounded_outline"))


def print_institutional(holders: pd.DataFrame):
    hdr("INSTITUTIONAL HOLDERS (Top 10)")
    if holders is None or holders.empty:
        print("  No institutional holder data available.")
        return
    try:
        top = holders.head(10)
        rows = []
        for _, r in top.iterrows():
            rows.append([
                r.get("Holder", "N/A"),
                f"{r.get('pctHeld', 0)*100:.2f}%" if r.get("pctHeld") else "N/A",
                f"{r.get('Shares', 0):,}" if r.get("Shares") else "N/A",
            ])
        print(tabulate(rows, headers=["Institution","% Held","Shares"],
                       tablefmt="rounded_outline"))
    except Exception as e:
        print(f"  Could not parse: {e}")


def print_risk_factors(info: dict, tech: dict):
    hdr("RISK FACTORS & RED FLAGS")
    risks = []

    pe = info.get("trailingPE") or info.get("forwardPE")
    if pe and pe > 50:
        risks.append(bad(f"⚠ Very high P/E ({pe:.0f}x) — price reflects high expectations"))

    de = info.get("debtToEquity")
    if de and de > 200:
        risks.append(bad(f"⚠ Debt/Equity is {de:.0f}% — significant leverage risk"))

    pm = info.get("profitMargins")
    if pm and pm < 0:
        risks.append(bad(f"⚠ Company is reporting net losses (margin: {pm*100:.1f}%)"))

    fcf = info.get("freeCashflow")
    if fcf and fcf < 0:
        risks.append(bad(f"⚠ Negative Free Cash Flow — burning cash"))

    rsi = tech.get("rsi_14")
    if rsi and rsi > 75:
        risks.append(warn(f"⚠ RSI {rsi:.1f} — technically overbought, wait for pullback"))
    if rsi and rsi < 30:
        risks.append(warn(f"⚠ RSI {rsi:.1f} — oversold, may bounce but check fundamentals"))

    cr = info.get("currentRatio")
    if cr and cr < 1:
        risks.append(bad(f"⚠ Current Ratio {cr:.2f} — company may face short-term liquidity issues"))

    beta = info.get("beta")
    if beta and beta > 1.8:
        risks.append(warn(f"⚠ Beta {beta:.2f} — very volatile stock, wider swings than Nifty"))

    payout = info.get("payoutRatio")
    if payout and payout > 0.9:
        risks.append(warn(f"⚠ Payout Ratio {payout*100:.0f}% — dividend may not be sustainable"))

    vol = tech.get("volatility_annual")
    if vol and vol > 50:
        risks.append(warn(f"⚠ Annual price volatility {vol:.1f}% — high-risk stock"))

    if not risks:
        print(good("  ✅ No major red flags detected."))
    else:
        for r in risks:
            print(f"  {r}")


def print_investment_score(score: int, verdict: str, details: list):
    hdr("OVERALL INVESTMENT SCORE")
    bar_len = 40
    filled  = int(bar_len * score / 100)
    bar_col = (Fore.GREEN if score >= 60 else Fore.YELLOW if score >= 40 else Fore.RED)
    bar     = bar_col + "█" * filled + Style.DIM + "░" * (bar_len - filled) + Style.RESET_ALL
    print(f"\n  Score:  {bar}  {Style.BRIGHT}{score}/100{Style.RESET_ALL}")
    print(f"  Verdict: {verdict}\n")

    print(tabulate(
        [[d[0], d[1], d[2]] for d in details],
        headers=["Component", "Points Earned", "Max Points"],
        tablefmt="rounded_outline"
    ))


def print_investment_checklist(info: dict, tech: dict):
    hdr("INVESTMENT CHECKLIST  (Before You Buy)")
    checklist = [
        ("Is the business easy to understand?",          "Check company website & annual report"),
        ("Does it have a competitive moat?",             "Brand, patents, switching costs, network effects"),
        ("Is management trustworthy?",                   "Check promoter pledging, insider transactions"),
        ("Is promoter holding > 50%?",                   f"{info.get('heldPercentInsiders', 0)*100:.1f}% insiders (Yahoo)"),
        ("Institutional holding increasing?",            "Check NSE bulk deals / shareholding pattern"),
        ("Any upcoming results / events?",               "Check NSE calendar for earnings date"),
        ("Any GST / regulatory / sector headwinds?",     "Check recent news above"),
        ("Is the stock liquid enough?",                  f"Volume: {info.get('averageVolume3Month', 0):,}"),
        ("Have you checked peers/competitors?",          "Compare P/E, ROE with sector average"),
        ("What is your exit strategy?",                  "Set SL at 52W low or ATR-based stop"),
    ]
    rows = [[f"{'✅' if i%2==0 else '📋'} {q}", a] for i, (q, a) in enumerate(checklist)]
    print(tabulate(rows, headers=["Question", "Guidance"], tablefmt="rounded_outline"))


# ══════════════════════════════════════════════════════════════════════════════
#  MAIN ANALYSIS
# ══════════════════════════════════════════════════════════════════════════════
def analyse(symbol: str):
    symbol = symbol.upper().strip()

    print(f"\n{'='*72}")
    print(f"  📊  STOCK ANALYSIS REPORT  —  {symbol}")
    print(f"  Generated: {datetime.now(IST).strftime('%d %b %Y  %H:%M IST')}")
    print(f"{'='*72}")

    # ── Step 1: Zerodha Login + Live Quote ───────────────────────────────────
    kite   = None
    ltp_data = {}
    df_kite  = pd.DataFrame()

    try:
        kite     = zerodha_login()
        ltp_data = get_kite_price(kite, symbol)
        print("  Fetching price history from Zerodha...")
        df_kite  = get_kite_history(kite, symbol, days=730)
    except Exception as e:
        print(warn(f"  ⚠ Zerodha unavailable: {e}"))
        print("  → Falling back to yfinance for price data")

    # ── Step 2: Yahoo Finance — fundamentals + history fallback ─────────────
    print("\n  Fetching fundamentals from Yahoo Finance...")
    yf_data = get_yf_data(symbol)
    info    = yf_data["info"]

    # Use Kite history if available, else yfinance
    if not df_kite.empty:
        df = df_kite
    else:
        h = yf_data["hist_2y"] if "hist_2y" in yf_data else yf_data.get("hist_1y", pd.DataFrame())
        h5 = yf_data.get("hist_5y", pd.DataFrame())
        df = h5 if not h5.empty else h
        if not df.empty:
            df.columns = [c.lower() for c in df.columns]
            df.index.name = "date"
            print(good(f"  ✓ yfinance history: {len(df)} days loaded"))

    # ── Step 3: Technical indicators ─────────────────────────────────────────
    tech = compute_technicals(df)
    ltp  = (ltp_data.get("ltp") or info.get("currentPrice")
            or info.get("regularMarketPrice") or (df["close"].iloc[-1] if not df.empty else 0))

    # ── Step 4: Print all sections ───────────────────────────────────────────
    print_company_overview(info, symbol)
    print_price_info(ltp_data, info)
    print_fundamentals(info)
    if tech:
        print_technicals(tech, ltp)
    print_news(yf_data["news"], symbol)
    print_dividends(yf_data["dividends"])
    print_institutional(yf_data["institutional_holders"])
    print_risk_factors(info, tech)
    score, verdict, details = compute_investment_score(info, tech)
    print_investment_score(score, verdict, details)
    print_investment_checklist(info, tech)

    print(f"\n{'='*72}")
    print(f"  ⚠  DISCLAIMER: This is for educational purposes only.")
    print(f"     Not SEBI-registered advice. Do your own due diligence.")
    print(f"{'='*72}\n")


# ══════════════════════════════════════════════════════════════════════════════
#  ENTRY POINT
# ══════════════════════════════════════════════════════════════════════════════
if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("\nUsage:  python stock_analysis.py <NSE_SYMBOL>")
        print("Examples:")
        print("  python stock_analysis.py RELIANCE")
        print("  python stock_analysis.py TCS")
        print("  python stock_analysis.py INFY")
        print("  python stock_analysis.py HDFCBANK")
        print("  python stock_analysis.py WIPRO")
        sys.exit(1)

    analyse(sys.argv[1])
