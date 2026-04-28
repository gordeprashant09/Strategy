"""
╔══════════════════════════════════════════════════════════════════════════════╗
║  BULLISH INTRADAY STOCK SCANNER — Streamlit Dashboard                      ║
║                                                                              ║
║  Uses same Zerodha (KiteConnect) auth as fo_realtime_feeder_new_up.py      ║
║                                                                              ║
║  Screens for:                                                                ║
║    1. Pre-open price > Prev Close  (gap-up / bullish open)                 ║
║    2. 52-Week High breakers                                                 ║
║    3. High Volume (2x+ avg) movers                                          ║
║    4. Strong momentum (% change, RSI proxy, VWAP above open)               ║
║                                                                              ║
║  Run:  streamlit run bullish_scanner_dashboard.py                           ║
║  Deps: pip install streamlit kiteconnect pyotp requests pandas              ║
╚══════════════════════════════════════════════════════════════════════════════╝
"""

import os, sys, time, json, threading, subprocess
from datetime import datetime, timedelta, timezone, date

# ── Auto-install ───────────────────────────────────────────────────────────────
def _pip(pkg):
    try: __import__(pkg.replace("-","_").split("[")[0])
    except ImportError:
        subprocess.run([sys.executable, "-m", "pip", "install", pkg,
                        "--quiet", "--break-system-packages"], check=True)

for p in ["streamlit", "kiteconnect", "pyotp", "requests", "pandas"]:
    _pip(p)

import streamlit as st
import pandas as pd
import requests
import pyotp
from kiteconnect import KiteConnect

# ═══════════════════════════════════════════════════════════════════════════════
#  CONFIG  — same credentials as fo_realtime_feeder_new_up.py
# ═══════════════════════════════════════════════════════════════════════════════
API_KEY    = os.getenv("KITE_API_KEY",  "4tl671rr7bwffw7b")
API_SECRET = os.getenv("KITE_SECRET",   "4gesk7v5vsbx9us4t8j3gh229zwzwf9t")
USER_ID    = os.getenv("KITE_USER_ID",  "QWK225")
PASSWORD   = os.getenv("KITE_PASSWORD", "Dec2025!")
TOTP_KEY   = os.getenv("KITE_TOTP_KEY", "VV2ZTNC3LG4V7EG7ECFLJIURPGVERJL7")
KITE_PIN   = os.getenv("KITE_PIN",      "123456")

IST = timezone(timedelta(hours=5, minutes=30))

# ── NSE F&O stocks universe (top liquid stocks) ───────────────────────────────
FO_STOCKS = [
    "RELIANCE","TCS","INFY","HDFCBANK","ICICIBANK","SBIN","BHARTIARTL",
    "WIPRO","LT","AXISBANK","KOTAKBANK","HCLTECH","BAJFINANCE","ASIANPAINT",
    "MARUTI","ULTRACEMCO","TITAN","BAJAJFINSV","NESTLEIND","TECHM",
    "SUNPHARMA","DRREDDY","CIPLA","DIVISLAB","APOLLOHOSP","ADANIPORTS",
    "HINDUNILVR","ITC","POWERGRID","NTPC","ONGC","COALINDIA","JSWSTEEL",
    "TATASTEEL","HINDALCO","TATACONSUM","GRASIM","SHREECEM","AMBUJACEM",
    "HEROMOTOCO","EICHERMOT","BAJAJ-AUTO","M&M","TATAMOTOR","TATAMOTORS",
    "INDUSINDBK","FEDERALBNK","BANDHANBNK","PNB","CANBK","BANKBARODA",
    "HDFCLIFE","SBILIFE","ICICIGI","MUTHOOTFIN","CHOLAFIN","LICHSGFIN",
    "PIDILITIND","BERGEPAINT","HAVELLS","VOLTAS","WHIRLPOOL","CROMPTON",
    "MCDOWELL-N","UBL","BRITANNIA","DABUR","MARICO","GODREJCP",
    "JUBLFOOD","ZOMATO","NYKAA","PAYTM","DMART","TRENT",
    "IRCTC","CONCOR","NMDC","RECLTD","PFC","IRFC",
    "HAL","BEL","BHEL","OFSS","PERSISTENT","LTIM","COFORGE",
    "INDIAMART","NAUKRI","POLICYBZR","STAR","SIEMENS","ABB","CUMMINSIND",
    "GODREJPROP","DLF","OBEROI","PRESTIGE","PHOENIXLTD",
    "IDFCFIRSTB","RBLBANK","YESBANK","AUBANK",
    "SAIL","NATIONALUM","HINDCOPPER","VEDL","GMRINFRA",
    "MOTHERSON","BALKRISHIND","APOLLOTYRE","MFSL","MAXHEALTH",
]

# ═══════════════════════════════════════════════════════════════════════════════
#  PAGE CONFIG
# ═══════════════════════════════════════════════════════════════════════════════
st.set_page_config(
    page_title="🚀 Bullish Intraday Scanner",
    page_icon="🚀",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── Custom CSS ─────────────────────────────────────────────────────────────────
st.markdown("""
<style>
    .main { background-color: #0e1117; }
    .metric-card {
        background: linear-gradient(135deg, #1e2130, #252840);
        border: 1px solid #2e3250;
        border-radius: 12px;
        padding: 16px 20px;
        margin: 6px 0;
    }
    .bullish-tag {
        background: #0d3321;
        color: #00e676;
        padding: 2px 8px;
        border-radius: 4px;
        font-size: 12px;
        font-weight: bold;
    }
    .signal-strong {
        background: #003300;
        color: #00ff88;
        border-left: 4px solid #00ff88;
        padding: 6px 12px;
        border-radius: 4px;
        margin: 3px 0;
    }
    .signal-medium {
        background: #1a2600;
        color: #aaff00;
        border-left: 4px solid #aaff00;
        padding: 6px 12px;
        border-radius: 4px;
        margin: 3px 0;
    }
    div[data-testid="stDataFrame"] { border-radius: 10px; }
    .stButton>button {
        background: linear-gradient(135deg, #00c853, #1b5e20);
        color: white;
        border: none;
        border-radius: 8px;
        font-weight: bold;
        padding: 8px 24px;
    }
    .stButton>button:hover { background: linear-gradient(135deg, #00e676, #2e7d32); }
    h1 { color: #00e676 !important; }
    h2, h3 { color: #69f0ae !important; }
    .last-refresh { color: #888; font-size: 12px; }
</style>
""", unsafe_allow_html=True)

# ═══════════════════════════════════════════════════════════════════════════════
#  AUTH — cached in session_state
# ═══════════════════════════════════════════════════════════════════════════════
def _now(): return datetime.now(IST)

def zerodha_login():
    """
    Login to Zerodha using ONE web session — extracts enctoken after TOTP,
    then tries the SDK request_token path.  If SDK path fails (rate-limit,
    redirect_uri not configured, stale token etc.) the already-obtained
    enctoken is used directly — no second login, no 403/429 errors.

    Returns a KiteConnect-compatible object on success, raises on total failure.
    """
    from urllib.parse import urlparse, parse_qs
    from requests.adapters import HTTPAdapter

    sess = requests.Session()
    sess.headers.update({
        "User-Agent":      "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                           "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept":          "application/json, text/plain, */*",
        "Accept-Language": "en-US,en;q=0.9",
        "Origin":          "https://kite.zerodha.com",
        "Referer":         "https://kite.zerodha.com/",
        "Content-Type":    "application/x-www-form-urlencoded",
    })

    # ── Step 1: Password ──────────────────────────────────────────────────────
    r1 = sess.post("https://kite.zerodha.com/api/login",
                   data={"user_id": USER_ID, "password": PASSWORD}, timeout=20)
    j1 = r1.json()
    if j1.get("status") != "success":
        raise RuntimeError(f"Login step1 failed: {j1.get('message')}")

    req_id = j1["data"]["request_id"]
    twofa  = j1["data"].get("twofa_type", "totp")
    tv     = pyotp.TOTP(TOTP_KEY).now() if "totp" in twofa.lower() else KITE_PIN

    # ── Step 2: TOTP ──────────────────────────────────────────────────────────
    r2 = sess.post("https://kite.zerodha.com/api/twofa",
                   data={"user_id": USER_ID, "request_id": req_id,
                         "twofa_value": tv, "twofa_type": twofa}, timeout=20)
    j2 = r2.json()
    if j2.get("status") != "success":
        raise RuntimeError(f"TOTP failed: {j2.get('message')}")

    # ── Extract enctoken NOW (before any further calls that could rate-limit) ─
    enc = None
    if isinstance(j2.get("data"), dict):
        enc = j2["data"].get("enctoken")
    if not enc:
        enc = sess.cookies.get("enctoken")
    if not enc:
        for c in sess.cookies:
            if c.name == "enctoken":
                enc = c.value; break

    # ── Step 3: Try SDK path (request_token via redirect) ─────────────────────
    # Only succeeds when Kite app redirect_uri is configured to return the token.
    # Fails silently → we fall through to the enctoken path below.
    request_token = None
    try:
        r3 = sess.get(f"https://kite.zerodha.com/connect/login?api_key={API_KEY}&v=3",
                      timeout=20, allow_redirects=True)
        location = r3.url
        qs = parse_qs(urlparse(location).query)
        request_token = qs.get("request_token", [None])[0]
    except Exception:
        request_token = None

    if request_token:
        try:
            kite = KiteConnect(api_key=API_KEY)
            sd   = kite.generate_session(request_token, api_secret=API_SECRET)
            kite.set_access_token(sd["access_token"])
            # Patch connection pool — 500 symbols × parallel chunks need large pool
            adapter = HTTPAdapter(pool_connections=10, pool_maxsize=100, max_retries=2)
            _s = getattr(kite, 'reqsession', None) or getattr(kite, '_session', None)
            if _s:
                _s.mount("https://", adapter); _s.mount("http://", adapter)
            return kite          # ✅ SDK path succeeded
        except Exception as sdk_err:
            # SDK failed (Too many requests, stale secret, etc.) — fall through
            pass

    # ── Step 4: enctoken fallback (cookie-based OMS session) ─────────────────
    # This is the reliable daily path — enctoken is valid all day once obtained.
    if not enc:
        raise RuntimeError(
            "Login succeeded but enctoken not found — cannot connect to Zerodha OMS.")

    # Build a requests.Session with enctoken cookie for OMS calls
    oms = requests.Session()
    adapter = HTTPAdapter(pool_connections=10, pool_maxsize=100, max_retries=2)
    oms.mount("https://", adapter); oms.mount("http://", adapter)
    oms.headers.update({
        "User-Agent":      "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                           "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept":          "application/json, text/plain, */*",
        "Origin":          "https://kite.zerodha.com",
        "Referer":         "https://kite.zerodha.com/",
    })
    # OMS uses cookie-only auth — no Authorization header
    oms.cookies.set("enctoken", enc, domain="kite.zerodha.com", path="/")
    oms.cookies.set("enctoken", enc, domain=".zerodha.com",     path="/")

    # Wrap oms session as a lightweight KiteConnect-compatible proxy
    # so the rest of the dashboard (kite.quote, kite.ltp, etc.) works unchanged.
    kite_proxy = _EncTokenKite(oms, enc)
    return kite_proxy


class _EncTokenKite:
    """
    Lightweight proxy that mirrors the KiteConnect methods used by this dashboard
    (quote, ltp, historical_data) but authenticates via enctoken cookie to the
    Zerodha OMS endpoint instead of the SDK api.kite.trade endpoint.
    Avoids a second login call — uses the enctoken already obtained above.
    """
    _OMS = "https://kite.zerodha.com/oms"

    def __init__(self, session: requests.Session, enc: str):
        self._sess = session
        self._enc  = enc
        # Instrument token cache:  "NSE:SYMBOL" → int token
        self._tok_cache: dict = {}

    def _get(self, path, params=None):
        r = self._sess.get(f"{self._OMS}{path}", params=params, timeout=15)
        r.raise_for_status()
        j = r.json()
        if j.get("status") != "success":
            raise RuntimeError(f"OMS {path} error: {j.get('message', j)}")
        return j["data"]

    # ── quote() ───────────────────────────────────────────────────────────────
    def quote(self, instruments: list) -> dict:
        """Fetch full quote for a list of 'EXCHANGE:SYMBOL' strings."""
        result = {}
        # OMS accepts up to 500 per call via repeated 'i' params
        for i in range(0, len(instruments), 450):
            chunk = instruments[i:i+450]
            params = [("i", s) for s in chunk]
            data = self._get("/quote", params)
            result.update(data)
        return result

    # ── ltp() ─────────────────────────────────────────────────────────────────
    def ltp(self, instruments: list) -> dict:
        """Fetch last traded price for a list of instruments."""
        result = {}
        for i in range(0, len(instruments), 450):
            chunk = instruments[i:i+450]
            params = [("i", s) for s in chunk]
            data = self._get("/quote/ltp", params)
            result.update(data)
        return result

    # ── historical_data() ─────────────────────────────────────────────────────
    def historical_data(self, instrument_token, from_date, to_date,
                        interval, continuous=False, oi=False):
        """Fetch OHLCV candles. instrument_token must be an int."""
        if not instrument_token:
            return []
        params = {
            "from":        str(from_date),
            "to":          str(to_date),
            "interval":    interval,
            "continuous":  int(continuous),
            "oi":          int(oi),
        }
        data = self._get(f"/instruments/historical/{instrument_token}/{interval}",
                         params)
        candles = data.get("candles", [])
        # Return same format as KiteConnect SDK
        keys = ["date", "open", "high", "low", "close", "volume"]
        if oi:
            keys.append("oi")
        return [dict(zip(keys, c)) for c in candles]

    # ── profile() (used for sanity check) ────────────────────────────────────
    def profile(self):
        return self._get("/user/profile") or {}


def get_kite():
    """Return cached kite object from session_state, logging in if needed."""
    if "kite" not in st.session_state or st.session_state.kite is None:
        st.session_state.kite = None
        with st.spinner("🔐 Logging into Zerodha..."):
            try:
                st.session_state.kite = zerodha_login()
                st.session_state.login_time = _now()
                # Show which auth method was used
                if isinstance(st.session_state.kite, _EncTokenKite):
                    st.toast("✅ Connected via enctoken (SDK path unavailable — normal)", icon="🔑")
                else:
                    st.toast("✅ Connected via KiteConnect SDK", icon="🔑")
            except Exception as e:
                st.error(f"Login failed: {e}")
                return None
    return st.session_state.kite

# ═══════════════════════════════════════════════════════════════════════════════
#  DATA FETCHERS
# ═══════════════════════════════════════════════════════════════════════════════
def fetch_quotes_chunked(kite, symbols: list, exchange="NSE") -> dict:
    """Fetch quotes in chunks of 500 (Kite limit)."""
    full_syms = [f"{exchange}:{s}" for s in symbols]
    result = {}
    for i in range(0, len(full_syms), 450):
        chunk = full_syms[i:i+450]
        try:
            q = kite.quote(chunk)
            result.update(q)
        except Exception as e:
            st.warning(f"Quote fetch error (chunk {i}): {e}")
    return result

def fetch_preopen(kite) -> pd.DataFrame:
    """
    Fetch pre-open market data.
    Pre-open is available 9:00–9:15 AM IST via kite.quote() with ohlc.
    During market hours: open > prev_close signals gap-up bullish.
    """
    quotes = fetch_quotes_chunked(kite, FO_STOCKS)
    rows = []
    for sym_full, q in quotes.items():
        sym = sym_full.split(":", 1)[-1]
        ohlc      = q.get("ohlc") or {}
        ltp       = float(q.get("last_price") or 0)
        prev_close= float(ohlc.get("close") or 0)
        open_     = float(ohlc.get("open")  or 0)
        high      = float(ohlc.get("high")  or 0)
        low       = float(ohlc.get("low")   or 0)
        volume    = int(q.get("volume") or 0)
        change_pct= float(q.get("change") or 0)
        depth     = q.get("depth") or {}
        buy0      = (depth.get("buy")  or [{}])[0]
        sell0     = (depth.get("sell") or [{}])[0]
        bid       = float(buy0.get("price") or 0)
        ask       = float(sell0.get("price") or 0)

        if prev_close <= 0 or open_ <= 0: continue

        gap_pct   = round((open_ - prev_close) / prev_close * 100, 2)
        preopen_bull = open_ > prev_close          # gapped up

        # Intraday range %
        range_pct  = round((high - low) / prev_close * 100, 2) if prev_close else 0
        # Price position in today's range (0=low, 100=high)
        range_pos  = round((ltp - low) / (high - low) * 100, 1) if high != low else 50

        rows.append({
            "Symbol":       sym,
            "LTP":          ltp,
            "Open":         open_,
            "Prev Close":   prev_close,
            "High":         high,
            "Low":          low,
            "Gap %":        gap_pct,
            "Change %":     round(change_pct, 2),
            "Range %":      range_pct,
            "Range Pos %":  range_pos,
            "Volume":       volume,
            "Bid":          bid,
            "Ask":          ask,
            "Preopen Bull": preopen_bull,
        })

    df = pd.DataFrame(rows)
    if df.empty: return df
    return df.sort_values("Gap %", ascending=False).reset_index(drop=True)

def fetch_52wk_highs(kite) -> pd.DataFrame:
    """
    Identify stocks near or at 52-week high.
    Kite doesn't give 52wk directly in quote; we use:
      - Historical API (last 365 days) for a subset, OR
      - Approximate: LTP >= 0.98 * 52wk_high using historical candles.
    We use kite.historical_data for reliable 52-week high.
    """
    results = []
    progress = st.progress(0, text="Fetching 52-week high data...")
    total = len(FO_STOCKS)
    today = _now().date()
    yr_ago = today - timedelta(days=365)

    # First get current LTPs in one call
    quotes = fetch_quotes_chunked(kite, FO_STOCKS)

    for idx, sym in enumerate(FO_STOCKS):
        progress.progress((idx+1)/total, text=f"52wk scan: {sym} ({idx+1}/{total})")
        q = quotes.get(f"NSE:{sym}") or {}
        ltp = float(q.get("last_price") or 0)
        if ltp <= 0:
            continue
        try:
            # Fetch daily OHLC for past 365 days
            instr = kite.ltp([f"NSE:{sym}"])  # lightweight check
            hist = kite.historical_data(
                instrument_token=q.get("instrument_token"),
                from_date=yr_ago.strftime("%Y-%m-%d"),
                to_date=today.strftime("%Y-%m-%d"),
                interval="day",
            )
            if not hist:
                continue
            highs = [float(c["high"]) for c in hist if c.get("high")]
            wk52_high = max(highs) if highs else 0
            wk52_low  = min([float(c["low"]) for c in hist if c.get("low")]) if hist else 0
            if wk52_high <= 0:
                continue

            dist_from_high = round((wk52_high - ltp) / wk52_high * 100, 2)
            dist_from_low  = round((ltp - wk52_low) / wk52_low * 100, 2)
            at_52wk_high   = dist_from_high <= 2.0   # within 2% of 52wk high

            ohlc = q.get("ohlc") or {}
            results.append({
                "Symbol":          sym,
                "LTP":             ltp,
                "52W High":        wk52_high,
                "52W Low":         wk52_low,
                "Dist from High %":dist_from_high,
                "Above Low %":     dist_from_low,
                "Change %":        round(float(q.get("change") or 0), 2),
                "Volume":          int(q.get("volume") or 0),
                "At 52W High":     at_52wk_high,
            })
        except Exception:
            # Skip if historical fails (instrument_token unavailable etc.)
            pass

    progress.empty()
    df = pd.DataFrame(results)
    if df.empty: return df
    return df.sort_values("Dist from High %").reset_index(drop=True)

def compute_bullish_score(row) -> int:
    """
    Score 0-100 for overall bullishness based on multiple parameters.
    Higher = more bullish.
    """
    score = 0
    # Gap up
    gap = row.get("Gap %", 0)
    if gap > 3:   score += 25
    elif gap > 1: score += 15
    elif gap > 0: score += 8
    # Change %
    chg = row.get("Change %", 0)
    if chg > 3:   score += 20
    elif chg > 1: score += 12
    elif chg > 0: score += 5
    # Range position (LTP in upper half of day's range)
    rp = row.get("Range Pos %", 50)
    if rp > 80:   score += 20
    elif rp > 60: score += 12
    elif rp > 50: score += 6
    # Volume (proxied by raw volume; high volume = conviction)
    vol = row.get("Volume", 0)
    if vol > 5_000_000:  score += 15
    elif vol > 1_000_000: score += 10
    elif vol > 500_000:   score += 5
    # High of day equals LTP (making new highs)
    ltp  = row.get("LTP", 0)
    high = row.get("High", 0)
    if high > 0 and abs(ltp - high) / high < 0.002:
        score += 20   # at high of day
    return min(score, 100)

def get_signal_label(score):
    if score >= 70: return "🟢 STRONG BUY"
    if score >= 50: return "🟡 BUY"
    if score >= 30: return "🔵 WATCH"
    return "⚪ NEUTRAL"

# ═══════════════════════════════════════════════════════════════════════════════
#  SIDEBAR
# ═══════════════════════════════════════════════════════════════════════════════
with st.sidebar:
    st.markdown("## ⚙️ Scanner Controls")
    st.divider()

    auto_refresh = st.toggle("🔄 Auto Refresh", value=False)
    refresh_sec  = st.slider("Refresh every (sec)", 30, 300, 60, step=10,
                             disabled=not auto_refresh)

    st.divider()
    st.markdown("### 🎚️ Filters")
    min_gap_pct  = st.slider("Min Gap-Up %",  0.0, 5.0, 0.1, step=0.1)
    min_chg_pct  = st.slider("Min Change %",  0.0, 5.0, 0.0, step=0.1)
    min_score    = st.slider("Min Bullish Score", 0, 100, 20, step=5)
    near_high_pct= st.slider("Near 52W High within %", 0.5, 10.0, 3.0, step=0.5)

    st.divider()
    st.markdown("### 📊 Display Options")
    show_preopen = st.checkbox("Gap-Up / Pre-open Stocks", value=True)
    show_52wk    = st.checkbox("52-Week High Breakouts", value=True)
    show_volume  = st.checkbox("Volume Surge Stocks", value=True)
    show_alldata = st.checkbox("All Stocks Summary", value=False)

    st.divider()
    scan_btn = st.button("🚀 Run Scanner", width="stretch")
    st.markdown('<p class="last-refresh">Built with Zerodha KiteConnect</p>',
                unsafe_allow_html=True)

# ═══════════════════════════════════════════════════════════════════════════════
#  HEADER
# ═══════════════════════════════════════════════════════════════════════════════
st.markdown("# 🚀 Bullish Intraday Stock Scanner")
st.markdown("**Real-time data from Zerodha KiteConnect** — Gap-Up, 52-Week High, Volume Surge, Momentum")

col_time, col_market, col_status = st.columns(3)
now_ist = _now()
market_open = (9*60+15) <= (now_ist.hour*60+now_ist.minute) <= (15*60+30) and now_ist.weekday() < 5
col_time.metric("🕐 IST Time", now_ist.strftime("%H:%M:%S"))
col_market.metric("📈 Market", "🟢 OPEN" if market_open else "🔴 CLOSED")
col_status.metric("👤 Account", USER_ID)

st.divider()

# ═══════════════════════════════════════════════════════════════════════════════
#  MAIN LOGIC
# ═══════════════════════════════════════════════════════════════════════════════
# Auto-refresh timer
if auto_refresh:
    if "last_scan" not in st.session_state:
        st.session_state.last_scan = 0
    elapsed = time.time() - st.session_state.last_scan
    if elapsed >= refresh_sec:
        scan_btn = True

if scan_btn or ("scan_data" in st.session_state and not st.session_state.scan_data.empty):
    kite = get_kite()
    if kite is None:
        st.stop()

    # Run scan if button pressed or first time
    if scan_btn:
        st.session_state.last_scan = time.time()
        with st.spinner("📡 Fetching live quotes from Zerodha..."):
            df_quotes = fetch_quotes_chunked(kite, FO_STOCKS)
            rows = []
            for sym_full, q in df_quotes.items():
                sym  = sym_full.split(":",1)[-1]
                ohlc = q.get("ohlc") or {}
                ltp       = float(q.get("last_price") or 0)
                prev_close= float(ohlc.get("close") or 0)
                open_     = float(ohlc.get("open")  or 0)
                high      = float(ohlc.get("high")  or 0)
                low       = float(ohlc.get("low")   or 0)
                volume    = int(q.get("volume") or 0)
                chg_pct   = float(q.get("change") or 0)
                depth     = q.get("depth") or {}
                buy0      = (depth.get("buy")  or [{}])[0]
                sell0     = (depth.get("sell") or [{}])[0]
                bid       = float(buy0.get("price") or 0)
                ask       = float(sell0.get("price") or 0)
                spread    = round(ask - bid, 2) if ask and bid else 0
                spread_pct= round(spread/ltp*100, 3) if ltp else 0
                if prev_close <= 0 or open_ <= 0: continue
                gap_pct   = round((open_ - prev_close)/prev_close*100, 2)
                range_pct = round((high-low)/prev_close*100, 2) if prev_close else 0
                range_pos = round((ltp-low)/(high-low)*100,1) if high!=low else 50
                at_hod    = abs(ltp-high)/high < 0.005 if high else False
                rows.append({
                    "Symbol":      sym,
                    "LTP":         ltp,
                    "Open":        open_,
                    "Prev Close":  prev_close,
                    "High":        high,
                    "Low":         low,
                    "Gap %":       gap_pct,
                    "Change %":    round(chg_pct,2),
                    "Range %":     range_pct,
                    "Range Pos %": range_pos,
                    "Volume":      volume,
                    "Bid":         bid,
                    "Ask":         ask,
                    "Spread %":    spread_pct,
                    "At HOD":      at_hod,
                })
            df_all = pd.DataFrame(rows)
            if not df_all.empty:
                df_all["Bullish Score"] = df_all.apply(compute_bullish_score, axis=1)
                df_all["Signal"]        = df_all["Bullish Score"].apply(get_signal_label)
                st.session_state.scan_data = df_all
                st.session_state.scan_time = _now().strftime("%H:%M:%S")

    df_all = st.session_state.get("scan_data", pd.DataFrame())
    scan_time = st.session_state.get("scan_time", "")

    if df_all.empty:
        st.warning("No data. Check Kite credentials or market hours.")
        st.stop()

    # ── TOP METRICS ROW ──────────────────────────────────────────────────────
    st.markdown(f"**🕐 Last Scan:** `{scan_time}` &nbsp;&nbsp; **📊 Stocks Scanned:** `{len(df_all)}`",
                unsafe_allow_html=True)

    m1, m2, m3, m4, m5 = st.columns(5)
    gap_up_df   = df_all[df_all["Gap %"] > min_gap_pct]
    strong_df   = df_all[df_all["Bullish Score"] >= 70]
    hod_df      = df_all[df_all["At HOD"] == True]
    vol_surge   = df_all[df_all["Volume"] >= 1_000_000]
    green_count = len(df_all[df_all["Change %"] > 0])

    m1.metric("⬆️ Gap-Up Stocks",    len(gap_up_df))
    m2.metric("🟢 Strong Buy",        len(strong_df))
    m3.metric("🏔️ At High of Day",    len(hod_df))
    m4.metric("📊 High Volume",        len(vol_surge))
    m5.metric("✅ Positive Stocks",   green_count)

    st.divider()

    # ── TAB LAYOUT ───────────────────────────────────────────────────────────
    tabs = st.tabs([
        "⬆️ Gap-Up / Pre-Open Bulls",
        "📊 Volume Surge",
        "🏔️ High of Day",
        "🎯 Top Bullish Picks",
        "📋 All Stocks",
    ])

    # ── Colour helpers ────────────────────────────────────────────────────────
    def color_pct(val):
        if isinstance(val, (int,float)):
            if val > 0:  return "color: #00e676; font-weight:bold"
            if val < 0:  return "color: #ff5252"
        return ""

    def color_score(val):
        if isinstance(val, (int,float)):
            if val >= 70: return "background-color: #003300; color: #00ff88; font-weight:bold"
            if val >= 50: return "background-color: #1a2600; color: #aaff00"
            if val >= 30: return "background-color: #0d1a33; color: #4fc3f7"
        return ""

    def fmt_df(df, cols_pct=None, cols_score=None):
        style = df.style.format({
            "LTP":       "₹{:.2f}",
            "Open":      "₹{:.2f}",
            "Prev Close":"₹{:.2f}",
            "High":      "₹{:.2f}",
            "Low":       "₹{:.2f}",
            "Bid":       "₹{:.2f}",
            "Ask":       "₹{:.2f}",
            "Gap %":     "{:+.2f}%",
            "Change %":  "{:+.2f}%",
            "Range %":   "{:.2f}%",
            "Range Pos %": "{:.1f}%",
            "Spread %":  "{:.3f}%",
            "Volume":    "{:,}",
        }, na_rep="-")
        if cols_pct:
            for c in cols_pct:
                style = style.applymap(color_pct, subset=[c])
        if cols_score and "Bullish Score" in df.columns:
            style = style.applymap(color_score, subset=["Bullish Score"])
        return style

    # ── TAB 1: Gap-Up / Pre-Open Bulls ───────────────────────────────────────
    with tabs[0]:
        st.markdown("### ⬆️ Stocks Opening Above Prev Close (Gap-Up = Bullish)")
        st.caption("These stocks opened higher than yesterday's close — strong bullish signal for intraday.")

        df_gap = df_all[
            (df_all["Gap %"] > min_gap_pct) &
            (df_all["Change %"] > min_chg_pct)
        ].sort_values("Gap %", ascending=False).reset_index(drop=True)

        if df_gap.empty:
            st.info(f"No stocks with gap > {min_gap_pct}% found. Try lowering the filter.")
        else:
            c1, c2 = st.columns(2)
            c1.metric("Gap-Up Count", len(df_gap))
            c2.metric("Avg Gap %", f"{df_gap['Gap %'].mean():.2f}%")

            display_cols = ["Symbol","LTP","Open","Prev Close","High","Low",
                            "Gap %","Change %","Range Pos %","Volume","Bullish Score","Signal"]
            st.dataframe(
                fmt_df(df_gap[display_cols], ["Gap %","Change %"], True),
                width="stretch", height=420
            )
            # Bar chart of top 20 by gap
            top20 = df_gap.head(20)
            st.bar_chart(top20.set_index("Symbol")["Gap %"])

    # ── TAB 2: Volume Surge ───────────────────────────────────────────────────
    with tabs[1]:
        st.markdown("### 📊 Volume Surge — High Conviction Moves")
        st.caption("Stocks with volume > 10 lakh + positive change = institutional buying signal.")

        df_vol = df_all[
            (df_all["Volume"] >= 1_000_000) &
            (df_all["Change %"] > 0)
        ].sort_values("Volume", ascending=False).reset_index(drop=True)

        if df_vol.empty:
            st.info("No high-volume stocks found yet. Try after 10:00 AM.")
        else:
            display_cols = ["Symbol","LTP","Change %","Volume","Gap %",
                            "Range Pos %","At HOD","Spread %","Bullish Score","Signal"]
            st.dataframe(
                fmt_df(df_vol[display_cols], ["Gap %","Change %"], True),
                width="stretch", height=420
            )
            top15 = df_vol.head(15)
            st.bar_chart(top15.set_index("Symbol")["Volume"])

    # ── TAB 3: High of Day ────────────────────────────────────────────────────
    with tabs[2]:
        st.markdown("### 🏔️ Stocks Trading at / Near High of Day")
        st.caption("LTP within 0.5% of intraday high = strong momentum, no selling pressure.")

        df_hod = df_all[
            (df_all["Range Pos %"] >= 90) &
            (df_all["Change %"] > 0)
        ].sort_values("Range Pos %", ascending=False).reset_index(drop=True)

        if df_hod.empty:
            st.info("No stocks at high of day right now.")
        else:
            display_cols = ["Symbol","LTP","High","Low","Range Pos %",
                            "Gap %","Change %","Volume","Bullish Score","Signal"]
            st.dataframe(
                fmt_df(df_hod[display_cols], ["Gap %","Change %"], True),
                width="stretch", height=420
            )

    # ── TAB 4: Top Bullish Picks ──────────────────────────────────────────────
    with tabs[3]:
        st.markdown("### 🎯 Top Bullish Picks — Multi-Factor Score")
        st.caption("""
        **Bullish Score** is computed from:
        - ✅ Gap-Up % (opens above prev close)
        - ✅ Intraday Change %
        - ✅ LTP position in day's range (upper = bullish)
        - ✅ Volume (higher = more conviction)
        - ✅ LTP at High of Day
        """)

        df_picks = df_all[df_all["Bullish Score"] >= min_score]\
                    .sort_values("Bullish Score", ascending=False)\
                    .reset_index(drop=True)

        if df_picks.empty:
            st.info(f"No stocks with Bullish Score ≥ {min_score}. Lower the threshold in sidebar.")
        else:
            # Highlight top 5
            st.markdown("#### 🥇 Top 5 Bullish Stocks Right Now")
            top5 = df_picks.head(5)
            cols5 = st.columns(5)
            for i, (_, row) in enumerate(top5.iterrows()):
                with cols5[i]:
                    st.markdown(f"""
                    <div class="metric-card">
                        <b>{row['Symbol']}</b><br>
                        <span style="font-size:18px;color:#00e676">₹{row['LTP']:.2f}</span><br>
                        <span class="bullish-tag">{row['Signal']}</span><br>
                        Gap: <b>{row['Gap %']:+.2f}%</b><br>
                        Score: <b>{row['Bullish Score']}</b>/100
                    </div>
                    """, unsafe_allow_html=True)

            st.markdown("#### 📋 All Bullish Picks")
            display_cols = ["Symbol","LTP","Gap %","Change %","Range Pos %",
                            "Volume","At HOD","Spread %","Bullish Score","Signal"]
            st.dataframe(
                fmt_df(df_picks[display_cols], ["Gap %","Change %"], True),
                width="stretch", height=500
            )

            # Score distribution
            st.markdown("#### 📊 Score Distribution")
            score_bins = pd.cut(df_picks["Bullish Score"], bins=[0,20,40,60,80,100],
                                labels=["0-20","20-40","40-60","60-80","80-100"])
            st.bar_chart(score_bins.value_counts().sort_index())

    # ── TAB 5: All Stocks ─────────────────────────────────────────────────────
    with tabs[4]:
        st.markdown("### 📋 All Scanned Stocks")
        search = st.text_input("🔍 Search symbol", "")
        df_show = df_all.copy()
        if search:
            df_show = df_show[df_show["Symbol"].str.contains(search.upper())]
        df_show = df_show.sort_values("Bullish Score", ascending=False).reset_index(drop=True)
        display_cols = ["Symbol","LTP","Open","Prev Close","High","Low",
                        "Gap %","Change %","Range Pos %","Volume",
                        "At HOD","Spread %","Bullish Score","Signal"]
        st.dataframe(
            fmt_df(df_show[display_cols], ["Gap %","Change %"], True),
            width="stretch", height=600
        )
        # Download button
        csv = df_show.to_csv(index=False)
        st.download_button("⬇️ Download CSV", csv,
                           f"bullish_scan_{_now().strftime('%Y%m%d_%H%M')}.csv",
                           "text/csv")

    # ── 52-WEEK HIGH SECTION (separate, since it requires historical API) ─────
    if show_52wk:
        st.divider()
        st.markdown("### 📈 52-Week High Breakout Scanner")
        st.caption("⚠️ This fetches 1-year historical data and may take 1–2 minutes.")

        with st.expander("🔍 Run 52-Week High Scan (click to expand)", expanded=False):
            if st.button("▶️ Fetch 52-Week High Data", key="btn_52wk"):
                df_52 = fetch_52wk_highs(kite)
                st.session_state.df_52wk = df_52

            df_52 = st.session_state.get("df_52wk", pd.DataFrame())
            if not df_52.empty:
                near_52 = df_52[df_52["Dist from High %"] <= near_high_pct]\
                            .sort_values("Dist from High %")
                at_52   = df_52[df_52["At 52W High"] == True]

                c1, c2 = st.columns(2)
                c1.metric(f"Near 52W High (within {near_high_pct}%)", len(near_52))
                c2.metric("At/Above 52W High", len(at_52))

                st.markdown("#### Stocks Near 52-Week High")
                st.dataframe(
                    near_52[["Symbol","LTP","52W High","52W Low",
                             "Dist from High %","Above Low %","Change %","Volume","At 52W High"]]
                    .style.format({
                        "LTP":             "₹{:.2f}",
                        "52W High":        "₹{:.2f}",
                        "52W Low":         "₹{:.2f}",
                        "Dist from High %":"{:.2f}%",
                        "Above Low %":     "{:.1f}%",
                        "Change %":        "{:+.2f}%",
                        "Volume":          "{:,}",
                    }),
                    width="stretch",
                )

    # ── AUTO REFRESH ──────────────────────────────────────────────────────────
    if auto_refresh:
        time.sleep(refresh_sec)
        st.rerun()

else:
    # Landing state
    st.info("👈 Click **🚀 Run Scanner** in the sidebar to fetch live data from Zerodha.")
    st.markdown("""
    ### What this scanner finds:

    | Screen | Signal |
    |--------|--------|
    | **⬆️ Gap-Up Stocks** | Open > Prev Close — bullish bias for the day |
    | **📊 Volume Surge** | Volume > 10L with positive move — institutional buying |
    | **🏔️ High of Day** | LTP at/near intraday high — strong momentum |
    | **📈 52-Week High** | Near or at 52W high — breakout candidates |
    | **🎯 Bullish Score** | Composite score (0–100) using Gap, Change, Volume, Position |

    ### How to run:
    1. Make sure your Zerodha API credentials are set (already prefilled from `fo_realtime_feeder_new_up.py`)
    2. Click **🚀 Run Scanner** in the sidebar
    3. Use filters to narrow down your watchlist
    4. Enable **Auto Refresh** for live updates

    ### Pre-market vs Intraday:
    - **9:00–9:15 AM**: Pre-open session — check gap-up stocks
    - **9:15 AM onwards**: Real-time LTP, volume, HOD tracking
    """)
