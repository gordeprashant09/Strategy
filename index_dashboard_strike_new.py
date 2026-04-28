"""
╔══════════════════════════════════════════════════════════════════════════════╗
║  INDEX QUANT DASHBOARD — MFT (Market / Futures / Trading) Research Tool    ║
║                                                                              ║
║  Indices: NIFTY 50, BANKNIFTY, FINNIFTY, MIDCPNIFTY, SENSEX               ║
║                                                                              ║
║  Parameters for MFT traders:                                                ║
║   • Price, OI, OI Change, PCR (Put-Call Ratio)                             ║
║   • Futures Premium / Basis                                                  ║
║   • IV (Implied Volatility via ATM options)                                 ║
║   • VIX, ATR, Range Expansion                                               ║
║   • Trend Bias (EMA structure, price vs VWAP)                               ║
║   • Intraday Stats: HOD/LOD proximity, Range Position                       ║
║                                                                              ║
║  Run:  streamlit run index_dashboard.py                                     ║
║  Deps: pip install streamlit kiteconnect pyotp requests pandas numpy        ║
╚══════════════════════════════════════════════════════════════════════════════╝
"""

import os, sys, time, math, subprocess
from datetime import datetime, timedelta, timezone, date

# ── Auto-install ───────────────────────────────────────────────────────────────
def _pip(pkg):
    try: __import__(pkg.replace("-","_").split("[")[0])
    except ImportError:
        subprocess.run([sys.executable, "-m", "pip", "install", pkg,
                        "--quiet", "--break-system-packages"], check=True)

for p in ["streamlit", "kiteconnect", "pyotp", "requests", "pandas", "numpy"]:
    _pip(p)

import streamlit as st
import pandas as pd
import numpy as np
import requests
import pyotp
from kiteconnect import KiteConnect

# ═══════════════════════════════════════════════════════════════════════════════
#  CONFIG — reuses same Zerodha credentials
# ═══════════════════════════════════════════════════════════════════════════════
API_KEY    = os.getenv("KITE_API_KEY",  "4tl671rr7bwffw7b")
API_SECRET = os.getenv("KITE_SECRET",   "4gesk7v5vsbx9us4t8j3gh229zwzwf9t")
USER_ID    = os.getenv("KITE_USER_ID",  "QWK225")
PASSWORD   = os.getenv("KITE_PASSWORD", "Dec2025!")
TOTP_KEY   = os.getenv("KITE_TOTP_KEY", "VV2ZTNC3LG4V7EG7ECFLJIURPGVERJL7")
KITE_PIN   = os.getenv("KITE_PIN",      "123456")

IST = timezone(timedelta(hours=5, minutes=30))
def _now(): return datetime.now(IST)

# ═══════════════════════════════════════════════════════════════════════════════
#  INDEX CONFIG — Kite symbols for indices & their F&O names
# ═══════════════════════════════════════════════════════════════════════════════
INDEX_CONFIG = {
    "NIFTY 50": {
        "spot_sym":   "NSE:NIFTY 50",
        "fut_prefix": "NFO:NIFTY",
        "lot_size":   75,
        "color":      "#00e676",
        "icon":       "🏦",
        "expiry_sym": "NIFTY",
    },
    "BANKNIFTY": {
        "spot_sym":   "NSE:NIFTY BANK",
        "fut_prefix": "NFO:BANKNIFTY",
        "lot_size":   30,
        "color":      "#40c4ff",
        "icon":       "🏧",
        "expiry_sym": "BANKNIFTY",
    },
    "FINNIFTY": {
        "spot_sym":   "NSE:NIFTY FIN SERVICE",
        "fut_prefix": "NFO:FINNIFTY",
        "lot_size":   65,
        "color":      "#ce93d8",
        "icon":       "💹",
        "expiry_sym": "FINNIFTY",
    },
    "MIDCPNIFTY": {
        "spot_sym":   "NSE:NIFTY MID SELECT",
        "fut_prefix": "NFO:MIDCPNIFTY",
        "lot_size":   120,
        "color":      "#ffcc02",
        "icon":       "📊",
        "expiry_sym": "MIDCPNIFTY",
    },
    "SENSEX": {
        "spot_sym":   "BSE:SENSEX",
        "fut_prefix": "BFO:SENSEX",
        "lot_size":   20,
        "color":      "#ff7043",
        "icon":       "🔶",
        "expiry_sym": "SENSEX",
    },
}

VIX_SYM = "NSE:INDIA VIX"

# ═══════════════════════════════════════════════════════════════════════════════
#  PAGE CONFIG
# ═══════════════════════════════════════════════════════════════════════════════
st.set_page_config(
    page_title="📊 MFT Index Quant Dashboard",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown("""
<style>
/* ── Base ── */
.main, [data-testid="stAppViewContainer"], [data-testid="stHeader"] {
    background: #080c14 !important;
}
[data-testid="stSidebar"] { background: #0c111c !important; border-right: 1px solid #1a2235; }
body, .stMarkdown, p, li { color: #c8d4e0; }

/* ── Index Cards ── */
.idx-card {
    background: linear-gradient(160deg,#0f1826 0%,#151f30 100%);
    border: 1px solid #1e2e45;
    border-top: 3px solid var(--accent,#00e676);
    border-radius: 12px; padding: 14px 16px 12px; margin: 4px 0;
    transition: box-shadow .2s;
}
.idx-card:hover { box-shadow: 0 4px 20px #00000060; }
.idx-label { font-size:11px; color:#5a7090; font-weight:700; letter-spacing:1.2px; text-transform:uppercase; margin-bottom:4px; }
.idx-ltp   { font-size:26px; font-weight:900; line-height:1.15; }
.idx-chg   { font-size:13px; font-weight:700; margin-top:3px; }
.idx-hl    { font-size:11px; color:#4a6070; margin-top:5px; }
.pos { color:#00e676; } .neg { color:#ff4f4f; } .neu { color:#7a8a9a; }

/* ── Range bar ── */
.rbar-wrap { background:#101820; border-radius:4px; height:5px; margin:7px 0 3px; overflow:hidden; }
.rbar-fill  { height:5px; border-radius:4px; }
.range-bar-outer { background:#101820; border-radius:4px; height:6px; margin:6px 0; overflow:hidden; }
.range-bar-inner { height:6px; border-radius:4px; }

/* ── Param tiles ── */
.param-block, .ptile {
    background:#0e1624; border:1px solid #182030; border-radius:10px; padding:11px 14px; margin:3px 0;
}
.param-label, .ptile-label { font-size:10px; color:#4a6070; text-transform:uppercase; letter-spacing:.9px; }
.param-value, .ptile-val   { font-size:16px; font-weight:800; color:#dce8f4; margin:2px 0; }
.param-sub,   .ptile-sub   { font-size:10px; color:#3a5060; }

/* ── Badges ── */
.badge-bull, .b-bull { background:#072215; color:#00e676; border:1px solid #00a050; border-radius:5px; padding:2px 9px; font-size:11px; font-weight:800; }
.badge-bear, .b-bear { background:#220707; color:#ff5252; border:1px solid #a02020; border-radius:5px; padding:2px 9px; font-size:11px; font-weight:800; }
.badge-neut, .b-neut { background:#131822; color:#8899aa; border:1px solid #2a3545; border-radius:5px; padding:2px 9px; font-size:11px; font-weight:800; }
.badge-warn, .b-warn { background:#201800; color:#ffcc02; border:1px solid #806000; border-radius:5px; padding:2px 9px; font-size:11px; font-weight:800; }

/* ── Section headers ── */
.section-header, .sh {
    font-size:15px; font-weight:800; color:#4dd8a0;
    border-left:4px solid #00c070; padding-left:10px; margin:10px 0 8px;
}

/* ── VIX ── */
.vix-box {
    background:linear-gradient(145deg,#110d20,#1a1030);
    border:1px solid #3a1870; border-radius:12px; padding:16px; text-align:center;
}
.vix-val { font-size:34px; font-weight:900; color:#b388ff; }
.vix-lbl { font-size:11px; color:#7040b0; text-transform:uppercase; letter-spacing:1px; margin-bottom:4px; }

/* ── Trend dots ── */
.trend-row  { display:flex; align-items:center; gap:7px; margin:3px 0; }
.trend-dot-bull { width:8px; height:8px; border-radius:50%; background:#00e676; display:inline-block; flex-shrink:0; }
.trend-dot-bear { width:8px; height:8px; border-radius:50%; background:#ff5252; display:inline-block; flex-shrink:0; }
.trend-dot-neut { width:8px; height:8px; border-radius:50%; background:#607080; display:inline-block; flex-shrink:0; }

/* ── Streamlit component overrides ── */
div[data-testid="stDataFrame"] { border-radius:10px; overflow:hidden; }
div[data-testid="metric-container"] {
    background:#0e1624 !important; border:1px solid #1a2535 !important;
    border-radius:10px; padding:12px 16px !important;
}
div[data-testid="metric-container"] label {
    color:#5a7080 !important; font-size:11px !important;
    text-transform:uppercase; letter-spacing:.8px;
}
div[data-testid="metric-container"] [data-testid="stMetricValue"] {
    color:#dce8f4 !important; font-size:22px !important; font-weight:800 !important;
}
div[data-testid="metric-container"] [data-testid="stMetricDelta"] svg { display:none; }
div[data-testid="metric-container"] [data-testid="stMetricDelta"] { font-size:11px !important; }

.stButton>button {
    background:linear-gradient(135deg,#0d6efd,#0a4ecc) !important;
    color:#fff !important; border:none !important; border-radius:8px !important;
    font-weight:700 !important; padding:8px 20px !important;
}
.stButton>button:hover { opacity:.85 !important; }

h1 { color:#4dd8a0 !important; font-weight:900 !important; }
h2, h3 { color:#69f0ae !important; }
h4 { color:#a0c8b0 !important; }

.stTabs [data-baseweb="tab-list"] { gap:4px; border-bottom:1px solid #1a2535 !important; }
.stTabs [data-baseweb="tab"] {
    background:#0c1422 !important; border-radius:8px 8px 0 0 !important;
    color:#5a7080 !important; font-weight:600 !important;
    padding:8px 16px !important; border:1px solid #1a2535 !important;
}
.stTabs [aria-selected="true"] {
    background:#0f1f30 !important; color:#00e676 !important;
    border-color:#1e3a50 !important;
}
hr { border-color:#162030 !important; margin:10px 0 !important; }
[data-testid="stVerticalBlock"] > [data-testid="stVerticalBlock"] { gap:0.3rem !important; }
</style>
""", unsafe_allow_html=True)


# ═══════════════════════════════════════════════════════════════════════════════
#  AUTH
# ═══════════════════════════════════════════════════════════════════════════════
def zerodha_login():
    sess = requests.Session()
    sess.headers.update({"User-Agent":"Mozilla/5.0","Content-Type":"application/x-www-form-urlencoded"})
    r1 = sess.post("https://kite.zerodha.com/api/login",
                   data={"user_id": USER_ID, "password": PASSWORD}, timeout=20)
    j1 = r1.json()
    if j1.get("status") != "success":
        raise RuntimeError(f"Login failed: {j1.get('message')}")
    req_id = j1["data"]["request_id"]
    twofa  = j1["data"].get("twofa_type", "totp")
    tv     = pyotp.TOTP(TOTP_KEY).now() if "totp" in twofa.lower() else KITE_PIN
    r2 = sess.post("https://kite.zerodha.com/api/twofa",
                   data={"user_id": USER_ID, "request_id": req_id,
                         "twofa_value": tv, "twofa_type": twofa}, timeout=20)
    if r2.json().get("status") != "success":
        raise RuntimeError(f"TOTP failed: {r2.json().get('message')}")
    kite = KiteConnect(api_key=API_KEY)
    r3 = sess.get(f"https://kite.zerodha.com/connect/login?api_key={API_KEY}&v=3",
                  timeout=20, allow_redirects=True)
    from urllib.parse import urlparse, parse_qs
    rt = parse_qs(urlparse(r3.url).query).get("request_token", [None])[0]
    if not rt:
        raise RuntimeError("request_token not found")
    sd = kite.generate_session(rt, api_secret=API_SECRET)
    kite.set_access_token(sd["access_token"])
    return kite

def get_kite():
    if "kite" not in st.session_state or st.session_state.kite is None:
        with st.spinner("🔐 Logging into Zerodha..."):
            try:
                st.session_state.kite = zerodha_login()
                st.session_state.login_time = _now()
            except Exception as e:
                st.error(f"Login failed: {e}")
                return None
    return st.session_state.kite

# ═══════════════════════════════════════════════════════════════════════════════
#  HELPER — get nearest expiry Thursday (NSE weekly)
# ═══════════════════════════════════════════════════════════════════════════════
def nearest_thursday() -> str:
    today = _now().date()
    days_ahead = (3 - today.weekday()) % 7
    if days_ahead == 0 and _now().hour >= 15 and _now().minute >= 30:
        days_ahead = 7
    exp = today + timedelta(days=days_ahead)
    return exp.strftime("%y%b").upper()

def get_expiry_str(index_name: str) -> str:
    """Return the likely expiry string like 24DEC for futures."""
    today = _now().date()
    # last Thursday of current month
    year  = today.year
    month = today.month
    # check if we're close to expiry, move to next month if needed
    # find last Thursday
    last_day = date(year, month % 12 + 1, 1) - timedelta(days=1) if month < 12 else date(year+1, 1, 1) - timedelta(days=1)
    # find last Thursday of month
    dow = last_day.weekday()
    last_thu = last_day - timedelta(days=(dow - 3) % 7)
    if today > last_thu:
        # move to next month
        month = month % 12 + 1
        if month == 1: year += 1
        last_day = date(year, month % 12 + 1, 1) - timedelta(days=1) if month < 12 else date(year+1, 1, 1) - timedelta(days=1)
        dow = last_day.weekday()
        last_thu = last_day - timedelta(days=(dow - 3) % 7)
    return last_thu.strftime("%y%b").upper()

def get_weekly_expiry_str() -> str:
    """Nearest weekly expiry for BANKNIFTY / FINNIFTY / NIFTY options."""
    return nearest_thursday()

# ═══════════════════════════════════════════════════════════════════════════════
#  FETCH INDEX SPOT DATA
# ═══════════════════════════════════════════════════════════════════════════════
def fetch_spot_data(kite) -> dict:
    """Fetch all index spots + VIX in one call."""
    syms = [cfg["spot_sym"] for cfg in INDEX_CONFIG.values()] + [VIX_SYM]
    try:
        raw = kite.quote(syms)
    except Exception as e:
        st.warning(f"Spot fetch error: {e}")
        return {}
    result = {}
    for name, cfg in INDEX_CONFIG.items():
        q = raw.get(cfg["spot_sym"]) or {}
        ohlc = q.get("ohlc") or {}
        ltp        = float(q.get("last_price") or 0)
        prev_close = float(ohlc.get("close") or 0)
        open_      = float(ohlc.get("open")  or 0)
        high       = float(ohlc.get("high")  or 0)
        low        = float(ohlc.get("low")   or 0)
        chg        = float(q.get("change") or 0)
        chg_abs    = ltp - prev_close if prev_close else 0
        gap_pct    = (open_ - prev_close) / prev_close * 100 if prev_close else 0
        range_pos  = (ltp - low) / (high - low) * 100 if high != low else 50
        result[name] = {
            "ltp": ltp, "open": open_, "prev_close": prev_close,
            "high": high, "low": low,
            "chg_pct": round(chg, 2), "chg_abs": round(chg_abs, 2),
            "gap_pct": round(gap_pct, 2),
            "range_pos": round(range_pos, 1),
            "day_range": round(high - low, 2),
        }
    vix_q = raw.get(VIX_SYM) or {}
    result["__VIX__"] = {
        "ltp": float(vix_q.get("last_price") or 0),
        "chg_pct": float(vix_q.get("change") or 0),
        "prev_close": float((vix_q.get("ohlc") or {}).get("close") or 0),
    }
    return result

# ═══════════════════════════════════════════════════════════════════════════════
#  FETCH FUTURES DATA
# ═══════════════════════════════════════════════════════════════════════════════
def fetch_futures(kite, instruments_df: pd.DataFrame) -> dict:
    """
    Try to find near-month futures for each index and fetch OI + price.
    Instruments list is used to resolve the actual trading symbol.
    """
    result = {}
    for name, cfg in INDEX_CONFIG.items():
        exp_str = get_expiry_str(name)
        expiry  = cfg["expiry_sym"]
        exchange = "BFO" if name == "SENSEX" else "NFO"
        # Build candidate symbols
        candidate_syms = []
        if not instruments_df.empty:
            mask = (
                (instruments_df["name"] == expiry) &
                (instruments_df["segment"].str.startswith(exchange)) &
                (instruments_df["instrument_type"] == "FUT")
            )
            fut_rows = instruments_df[mask].sort_values("expiry")
            if not fut_rows.empty:
                row = fut_rows.iloc[0]
                candidate_syms = [f"{exchange}:{row['tradingsymbol']}"]

        if not candidate_syms:
            result[name] = {}
            continue

        try:
            raw = kite.quote(candidate_syms)
            q   = raw.get(candidate_syms[0]) or {}
            ohlc= q.get("ohlc") or {}
            result[name] = {
                "fut_ltp":  float(q.get("last_price") or 0),
                "fut_oi":   int(q.get("oi") or 0),
                "fut_oi_chg": int(q.get("oi_day_high") or 0) - int(q.get("oi_day_low") or 0),
                "fut_vol":  int(q.get("volume") or 0),
                "fut_high": float(ohlc.get("high") or 0),
                "fut_low":  float(ohlc.get("low")  or 0),
                "sym":      candidate_syms[0],
            }
        except Exception:
            result[name] = {}

    return result

# ═══════════════════════════════════════════════════════════════════════════════
#  FETCH OPTIONS CHAIN (ATM only) for PCR + IV
# ═══════════════════════════════════════════════════════════════════════════════
def fetch_atm_options(kite, instruments_df: pd.DataFrame, spot_data: dict) -> dict:
    """
    Fetch ATM CE + PE for each index to compute:
    - PCR (Put-Call Ratio by OI)
    - ATM IV (proxy: compare CE/PE price to theoretical)
    - Total OI in 3 strikes around ATM
    """
    result = {}
    for name, cfg in INDEX_CONFIG.items():
        spot = (spot_data.get(name) or {}).get("ltp", 0)
        if spot <= 0:
            result[name] = {}
            continue
        expiry  = cfg["expiry_sym"]
        is_bfo  = (name == "SENSEX")
        exchange = "BFO" if is_bfo else "NFO"
        seg_opt  = "BFO-OPT" if is_bfo else "NFO-OPT"
        # Determine strike step
        step_map = {"NIFTY 50": 50, "BANKNIFTY": 100, "FINNIFTY": 50, "MIDCPNIFTY": 25, "SENSEX": 100}
        step = step_map.get(name, 100)
        atm  = round(spot / step) * step

        try:
            mask = (
                (instruments_df["name"] == expiry) &
                (instruments_df["segment"] == seg_opt) &
                (instruments_df["strike"].between(atm - step*4, atm + step*4))
            )
            opt_rows = instruments_df[mask].copy()
            if opt_rows.empty:
                result[name] = {}
                continue

            # Pick nearest expiry
            opt_rows = opt_rows.sort_values("expiry")
            nearest_exp = opt_rows["expiry"].iloc[0]
            opt_rows = opt_rows[opt_rows["expiry"] == nearest_exp]

            syms = [f"{exchange}:" + ts for ts in opt_rows["tradingsymbol"].tolist()[:40]]
            raw  = kite.quote(syms)

            total_ce_oi = total_pe_oi = 0
            atm_ce_price = atm_pe_price = 0
            atm_ce_iv = atm_pe_iv = 0

            for ts, q in raw.items():
                sym_name = ts.split(":")[1]
                row = opt_rows[opt_rows["tradingsymbol"] == sym_name]
                if row.empty: continue
                row = row.iloc[0]
                oi    = int(q.get("oi") or 0)
                price = float(q.get("last_price") or 0)

                if row["instrument_type"] == "CE":
                    total_ce_oi += oi
                    if row["strike"] == atm:
                        atm_ce_price = price
                elif row["instrument_type"] == "PE":
                    total_pe_oi += oi
                    if row["strike"] == atm:
                        atm_pe_price = price

            pcr = round(total_pe_oi / total_ce_oi, 3) if total_ce_oi else 0
            result[name] = {
                "pcr":          pcr,
                "atm":          atm,
                "atm_ce_price": round(atm_ce_price, 2),
                "atm_pe_price": round(atm_pe_price, 2),
                "total_ce_oi":  total_ce_oi,
                "total_pe_oi":  total_pe_oi,
                "exp_date":     str(nearest_exp)[:10],
            }
        except Exception as ex:
            result[name] = {"error": str(ex)}

    return result

# ═══════════════════════════════════════════════════════════════════════════════
#  FETCH HISTORICAL for ATR (5-day)
# ═══════════════════════════════════════════════════════════════════════════════
def fetch_atr(kite, instruments_df: pd.DataFrame) -> dict:
    """5-day ATR for each index using daily candles."""
    result = {}
    today  = _now().date()
    from_  = (today - timedelta(days=30)).strftime("%Y-%m-%d")
    to_    = today.strftime("%Y-%m-%d")

    # Instrument tokens for indices
    index_tokens = {
        "NIFTY 50":    256265,
        "BANKNIFTY":   260105,
        "FINNIFTY":    257801,
        "MIDCPNIFTY":  288009,
        "SENSEX":      265,
    }
    for name, token in index_tokens.items():
        try:
            hist = kite.historical_data(
                instrument_token=token,
                from_date=from_, to_date=to_,
                interval="day",
            )
            if len(hist) < 2:
                result[name] = {}
                continue
            df = pd.DataFrame(hist)
            df["prev_close"] = df["close"].shift(1)
            df["tr"] = df.apply(lambda r: max(
                r["high"] - r["low"],
                abs(r["high"] - r["prev_close"]),
                abs(r["low"]  - r["prev_close"])
            ) if r["prev_close"] > 0 else r["high"] - r["low"], axis=1)
            atr5  = round(df["tr"].tail(5).mean(), 2)
            atr14 = round(df["tr"].tail(14).mean(), 2)
            today_range = df.iloc[-1]["high"] - df.iloc[-1]["low"]
            atr_expansion = round(today_range / atr5 * 100, 1) if atr5 else 0
            result[name] = {
                "atr5": atr5, "atr14": atr14,
                "atr_expansion": atr_expansion,
                "today_range": round(today_range, 2),
            }
        except Exception:
            result[name] = {}

    return result

# ═══════════════════════════════════════════════════════════════════════════════
#  DERIVED SIGNALS
# ═══════════════════════════════════════════════════════════════════════════════
def compute_trend_bias(spot: dict, fut: dict) -> dict:
    """
    Determine trend bias from multiple factors:
    - Price vs Open (above = bullish intraday)
    - Gap direction
    - Range position (upper = bullish)
    - Futures premium
    - PCR
    """
    ltp     = spot.get("ltp", 0)
    open_   = spot.get("open", 0)
    prev_cl = spot.get("prev_close", 0)
    range_p = spot.get("range_pos", 50)
    gap_p   = spot.get("gap_pct", 0)
    chg_p   = spot.get("chg_pct", 0)

    score = 0  # -100 to +100
    signals = []

    # 1. Price vs open
    if ltp > open_:
        score += 20; signals.append(("Bull", "LTP > Open"))
    elif ltp < open_:
        score -= 20; signals.append(("Bear", "LTP < Open"))

    # 2. Gap direction
    if gap_p > 0.3:
        score += 15; signals.append(("Bull", f"Gap Up {gap_p:+.2f}%"))
    elif gap_p < -0.3:
        score -= 15; signals.append(("Bear", f"Gap Down {gap_p:+.2f}%"))

    # 3. Range position
    if range_p > 70:
        score += 15; signals.append(("Bull", f"Range Pos {range_p:.0f}%"))
    elif range_p < 30:
        score -= 15; signals.append(("Bear", f"Range Pos {range_p:.0f}%"))

    # 4. Change %
    if chg_p > 0.5:
        score += 10; signals.append(("Bull", f"Change {chg_p:+.2f}%"))
    elif chg_p < -0.5:
        score -= 10; signals.append(("Bear", f"Change {chg_p:+.2f}%"))

    # 5. Futures premium
    fut_ltp = fut.get("fut_ltp", 0)
    if fut_ltp and ltp:
        basis_pct = (fut_ltp - ltp) / ltp * 100
        if basis_pct > 0.1:
            score += 10; signals.append(("Bull", f"Fut Premium {basis_pct:+.2f}%"))
        elif basis_pct < -0.1:
            score -= 10; signals.append(("Bear", f"Fut Discount {basis_pct:+.2f}%"))

    if score >= 30:
        trend = "BULLISH"; badge = "bull"
    elif score <= -30:
        trend = "BEARISH"; badge = "bear"
    else:
        trend = "SIDEWAYS"; badge = "neut"

    return {"score": score, "trend": trend, "badge": badge, "signals": signals}

def pcr_signal(pcr: float) -> tuple:
    """Interpret PCR for directional bias."""
    if pcr == 0:    return "N/A",    "neut", "No data"
    if pcr > 1.3:   return "BULLISH","bull", "High PE OI → support likely"
    if pcr > 1.0:   return "MILDLY BULLISH","bull","PE writers dominating"
    if pcr < 0.7:   return "BEARISH","bear","CE writers dominant → supply"
    if pcr < 0.9:   return "MILDLY BEARISH","bear","CE OI building up"
    return "NEUTRAL","neut","PCR near equilibrium"

def vix_signal(vix: float) -> tuple:
    """VIX regime."""
    if vix == 0:    return "N/A", "neut"
    if vix < 12:    return "VERY LOW — Complacency", "warn"
    if vix < 15:    return "LOW — Calm Market", "bull"
    if vix < 20:    return "NORMAL Volatility", "neut"
    if vix < 25:    return "ELEVATED — Caution", "warn"
    if vix < 30:    return "HIGH — Panic Zone", "bear"
    return "EXTREME — High Risk", "bear"

def atr_expansion_signal(exp: float) -> str:
    if exp == 0:    return "N/A"
    if exp > 150:   return "🔥 Expanding Range"
    if exp > 100:   return "📈 Normal Range"
    if exp > 60:    return "😴 Contracting Range"
    return "🪤 Tight Consolidation"

# ═══════════════════════════════════════════════════════════════════════════════
#  FETCH STRIKE CHAIN (wider) for Trade Suggester
# ═══════════════════════════════════════════════════════════════════════════════
def fetch_strike_chain(kite, instruments_df: pd.DataFrame, name: str, spot: float) -> pd.DataFrame:
    """
    Fetch ±8 strikes around ATM for the selected index.
    Returns a DataFrame with strike, CE price/OI, PE price/OI.
    """
    cfg      = INDEX_CONFIG[name]
    expiry   = cfg["expiry_sym"]
    is_bfo   = (name == "SENSEX")
    exchange = "BFO" if is_bfo else "NFO"
    seg_opt  = "BFO-OPT" if is_bfo else "NFO-OPT"
    step_map = {"NIFTY 50": 50, "BANKNIFTY": 100, "FINNIFTY": 50, "MIDCPNIFTY": 25, "SENSEX": 100}
    step     = step_map.get(name, 100)
    atm      = round(spot / step) * step

    if instruments_df.empty:
        return pd.DataFrame()

    mask = (
        (instruments_df["name"] == expiry) &
        (instruments_df["segment"] == seg_opt) &
        (instruments_df["strike"].between(atm - step*8, atm + step*8))
    )
    opt_rows = instruments_df[mask].copy()
    if opt_rows.empty:
        return pd.DataFrame()

    opt_rows = opt_rows.sort_values("expiry")
    nearest_exp = opt_rows["expiry"].iloc[0]
    opt_rows = opt_rows[opt_rows["expiry"] == nearest_exp]

    syms = [f"{exchange}:{ts}" for ts in opt_rows["tradingsymbol"].tolist()]
    try:
        raw = kite.quote(syms[:80])
    except Exception as e:
        st.warning(f"Strike chain fetch error: {e}")
        return pd.DataFrame()

    chain = {}
    for ts_full, q in raw.items():
        ts_name = ts_full.split(":")[1]
        row = opt_rows[opt_rows["tradingsymbol"] == ts_name]
        if row.empty: continue
        row = row.iloc[0]
        strike = int(row["strike"])
        itype  = row["instrument_type"]
        price  = float(q.get("last_price") or 0)
        oi     = int(q.get("oi") or 0)
        iv     = float(q.get("average_price") or 0)  # proxy
        ts_sym = ts_name

        if strike not in chain:
            chain[strike] = {"strike": strike, "ce_price": 0, "ce_oi": 0, "ce_sym": "",
                             "pe_price": 0, "pe_oi": 0, "pe_sym": ""}
        if itype == "CE":
            chain[strike]["ce_price"] = price
            chain[strike]["ce_oi"]    = oi
            chain[strike]["ce_sym"]   = ts_sym
        elif itype == "PE":
            chain[strike]["pe_price"] = price
            chain[strike]["pe_oi"]    = oi
            chain[strike]["pe_sym"]   = ts_sym

    df_chain = pd.DataFrame(chain.values()).sort_values("strike").reset_index(drop=True)
    df_chain["atm"]  = atm
    df_chain["step"] = step
    df_chain["exp"]  = str(nearest_exp)[:10]
    return df_chain


# ═══════════════════════════════════════════════════════════════════════════════
#  TRADE SUGGESTER ENGINE
# ═══════════════════════════════════════════════════════════════════════════════
def suggest_trades(name: str, spot_data: dict, futures_data: dict,
                   options_data: dict, atr_data: dict, chain_df: pd.DataFrame,
                   vix_val: float, risk_profile: str = "moderate") -> list:
    """
    Combines ALL parameters to suggest 1-3 option trades with strike, SL, target.
    Returns list of trade dicts.
    """
    s   = spot_data.get(name, {})
    f   = futures_data.get(name, {})
    o   = options_data.get(name, {})
    a   = atr_data.get(name, {})

    ltp     = s.get("ltp", 0)
    if not ltp or chain_df.empty:
        return []

    open_   = s.get("open", 0)
    high    = s.get("high", 0)
    low     = s.get("low", 0)
    prev_cl = s.get("prev_close", 0)
    chg_p   = s.get("chg_pct", 0)
    gap_p   = s.get("gap_pct", 0)
    rp      = s.get("range_pos", 50)

    pcr     = o.get("pcr", 0)
    atm     = o.get("atm", 0) or chain_df["atm"].iloc[0]
    step    = chain_df["step"].iloc[0]
    exp_dt  = chain_df["exp"].iloc[0]

    atr5    = a.get("atr5", 0)
    atr_exp = a.get("atr_expansion", 0)
    tb      = compute_trend_bias(s, f)
    bias_sc = tb["score"]
    trend   = tb["trend"]

    fut_ltp  = f.get("fut_ltp", 0)
    basis_p  = (fut_ltp - ltp) / ltp * 100 if fut_ltp and ltp else 0

    cfg      = INDEX_CONFIG[name]
    lot_size = cfg["lot_size"]

    # ── Risk multipliers by VIX ─────────────────────────────────────────────
    if vix_val > 25:
        sl_mult, tgt_mult = 0.25, 0.40   # tight SL in panic
    elif vix_val > 18:
        sl_mult, tgt_mult = 0.30, 0.50
    else:
        sl_mult, tgt_mult = 0.35, 0.60   # normal vol

    if risk_profile == "aggressive":
        sl_mult  *= 1.4
        tgt_mult *= 1.5
    elif risk_profile == "conservative":
        sl_mult  *= 0.7
        tgt_mult *= 0.8

    trades = []

    def _chain_row(strike):
        rows = chain_df[chain_df["strike"] == strike]
        return rows.iloc[0] if not rows.empty else None

    def _build_trade(direction, strike, option_type, reason, confidence):
        row = _chain_row(strike)
        if row is None: return None
        opt_price = row[f"{option_type.lower()}_price"]
        opt_oi    = row[f"{option_type.lower()}_oi"]
        opt_sym   = row[f"{option_type.lower()}_sym"]
        if opt_price <= 0: return None

        sl_pts  = round(opt_price * sl_mult, 2)
        tgt_pts = round(opt_price * tgt_mult * 2, 2)   # 2:1 minimum
        sl      = round(opt_price - sl_pts, 2)
        tgt1    = round(opt_price + tgt_pts, 2)
        tgt2    = round(opt_price + tgt_pts * 1.5, 2)

        # Risk-reward ratio
        rr = round(tgt_pts / sl_pts, 2) if sl_pts else 0

        # Lot value
        lot_val  = round(opt_price * lot_size, 0)

        # Confidence → color
        conf_map = {"HIGH": "#00e676", "MEDIUM": "#ffcc02", "LOW": "#ff9800"}
        conf_col = conf_map.get(confidence, "#aaa")

        return {
            "direction":   direction,
            "index":       name,
            "symbol":      opt_sym,
            "display_sym": f"{cfg['expiry_sym']}{strike}{option_type}",
            "option_type": option_type,
            "strike":      strike,
            "spot":        ltp,
            "atm":         atm,
            "moneyness":   "ATM" if strike == atm else (f"OTM {abs(strike-atm)//step} step" if (option_type=="CE" and strike>atm) or (option_type=="PE" and strike<atm) else f"ITM {abs(strike-atm)//step} step"),
            "entry":       opt_price,
            "sl":          max(sl, 0.5),
            "sl_pct":      round(sl_mult*100, 1),
            "target1":     tgt1,
            "target2":     tgt2,
            "rr_ratio":    rr,
            "lot_size":    lot_size,
            "lot_value":   lot_val,
            "oi":          opt_oi,
            "expiry":      exp_dt,
            "confidence":  confidence,
            "conf_color":  conf_col,
            "reason":      reason,
            "bias_score":  bias_sc,
            "pcr":         pcr,
            "vix":         vix_val,
            "atr5":        atr5,
        }

    # ── TRADE LOGIC ──────────────────────────────────────────────────────────

    # === STRONG BULLISH ===
    if bias_sc >= 40 and pcr >= 1.1 and rp > 65:
        # ATM CE — momentum trade
        t = _build_trade("BUY", atm, "CE",
            f"Strong Bull: Score={bias_sc:+d}, PCR={pcr:.2f}, Range={rp:.0f}%, Gap={gap_p:+.2f}%",
            "HIGH")
        if t: trades.append(t)
        # 1-step OTM CE — aggressive
        t = _build_trade("BUY", atm + step, "CE",
            f"Momentum OTM: Trend={trend}, VIX={vix_val:.1f}, ATR-Exp={atr_exp:.0f}%",
            "MEDIUM")
        if t: trades.append(t)

    # === MODERATE BULLISH ===
    elif bias_sc >= 20 and (pcr >= 0.95 or gap_p > 0.2):
        t = _build_trade("BUY", atm, "CE",
            f"Moderate Bull: Score={bias_sc:+d}, PCR={pcr:.2f}, LTP>Open={ltp>open_}",
            "MEDIUM")
        if t: trades.append(t)
        # Also suggest 1-step OTM PE sell (only if PCR supports)
        if pcr > 1.1:
            t = _build_trade("SELL", atm - step, "PE",
                f"PE Sell: PCR={pcr:.2f} → Put writers support, SL at ATM PE",
                "LOW")
            if t: trades.append(t)

    # === STRONG BEARISH ===
    elif bias_sc <= -40 and pcr <= 0.85 and rp < 35:
        t = _build_trade("BUY", atm, "PE",
            f"Strong Bear: Score={bias_sc:+d}, PCR={pcr:.2f}, Range={rp:.0f}%, Gap={gap_p:+.2f}%",
            "HIGH")
        if t: trades.append(t)
        t = _build_trade("BUY", atm - step, "PE",
            f"Momentum OTM Put: Trend={trend}, VIX={vix_val:.1f}",
            "MEDIUM")
        if t: trades.append(t)

    # === MODERATE BEARISH ===
    elif bias_sc <= -20 and (pcr <= 1.0 or gap_p < -0.2):
        t = _build_trade("BUY", atm, "PE",
            f"Moderate Bear: Score={bias_sc:+d}, PCR={pcr:.2f}, LTP<Open={ltp<open_}",
            "MEDIUM")
        if t: trades.append(t)

    # === SIDEWAYS / HIGH VIX → SELL STRADDLE / STRANGLE ===
    elif abs(bias_sc) < 20 and vix_val > 15 and atr_exp < 90:
        # Suggest short straddle (ATM CE sell + ATM PE sell)
        t_ce = _build_trade("SELL", atm, "CE",
            f"Range-bound: Score={bias_sc:+d}, ATR-Exp={atr_exp:.0f}% (low), Straddle sell",
            "MEDIUM")
        t_pe = _build_trade("SELL", atm, "PE",
            f"Range-bound: Sideways day, VIX={vix_val:.1f}, Collect premium",
            "MEDIUM")
        if t_ce: trades.append(t_ce)
        if t_pe: trades.append(t_pe)

    # === DEFAULT — ATM CE/PE based on minimal bias ===
    else:
        opt_type = "CE" if bias_sc >= 0 else "PE"
        conf = "LOW"
        t = _build_trade("BUY", atm, opt_type,
            f"Weak signal: Score={bias_sc:+d}, confirm before trading",
            conf)
        if t: trades.append(t)

    return trades[:3]   # max 3 suggestions


# ═══════════════════════════════════════════════════════════════════════════════
#  SIDEBAR
# ═══════════════════════════════════════════════════════════════════════════════
with st.sidebar:
    st.markdown("## ⚙️ Dashboard Controls")
    st.divider()
    auto_refresh  = st.toggle("🔄 Auto Refresh", value=False)
    refresh_sec   = st.slider("Refresh every (sec)", 15, 300, 60, step=15,
                              disabled=not auto_refresh)
    st.divider()
    st.markdown("### 📌 Display")
    show_options  = st.checkbox("Options Chain (PCR / IV)", value=True)
    show_futures  = st.checkbox("Futures Data (OI / Basis)", value=True)
    show_atr      = st.checkbox("Volatility (ATR / VIX)", value=True)
    show_signals  = st.checkbox("Signal Summary Table", value=True)
    show_intraday = st.checkbox("Intraday Stats", value=True)
    st.divider()
    fetch_btn = st.button("🚀 Fetch Live Data", use_container_width=True)
    st.markdown('<p style="color:#556677;font-size:11px;margin-top:8px">Zerodha KiteConnect • MFT Quant Dashboard</p>',
                unsafe_allow_html=True)

# ═══════════════════════════════════════════════════════════════════════════════
#  HEADER
# ═══════════════════════════════════════════════════════════════════════════════
now_ist = _now()
market_open = (9*60+15) <= (now_ist.hour*60+now_ist.minute) <= (15*60+30) and now_ist.weekday() < 5
pre_open    = (9*60) <= (now_ist.hour*60+now_ist.minute) < (9*60+15) and now_ist.weekday() < 5
mkt_color   = "#00e676" if market_open else ("#ffcc02" if pre_open else "#ff5252")
mkt_label   = "● MARKET OPEN" if market_open else ("● PRE-OPEN" if pre_open else "● CLOSED")

page_header = (
    '<div style="display:flex;align-items:center;justify-content:space-between;padding:10px 0 6px;flex-wrap:wrap;gap:8px">' +
    '<div>' +
    '<div style="font-size:26px;font-weight:900;color:#4dd8a0;letter-spacing:-0.5px">📊 MFT Index Dashboard</div>' +
    '<div style="font-size:12px;color:#3a5060;margin-top:2px">NIFTY &nbsp;·&nbsp; BANKNIFTY &nbsp;·&nbsp; FINNIFTY &nbsp;·&nbsp; MIDCPNIFTY &nbsp;·&nbsp; SENSEX &nbsp;—&nbsp; Zerodha KiteConnect</div>' +
    '</div>' +
    '<div style="display:flex;gap:12px;align-items:center;flex-wrap:wrap">' +
    f'<div style="background:#0d1624;border:1px solid #1a2535;border-radius:8px;padding:8px 16px;text-align:center">' +
    f'<div style="font-size:10px;color:#3a5060;text-transform:uppercase">IST Time</div>' +
    f'<div style="font-size:16px;font-weight:800;color:#c8d4e0">{now_ist.strftime("%H:%M:%S")}</div></div>' +
    f'<div style="background:#0d1624;border:1px solid #1a2535;border-radius:8px;padding:8px 16px;text-align:center">' +
    f'<div style="font-size:10px;color:#3a5060;text-transform:uppercase">Market</div>' +
    f'<div style="font-size:14px;font-weight:800;color:{mkt_color}">{mkt_label}</div></div>' +
    f'<div style="background:#0d1624;border:1px solid #1a2535;border-radius:8px;padding:8px 16px;text-align:center">' +
    f'<div style="font-size:10px;color:#3a5060;text-transform:uppercase">Date</div>' +
    f'<div style="font-size:14px;font-weight:800;color:#c8d4e0">{now_ist.strftime("%d %b %Y")}</div></div>' +
    f'<div style="background:#0d1624;border:1px solid #1a2535;border-radius:8px;padding:8px 16px;text-align:center">' +
    f'<div style="font-size:10px;color:#3a5060;text-transform:uppercase">Account</div>' +
    f'<div style="font-size:14px;font-weight:800;color:#c8d4e0">{USER_ID}</div></div>' +
    '</div></div>'
)
st.markdown(page_header, unsafe_allow_html=True)
st.divider()

# ═══════════════════════════════════════════════════════════════════════════════
#  AUTO-REFRESH TRIGGER
# ═══════════════════════════════════════════════════════════════════════════════
if auto_refresh:
    if "last_fetch" not in st.session_state:
        st.session_state.last_fetch = 0
    if time.time() - st.session_state.last_fetch >= refresh_sec:
        fetch_btn = True

# ═══════════════════════════════════════════════════════════════════════════════
#  MAIN DATA FETCH
# ═══════════════════════════════════════════════════════════════════════════════
if fetch_btn or "idx_spot" in st.session_state:
    kite = get_kite()
    if kite is None: st.stop()

    if fetch_btn:
        st.session_state.last_fetch = time.time()

        with st.spinner("📡 Fetching index spot data..."):
            st.session_state.idx_spot = fetch_spot_data(kite)

        # Instruments list (needed for futures & options)
        if "instruments_df" not in st.session_state:
            with st.spinner("📋 Loading instruments list..."):
                try:
                    instr_nfo = kite.instruments("NFO")
                    try:
                        instr_bfo = kite.instruments("BFO")
                    except Exception:
                        instr_bfo = []
                    all_instr = instr_nfo + list(instr_bfo)
                    st.session_state.instruments_df = pd.DataFrame(all_instr)
                    # ensure types
                    df_i = st.session_state.instruments_df
                    if "strike" in df_i.columns:
                        df_i["strike"] = pd.to_numeric(df_i["strike"], errors="coerce")
                    if "expiry" in df_i.columns:
                        df_i["expiry"] = pd.to_datetime(df_i["expiry"], errors="coerce")
                    st.session_state.instruments_df = df_i
                except Exception as e:
                    st.session_state.instruments_df = pd.DataFrame()
                    st.warning(f"Could not load instruments: {e}")

        df_instruments = st.session_state.get("instruments_df", pd.DataFrame())

        if show_futures and not df_instruments.empty:
            with st.spinner("📈 Fetching futures data..."):
                st.session_state.idx_futures = fetch_futures(kite, df_instruments)
        else:
            st.session_state.idx_futures = {}

        if show_options and not df_instruments.empty:
            with st.spinner("🔗 Fetching ATM options chain (PCR / IV)..."):
                st.session_state.idx_options = fetch_atm_options(kite, df_instruments, st.session_state.idx_spot)
        else:
            st.session_state.idx_options = {}

        if show_atr:
            with st.spinner("📉 Fetching historical ATR..."):
                st.session_state.idx_atr = fetch_atr(kite, df_instruments)
        else:
            st.session_state.idx_atr = {}

        st.session_state.fetch_time = _now().strftime("%H:%M:%S")

    # ── Pull from session state ─────────────────────────────────────────────
    spot_data    = st.session_state.get("idx_spot", {})
    futures_data = st.session_state.get("idx_futures", {})
    options_data = st.session_state.get("idx_options", {})
    atr_data     = st.session_state.get("idx_atr", {})
    fetch_time   = st.session_state.get("fetch_time", "")
    vix          = spot_data.get("__VIX__", {})

    if not spot_data:
        st.warning("No data. Try again after market open.")
        st.stop()

    st.markdown(f"**🕐 Last Fetch:** `{fetch_time}`", unsafe_allow_html=True)
    st.divider()

    # ═══════════════════════════════════════════════════════════════════════
    #  TOP ROW — INDEX CARDS
    # ═══════════════════════════════════════════════════════════════════════
    st.markdown('<div class="section-header">📌 Index Snapshot</div>', unsafe_allow_html=True)

    cols = st.columns(len(INDEX_CONFIG))
    for col, (name, cfg) in zip(cols, INDEX_CONFIG.items()):
        s = spot_data.get(name, {})
        ltp     = s.get("ltp", 0)
        chg_p   = s.get("chg_pct", 0)
        chg_abs = s.get("chg_abs", 0)
        high    = s.get("high", 0)
        low     = s.get("low", 0)
        rp      = s.get("range_pos", 50)
        gap_p   = s.get("gap_pct", 0)

        chg_cls  = "pos" if chg_p > 0 else ("neg" if chg_p < 0 else "neu")
        chg_sign = "+" if chg_p >= 0 else ""
        gap_sign = "+" if gap_p >= 0 else ""
        rp_c     = max(0, min(100, rp))
        bar_col  = "#00e676" if chg_p >= 0 else "#ff4f4f"
        lot      = cfg["lot_size"]

        with col:
            html_card = (
                f'<div class="idx-card" style="--accent:{cfg["color"]}">' +
                f'<div class="idx-label">{cfg["icon"]} {name} <span style="font-size:10px;color:#344858">Lot {lot}</span></div>' +
                f'<div class="idx-ltp" style="color:{cfg["color"]}">{ltp:,.2f}</div>' +
                f'<div class="idx-chg {chg_cls}">{chg_sign}{chg_p:.2f}%&nbsp;({chg_sign}{chg_abs:.2f})</div>' +
                f'<div class="idx-hl">H {high:,.2f} &middot; L {low:,.2f}</div>' +
                f'<div class="rbar-wrap"><div class="rbar-fill" style="width:{rp_c}%;background:{bar_col}"></div></div>' +
                f'<div style="font-size:10px;color:#344858">Range {rp:.0f}% &middot; Gap {gap_sign}{gap_p:.2f}%</div>' +
                '</div>'
            )
            st.markdown(html_card, unsafe_allow_html=True)

    st.divider()

    # ═══════════════════════════════════════════════════════════════════════
    #  VIX PANEL
    # ═══════════════════════════════════════════════════════════════════════
    vix_val = vix.get("ltp", 0)
    vix_chg = vix.get("chg_pct", 0)
    vix_label, vix_badge = vix_signal(vix_val)
    badge_cls = f"badge-{vix_badge}"

    v_col1, v_col2 = st.columns([1, 4])
    with v_col1:
        sign = "+" if vix_chg >= 0 else ""
        chg_col = "#ff5252" if vix_chg > 0 else "#00e676"
        vix_html = (
            '<div class="vix-box">' +
            '<div class="vix-lbl">India VIX</div>' +
            f'<div class="vix-val">{vix_val:.2f}</div>' +
            f'<div style="color:{chg_col};font-size:13px;font-weight:700">{sign}{vix_chg:.2f}%</div>' +
            f'<div style="margin-top:8px"><span class="{badge_cls}">{vix_label}</span></div>' +
            '<div style="font-size:10px;color:#50308a;margin-top:6px">&lt;15 Low &middot; &gt;20 Caution &middot; &gt;25 Panic</div>' +
            '</div>'
        )
        st.markdown(vix_html, unsafe_allow_html=True)

    with v_col2:
        st.markdown('<div class="section-header">🎯 Trend Bias — Multi-Factor Score</div>', unsafe_allow_html=True)
        t_cols = st.columns(len(INDEX_CONFIG))
        for tc, (name, cfg) in zip(t_cols, INDEX_CONFIG.items()):
            s  = spot_data.get(name, {})
            f  = futures_data.get(name, {})
            tb = compute_trend_bias(s, f)
            badge_class = f"badge-{tb['badge']}"
            score_color = "#00e676" if tb["score"] > 0 else ("#ff5252" if tb["score"] < 0 else "#aaa")
            with tc:
                tb_html = (
                    '<div class="ptile" style="text-align:center">' +
                    f'<div style="font-size:12px;color:#506070;margin-bottom:4px">{cfg["icon"]} {name}</div>' +
                    f'<div style="margin:5px 0"><span class="{badge_class}">{tb["trend"]}</span></div>' +
                    f'<div style="font-size:20px;font-weight:900;color:{score_color}">{tb["score"]:+d}</div>' +
                    '<div style="font-size:10px;color:#344858">Bias Score</div>' +
                    '</div>'
                )
                st.markdown(tb_html, unsafe_allow_html=True)
                for sig_type, sig_text in tb["signals"][:3]:
                    dot_cls = "trend-dot-bull" if sig_type=="Bull" else ("trend-dot-bear" if sig_type=="Bear" else "trend-dot-neut")
                    st.markdown(f'<div class="trend-row"><span class="{dot_cls}"></span><span style="font-size:11px;color:#889aaa">{sig_text}</span></div>', unsafe_allow_html=True)

    st.divider()

    # ═══════════════════════════════════════════════════════════════════════
    #  TABS: Detailed Parameters
    # ═══════════════════════════════════════════════════════════════════════
    tabs = st.tabs([
        "📊 Options & PCR",
        "📈 Futures & OI",
        "📉 Volatility & ATR",
        "🧭 Intraday Stats",
        "🎯 Strike Suggester",
        "📋 Full Signal Table",
    ])

    # ── TAB 1: OPTIONS & PCR ─────────────────────────────────────────────
    with tabs[0]:
        st.markdown('<div class="section-header">📊 Put-Call Ratio & ATM Options</div>', unsafe_allow_html=True)
        st.caption("""
        **PCR > 1.2** → More puts written → Market expects support → Mildly Bullish  
        **PCR < 0.8** → More calls written → Market expects resistance → Mildly Bearish  
        **ATM CE+PE** = Straddle price = Market's expected move for expiry
        """)

        for name, cfg in INDEX_CONFIG.items():
            opt = options_data.get(name, {})
            s   = spot_data.get(name, {})
            ltp = s.get("ltp", 0)

            if opt.get("error"):
                st.warning(f"{name}: {opt['error']}")
                continue
            if not opt:
                st.info(f"{name}: Options data not available.")
                continue

            pcr        = opt.get("pcr", 0)
            atm        = opt.get("atm", 0)
            ce_price   = opt.get("atm_ce_price", 0)
            pe_price   = opt.get("atm_pe_price", 0)
            straddle   = round(ce_price + pe_price, 2)
            straddle_p = round(straddle / ltp * 100, 2) if ltp else 0
            ce_oi      = opt.get("total_ce_oi", 0)
            pe_oi      = opt.get("total_pe_oi", 0)
            exp_dt     = opt.get("exp_date", "N/A")

            pcr_lab, pcr_badge, pcr_desc = pcr_signal(pcr)

            st.markdown(f"#### {cfg['icon']} {name} — Expiry: `{exp_dt}` | ATM Strike: `{atm:,.0f}`")
            c1, c2, c3, c4, c5 = st.columns(5)
            c1.markdown(f"""<div class="param-block">
                <div class="param-label">PCR (OI)</div>
                <div class="param-value">{pcr:.3f}</div>
                <div class="param-sub"><span class="badge-{pcr_badge}">{pcr_lab}</span></div>
                <div class="param-sub">{pcr_desc}</div>
            </div>""", unsafe_allow_html=True)
            c2.markdown(f"""<div class="param-block">
                <div class="param-label">ATM CE Price</div>
                <div class="param-value" style="color:#ff7043">₹{ce_price:.2f}</div>
                <div class="param-sub">Calls (3-strike OI: {ce_oi:,})</div>
            </div>""", unsafe_allow_html=True)
            c3.markdown(f"""<div class="param-block">
                <div class="param-label">ATM PE Price</div>
                <div class="param-value" style="color:#69f0ae">₹{pe_price:.2f}</div>
                <div class="param-sub">Puts (3-strike OI: {pe_oi:,})</div>
            </div>""", unsafe_allow_html=True)
            c4.markdown(f"""<div class="param-block">
                <div class="param-label">Straddle Price</div>
                <div class="param-value" style="color:#ffcc02">₹{straddle:.2f}</div>
                <div class="param-sub">{straddle_p:.2f}% of spot</div>
            </div>""", unsafe_allow_html=True)
            oi_skew_val = f"{pe_oi/ce_oi:.2f}x" if ce_oi else "N/A"
            c5.markdown(f"""<div class="param-block">
                <div class="param-label">OI Skew (PE/CE)</div>
                <div class="param-value">{oi_skew_val}</div>
                <div class="param-sub">PE OI vs CE OI ratio</div>
            </div>""", unsafe_allow_html=True)

            # Simple OI bar
            if ce_oi and pe_oi:
                total_oi = ce_oi + pe_oi
                ce_pct = ce_oi / total_oi * 100
                pe_pct = pe_oi / total_oi * 100
                st.markdown(f"""
                <div style="margin:4px 0 12px 0">
                    <div style="font-size:11px;color:#556677;margin-bottom:3px">OI Distribution (CE vs PE)</div>
                    <div style="display:flex;height:12px;border-radius:6px;overflow:hidden">
                        <div style="width:{ce_pct:.1f}%;background:#ff7043;"></div>
                        <div style="width:{pe_pct:.1f}%;background:#69f0ae;"></div>
                    </div>
                    <div style="display:flex;justify-content:space-between;font-size:10px;color:#556677;margin-top:2px">
                        <span>CE {ce_pct:.1f}% ({ce_oi:,})</span>
                        <span>PE {pe_pct:.1f}% ({pe_oi:,})</span>
                    </div>
                </div>
                """, unsafe_allow_html=True)
            st.divider()

    # ── TAB 2: FUTURES & OI ──────────────────────────────────────────────
    with tabs[1]:
        st.markdown('<div class="section-header">📈 Futures Data — Basis, OI, Premium</div>', unsafe_allow_html=True)
        st.caption("""
        **Basis (Futures Premium)** = Futures LTP − Spot. Positive = contango (bullish carry). Negative = backwardation (bearish).  
        **OI Rise + Price Rise** = Long buildup (Bullish). **OI Rise + Price Fall** = Short buildup (Bearish).  
        **OI Fall + Price Rise** = Short covering (Bullish). **OI Fall + Price Fall** = Long unwinding (Bearish).
        """)

        fut_rows = []
        for name, cfg in INDEX_CONFIG.items():
            s = spot_data.get(name, {})
            f = futures_data.get(name, {})
            ltp      = s.get("ltp", 0)
            fut_ltp  = f.get("fut_ltp", 0)
            basis    = round(fut_ltp - ltp, 2) if fut_ltp and ltp else 0
            basis_p  = round(basis / ltp * 100, 3) if ltp else 0
            oi       = f.get("fut_oi", 0)
            oi_chg   = f.get("fut_oi_chg", 0)
            fut_vol  = f.get("fut_vol", 0)

            # OI interpretation
            if oi_chg > 0 and s.get("chg_pct", 0) > 0:
                oi_signal = "🟢 Long Buildup"
            elif oi_chg > 0 and s.get("chg_pct", 0) < 0:
                oi_signal = "🔴 Short Buildup"
            elif oi_chg < 0 and s.get("chg_pct", 0) > 0:
                oi_signal = "🟡 Short Covering"
            elif oi_chg < 0 and s.get("chg_pct", 0) < 0:
                oi_signal = "🟠 Long Unwinding"
            else:
                oi_signal = "⚪ Neutral"

            basis_badge = "bull" if basis > 0 else ("bear" if basis < 0 else "neut")
            fut_rows.append({
                "Index":       f"{cfg['icon']} {name}",
                "Spot":        f"{ltp:,.2f}",
                "Futures":     f"{fut_ltp:,.2f}" if fut_ltp else "N/A",
                "Basis (pts)": f"{basis:+.2f}" if fut_ltp else "N/A",
                "Basis %":     f"{basis_p:+.3f}%" if fut_ltp else "N/A",
                "Open Interest": f"{oi:,}" if oi else "N/A",
                "OI Chg (est.)": f"{oi_chg:+,}" if oi_chg else "N/A",
                "Volume":      f"{fut_vol:,}" if fut_vol else "N/A",
                "OI Signal":   oi_signal,
            })

        if fut_rows:
            df_fut = pd.DataFrame(fut_rows)
            st.dataframe(df_fut, use_container_width=True, hide_index=True)
        else:
            st.info("Futures data not available. Enable 'Futures Data' in sidebar and refetch.")

        st.markdown("#### 📖 How to read Basis for MFT trading:")
        st.markdown("""
        | Basis | Market Interpretation | MFT Implication |
        |-------|----------------------|-----------------|
        | +0.1% to +0.3% | Normal carry | Neutral — no edge |
        | > +0.5% | Strong contango | Bullish sentiment, longs paying premium |
        | −0.1% to −0.3% | Mild backwardation | Caution — shorts active |
        | < −0.5% | Deep backwardation | Bearish — panic or dividend expectation |
        """)

    # ── TAB 3: VOLATILITY & ATR ──────────────────────────────────────────
    with tabs[2]:
        st.markdown('<div class="section-header">📉 Volatility — ATR & VIX Context</div>', unsafe_allow_html=True)
        st.caption("""
        **ATR (Average True Range)** = Average daily price swing. Used to set stop-loss and profit targets.  
        **ATR Expansion %** = Today's range / 5-day ATR. >100% = Trending day. <60% = Consolidation day.  
        Use ATR to size positions: smaller position when ATR is high (more risk per point).
        """)

        atr_rows = []
        for name, cfg in INDEX_CONFIG.items():
            s   = spot_data.get(name, {})
            a   = atr_data.get(name, {})
            ltp = s.get("ltp", 0)
            atr5  = a.get("atr5", 0)
            atr14 = a.get("atr14", 0)
            exp   = a.get("atr_expansion", 0)
            today_range = a.get("today_range", s.get("day_range", 0))

            atr_pct5  = round(atr5  / ltp * 100, 2) if ltp else 0
            atr_pct14 = round(atr14 / ltp * 100, 2) if ltp else 0

            # Typical stop loss levels
            sl_1x = round(ltp - atr5 * 0.5, 2) if ltp else 0
            sl_2x = round(ltp - atr5, 2)        if ltp else 0
            tgt_1x= round(ltp + atr5 * 0.5, 2) if ltp else 0
            tgt_2x= round(ltp + atr5, 2)        if ltp else 0

            exp_label = atr_expansion_signal(exp)
            day_type  = "Trending" if exp > 100 else ("Consolidating" if exp < 70 else "Normal")

            atr_rows.append({
                "Index":         f"{cfg['icon']} {name}",
                "LTP":           f"{ltp:,.2f}",
                "5D ATR (pts)":  f"{atr5:,.1f}" if atr5 else "N/A",
                "5D ATR %":      f"{atr_pct5:.2f}%" if atr_pct5 else "N/A",
                "14D ATR (pts)": f"{atr14:,.1f}" if atr14 else "N/A",
                "Today Range":   f"{today_range:,.1f}",
                "ATR Expansion": f"{exp:.1f}%" if exp else "N/A",
                "Day Type":      day_type,
                "Signal":        exp_label,
                "SL (0.5x ATR)": f"{sl_1x:,.2f}" if sl_1x else "N/A",
                "Target (1x ATR)":f"{tgt_2x:,.2f}" if tgt_2x else "N/A",
            })

        if atr_rows:
            st.dataframe(pd.DataFrame(atr_rows), use_container_width=True, hide_index=True)

        st.markdown("#### 📐 Position Sizing Guide (ATR-based)")
        st.markdown("""
        | Risk % | Formula | Example (NIFTY, ATR=100, Account ₹10L) |
        |--------|---------|----------------------------------------|
        | 1% risk | Qty = (Account × 1%) / ATR | = 10,000 / 100 = 100 lots-equivalent |
        | Use ATR × 1.5 as SL | SL = Entry − (1.5 × ATR) | Wider SL, smaller qty |
        | Use ATR × 0.5 as SL | SL = Entry − (0.5 × ATR) | Tighter SL, larger qty |
        
        **Rule for MFT:** On high ATR-expansion days, reduce position size. On consolidation days, 
        wait for breakout with tight SL = ATR × 0.3.
        """)

    # ── TAB 4: INTRADAY STATS ────────────────────────────────────────────
    with tabs[3]:
        st.markdown('<div class="section-header">🧭 Intraday Parameters for MFT Traders</div>', unsafe_allow_html=True)
        st.caption("""
        Key intraday levels and context for taking directional views.  
        **VWAP** (proxy): Using Open as reference. **HOD/LOD** proximity helps identify momentum.
        """)

        for name, cfg in INDEX_CONFIG.items():
            s   = spot_data.get(name, {})
            ltp = s.get("ltp", 0)
            if not ltp: continue

            high  = s.get("high", 0)
            low   = s.get("low", 0)
            open_ = s.get("open", 0)
            prev  = s.get("prev_close", 0)
            rp    = s.get("range_pos", 50)
            chg   = s.get("chg_pct", 0)
            gap_p = s.get("gap_pct", 0)

            # Derived levels
            mid_range  = round((high + low) / 2, 2) if high and low else 0
            pivot      = round((high + low + prev) / 3, 2) if all([high,low,prev]) else 0
            r1         = round(2*pivot - low, 2) if pivot and low else 0
            s1         = round(2*pivot - high, 2) if pivot and high else 0
            r2         = round(pivot + (high - low), 2) if pivot else 0
            s2         = round(pivot - (high - low), 2) if pivot else 0

            dist_hod = round((high - ltp) / high * 100, 2) if high else 0
            dist_lod = round((ltp - low) / ltp * 100, 2)  if ltp  else 0

            # Momentum: price vs open
            vs_open     = round(ltp - open_, 2)
            vs_open_pct = round(vs_open / open_ * 100, 2) if open_ else 0
            open_bias   = "Above Open 📈" if ltp > open_ else ("Below Open 📉" if ltp < open_ else "At Open ➡️")

            st.markdown(f"#### {cfg['icon']} {name}")
            r1c, r2c, r3c, r4c = st.columns(4)

            r1c.markdown(f"""<div class="param-block">
                <div class="param-label">Current LTP</div>
                <div class="param-value" style="color:{cfg['color']}">{ltp:,.2f}</div>
                <div class="param-sub">{open_bias}</div>
                <div class="param-sub">vs Open: {vs_open:+.2f} ({vs_open_pct:+.2f}%)</div>
            </div>""", unsafe_allow_html=True)

            r2c.markdown(f"""<div class="param-block">
                <div class="param-label">Day Range Position</div>
                <div class="param-value">{rp:.1f}%</div>
                <div class="param-sub">HOD: {high:,.2f} ({dist_hod:.2f}% away)</div>
                <div class="param-sub">LOD: {low:,.2f} ({dist_lod:.2f}% away)</div>
            </div>""", unsafe_allow_html=True)

            r3c.markdown(f"""<div class="param-block">
                <div class="param-label">Pivot Levels (Classic)</div>
                <div class="param-value">{pivot:,.2f}</div>
                <div class="param-sub">R1: {r1:,.2f} | R2: {r2:,.2f}</div>
                <div class="param-sub">S1: {s1:,.2f} | S2: {s2:,.2f}</div>
            </div>""", unsafe_allow_html=True)

            r4c.markdown(f"""<div class="param-block">
                <div class="param-label">Gap & Change</div>
                <div class="param-value">{"+" if gap_p>=0 else ""}{gap_p:.2f}%</div>
                <div class="param-sub">Gap (Open vs Prev Close)</div>
                <div class="param-sub">Intraday Change: {chg:+.2f}%</div>
            </div>""", unsafe_allow_html=True)

            # Range position bar
            rp_c = max(0, min(100, rp))
            bar_c = "#00e676" if chg >= 0 else "#ff5252"
            st.markdown(f"""
            <div style="margin: 4px 0 14px 0">
                <div style="display:flex;justify-content:space-between;font-size:10px;color:#445566;margin-bottom:3px">
                    <span>LOD {low:,.2f}</span>
                    <span>Range Position: {rp:.1f}%</span>
                    <span>HOD {high:,.2f}</span>
                </div>
                <div class="range-bar-outer" style="height:12px">
                    <div class="range-bar-inner" style="width:{rp_c}%;background:{bar_c}"></div>
                </div>
            </div>
            """, unsafe_allow_html=True)

        st.markdown("#### 📘 How to Use These Levels for MFT Trading")
        st.markdown("""
        | Level | Usage |
        |-------|-------|
        | **Range Position > 80%** | Strong momentum — look for continuation / buy dips |
        | **Range Position < 20%** | Weakness — look for reversals only with confirmation |
        | **LTP > Open + Range Pos high** | Intraday long bias — buy support, avoid shorts |
        | **Near HOD with strong OI buildup** | Potential breakout — scalp long with tight SL |
        | **Near LOD with high put OI** | Possible support — look for mean reversion long |
        | **Pivot R1/R2** | Intraday resistance targets for MFT momentum trades |
        | **Gap-up + PCR > 1.2** | Strong bullish day setup — favor long positions |
        | **Gap-down + PCR < 0.8** | Bearish day setup — favor short positions |
        """)

    # ── TAB 5: STRIKE SUGGESTER ───────────────────────────────────────────
    with tabs[4]:
        import streamlit.components.v1 as components

        st.markdown("## 🎯 Smart Strike Suggester")
        st.caption("All parameters combined → specific strike with Entry, SL, Target. No need to check each tab manually.")

        # ── Controls ────────────────────────────────────────────────────────
        ctrl1, ctrl2, ctrl3 = st.columns([2, 1, 1])
        with ctrl1:
            sel_index = st.selectbox("📌 Select Index", options=list(INDEX_CONFIG.keys()),
                                     index=0, key="ss_index")
        with ctrl2:
            risk_profile = st.selectbox("⚖️ Risk Profile",
                                        options=["conservative", "moderate", "aggressive"],
                                        index=1, key="ss_risk")
        with ctrl3:
            st.write("")
            fetch_chain_btn = st.button("🔄 Generate", use_container_width=True, key="btn_chain")

        # ── Fetch chain ──────────────────────────────────────────────────────
        chain_key = f"chain_{sel_index}"
        if fetch_chain_btn or chain_key not in st.session_state:
            df_instruments = st.session_state.get("instruments_df", pd.DataFrame())
            s_sel_pre = spot_data.get(sel_index, {})
            ltp_pre   = s_sel_pre.get("ltp", 0)
            if ltp_pre and not df_instruments.empty:
                with st.spinner(f"Fetching {sel_index} option chain..."):
                    st.session_state[chain_key] = fetch_strike_chain(
                        kite, df_instruments, sel_index, ltp_pre)
            else:
                st.warning("Fetch live data first (sidebar button).")

        chain_df = st.session_state.get(chain_key, pd.DataFrame())
        s_sel    = spot_data.get(sel_index, {})
        f_sel    = futures_data.get(sel_index, {})
        o_sel    = options_data.get(sel_index, {})
        a_sel    = atr_data.get(sel_index, {})
        tb_sel   = compute_trend_bias(s_sel, f_sel)
        cfg_sel  = INDEX_CONFIG[sel_index]
        ltp_sel  = s_sel.get("ltp", 0)

        # ── Context strip (native metrics) ──────────────────────────────────
        if ltp_sel:
            st.divider()
            pcr_v   = o_sel.get("pcr", 0)
            atr5_v  = a_sel.get("atr5", 0)
            atr_exp = a_sel.get("atr_expansion", 0)
            rp_v    = s_sel.get("range_pos", 50)
            chg_v   = s_sel.get("chg_pct", 0)
            sc_col  = "#00e676" if tb_sel["score"] > 0 else ("#ff5252" if tb_sel["score"] < 0 else "#7a8a9a")
            vix_col = "#ff5252" if vix_val > 22 else ("#ffcc02" if vix_val > 16 else "#00e676")
            rp_col  = "#00e676" if rp_v > 60 else ("#ff5252" if rp_v < 40 else "#ffcc02")
            chg_col2= "#00e676" if chg_v >= 0 else "#ff5252"

            ctx_html = (
                f'<div style="background:#0a1018;border:1px solid #162030;border-radius:12px;' +
                'padding:14px 18px;margin-bottom:10px">' +
                f'<div style="font-size:13px;font-weight:700;color:#4dd8a0;margin-bottom:10px">{cfg_sel["icon"]} {sel_index} — Live Context</div>' +
                '<div style="display:grid;grid-template-columns:repeat(6,1fr);gap:10px">' +
                # LTP
                '<div style="text-align:center">' +
                '<div class="ptile-label">LTP</div>' +
                f'<div style="font-size:22px;font-weight:900;color:{cfg_sel["color"]}">₹{ltp_sel:,.2f}</div>' +
                f'<div style="font-size:11px;color:{chg_col2}">{chg_v:+.2f}%</div></div>' +
                # Trend
                '<div style="text-align:center">' +
                '<div class="ptile-label">Trend Bias</div>' +
                f'<div style="font-size:16px;font-weight:800;color:{sc_col}">{tb_sel["trend"]}</div>' +
                f'<div style="font-size:11px;color:#3a5060">Score {tb_sel["score"]:+d}</div></div>' +
                # PCR
                '<div style="text-align:center">' +
                '<div class="ptile-label">PCR</div>' +
                f'<div style="font-size:18px;font-weight:800;color:#dce8f4">{(f"{pcr_v:.3f}") if pcr_v else "—"}</div>' +
                f'<div style="font-size:11px;color:#3a5060">{pcr_signal(pcr_v)[0] if pcr_v else "No data"}</div></div>' +
                # VIX
                '<div style="text-align:center">' +
                '<div class="ptile-label">India VIX</div>' +
                f'<div style="font-size:18px;font-weight:800;color:{vix_col}">{vix_val:.2f}</div>' +
                f'<div style="font-size:11px;color:#3a5060">{vix_signal(vix_val)[0][:14]}</div></div>' +
                # ATR
                '<div style="text-align:center">' +
                '<div class="ptile-label">5D ATR</div>' +
                f'<div style="font-size:18px;font-weight:800;color:#dce8f4">{f"{atr5_v:,.1f}" if atr5_v else "—"}</div>' +
                f'<div style="font-size:11px;color:#3a5060">Exp {atr_exp:.0f}%</div></div>' +
                # Range pos
                '<div style="text-align:center">' +
                '<div class="ptile-label">Range Pos</div>' +
                f'<div style="font-size:18px;font-weight:800;color:{rp_col}">{rp_v:.0f}%</div>' +
                f'<div style="font-size:11px;color:#3a5060">{"Bullish" if rp_v>60 else ("Bearish" if rp_v<40 else "Neutral")}</div></div>' +
                '</div></div>'
            )
            st.markdown(ctx_html, unsafe_allow_html=True)

        # ── Trade suggestions ────────────────────────────────────────────────
        if ltp_sel and not chain_df.empty:
            trades = suggest_trades(sel_index, spot_data, futures_data, options_data,
                                    atr_data, chain_df, vix_val, risk_profile)

            if not trades:
                st.info("No clear trade signal. Market may be in transition — wait for confirmation.")
            else:
                _sl_pct_map = {"conservative": 25, "moderate": 35, "aggressive": 49}
                for i, t in enumerate(trades):
                    # ── Card header ─────────────────────────────────────────
                    dir_emoji  = "🟢 BUY" if t["direction"] == "BUY" else "🔴 SELL"
                    conf_emoji = {"HIGH": "🔥 HIGH", "MEDIUM": "⚡ MEDIUM", "LOW": "💡 LOW"}.get(t["confidence"], t["confidence"])
                    opt_label  = "CALL (CE)" if t["option_type"] == "CE" else "PUT (PE)"
                    opt_emoji  = "📈" if t["option_type"] == "CE" else "📉"

                    border_col = t["conf_color"]

                    # ── Trade header ─────────────────────────────────────
                    dir_col  = "#00e676" if t["direction"] == "BUY" else "#ff5252"
                    opt_col  = "#40c4ff" if t["option_type"] == "CE" else "#ce93d8"
                    hdr = (
                        f'<div style="border-left:5px solid {border_col};background:#0d1520;' +
                        'border-radius:0 12px 12px 0;padding:14px 20px;margin:14px 0 2px 0">' +
                        f'<span style="font-size:22px;font-weight:900;color:{dir_col}">{dir_emoji}</span>' +
                        f'&nbsp;&nbsp;<span style="font-size:20px;font-weight:900;color:{opt_col}">{opt_emoji} {t["display_sym"]}</span>' +
                        f'&nbsp;&nbsp;<span style="background:{border_col}22;color:{border_col};border:1px solid {border_col};' +
                        f'border-radius:5px;padding:2px 10px;font-size:12px;font-weight:700">{conf_emoji} CONFIDENCE</span>' +
                        f'&nbsp;&nbsp;<span style="color:#4a6070;font-size:12px">{t["moneyness"]} &nbsp;&middot;&nbsp; ' +
                        f'Expiry <b style="color:#7090a0">{t["expiry"]}</b> &nbsp;&middot;&nbsp; ' +
                        f'Lot <b style="color:#7090a0">{t["lot_size"]} units</b></span></div>'
                    )
                    st.markdown(hdr, unsafe_allow_html=True)

                    # ── Price tiles row (pure HTML, no st.metric delta arrows) ──
                    premium_per_lot = int(t["entry"] * t["lot_size"])
                    risk_per_lot    = int((t["entry"] - t["sl"]) * t["lot_size"])
                    reward_per_lot  = int((t["target1"] - t["entry"]) * t["lot_size"])
                    rr_ok           = "✅" if t["rr_ratio"] >= 1.5 else "⚠️"

                    tiles_html = (
                        '<div style="display:grid;grid-template-columns:repeat(6,1fr);gap:8px;margin:4px 0 8px">' +
                        # Entry
                        '<div class="ptile" style="text-align:center">' +
                        '<div class="ptile-label">📥 Entry</div>' +
                        f'<div style="font-size:20px;font-weight:900;color:#dce8f4">₹{t["entry"]:.2f}</div>' +
                        '<div class="ptile-sub">Option premium</div></div>' +
                        # SL
                        '<div class="ptile" style="text-align:center;border-top:3px solid #a03030">' +
                        '<div class="ptile-label">🛑 Stop Loss</div>' +
                        f'<div style="font-size:20px;font-weight:900;color:#ff5252">₹{t["sl"]:.2f}</div>' +
                        f'<div class="ptile-sub">−{t["sl_pct"]:.0f}% from entry</div></div>' +
                        # Target 1
                        '<div class="ptile" style="text-align:center;border-top:3px solid #00a050">' +
                        '<div class="ptile-label">🎯 Target 1</div>' +
                        f'<div style="font-size:20px;font-weight:900;color:#00e676">₹{t["target1"]:.2f}</div>' +
                        '<div class="ptile-sub">Book 50% here</div></div>' +
                        # Target 2
                        '<div class="ptile" style="text-align:center;border-top:3px solid #008040">' +
                        '<div class="ptile-label">🚀 Target 2</div>' +
                        f'<div style="font-size:20px;font-weight:900;color:#69f0ae">₹{t["target2"]:.2f}</div>' +
                        '<div class="ptile-sub">Trail SL after T1</div></div>' +
                        # R:R
                        '<div class="ptile" style="text-align:center;border-top:3px solid #806000">' +
                        '<div class="ptile-label">⚖️ Risk : Reward</div>' +
                        f'<div style="font-size:20px;font-weight:900;color:#ffcc02">1 : {t["rr_ratio"]:.1f}</div>' +
                        f'<div class="ptile-sub">{rr_ok} {"Good" if t["rr_ratio"]>=1.5 else "Borderline"}</div></div>' +
                        # OI
                        '<div class="ptile" style="text-align:center">' +
                        '<div class="ptile-label">📊 Open Interest</div>' +
                        f'<div style="font-size:16px;font-weight:800;color:#aabbcc">{t["oi"]:,}</div>' +
                        '<div class="ptile-sub">Lots — check liquidity</div></div>' +
                        '</div>'
                    )
                    st.markdown(tiles_html, unsafe_allow_html=True)

                    # ── P&L per lot row ──────────────────────────────────────
                    pnl_html = (
                        '<div style="display:grid;grid-template-columns:repeat(4,1fr);gap:8px;margin-bottom:6px">' +
                        '<div class="ptile">' +
                        '<div class="ptile-label">💰 Capital / Lot</div>' +
                        f'<div style="font-size:17px;font-weight:800;color:#c8d4e0">₹{premium_per_lot:,}</div>' +
                        '<div class="ptile-sub">Premium × lot size</div></div>' +
                        '<div class="ptile" style="border-top:3px solid #a03030">' +
                        '<div class="ptile-label">🔴 Max Risk / Lot</div>' +
                        f'<div style="font-size:17px;font-weight:800;color:#ff7070">₹{risk_per_lot:,}</div>' +
                        '<div class="ptile-sub">If SL triggered</div></div>' +
                        '<div class="ptile" style="border-top:3px solid #007040">' +
                        '<div class="ptile-label">🟢 Reward / Lot (T1)</div>' +
                        f'<div style="font-size:17px;font-weight:800;color:#69f0ae">₹{reward_per_lot:,}</div>' +
                        '<div class="ptile-sub">At Target 1</div></div>' +
                        '<div class="ptile">' +
                        '<div class="ptile-label">📐 Bias Score</div>' +
                        f'<div style="font-size:17px;font-weight:800;color:{"#00e676" if t["bias_score"]>0 else "#ff5252"}">{ t["bias_score"]:+d}</div>' +
                        '<div class="ptile-sub">−100 (Bear) to +100 (Bull)</div></div>' +
                        '</div>'
                    )
                    st.markdown(pnl_html, unsafe_allow_html=True)

                    # ── Reason ───────────────────────────────────────────────
                    st.info(f"📊 **Why this trade:** {t['reason']}")
                    st.divider()

                # ── Option Chain table ───────────────────────────────────────
                st.markdown("### 📋 Option Chain  (±8 strikes from ATM)")
                atm_val = int(chain_df["atm"].iloc[0]) if not chain_df.empty else 0
                display_chain = chain_df[["strike","ce_price","ce_oi","pe_price","pe_oi"]].copy()
                display_chain.columns = ["Strike","CE Price ₹","CE OI","PE Price ₹","PE OI"]
                display_chain["CE Price ₹"] = display_chain["CE Price ₹"].apply(lambda x: f"{x:.2f}" if x else "—")
                display_chain["PE Price ₹"] = display_chain["PE Price ₹"].apply(lambda x: f"{x:.2f}" if x else "—")
                display_chain["CE OI"]      = display_chain["CE OI"].apply(lambda x: f"{int(x):,}" if x else "—")
                display_chain["PE OI"]      = display_chain["PE OI"].apply(lambda x: f"{int(x):,}" if x else "—")
                display_chain.insert(0, "", display_chain["Strike"].apply(lambda x: "◄ ATM" if int(x)==atm_val else ""))

                def _style_chain(row):
                    if str(row["Strike"]) == str(atm_val):
                        return ["background-color:#0d2b0d;font-weight:bold;color:#00e676"]*len(row)
                    return [""]*len(row)

                st.dataframe(
                    display_chain.style.apply(_style_chain, axis=1),
                    use_container_width=True, hide_index=True, height=360
                )

                # ── Risk disclaimer ──────────────────────────────────────────
                st.warning(
                    f"⚠️ **Risk Notes —** Algorithmic signals only, not financial advice.  "
                    f"VIX={vix_val:.1f} → {'Reduce size 40%' if vix_val>22 else 'Normal sizing'}.  "
                    f"Risk profile: **{risk_profile.upper()}** → SL ≈ {_sl_pct_map.get(risk_profile,35)}% of premium.  "
                    f"Check OI > 500 lots for liquidity. If SL hit → wait 15 min before re-entry."
                )
        else:
            st.info(f"Click **🔄 Generate** above to load the {sel_index} option chain and get strike recommendations.")

    # ── TAB 6: FULL SIGNAL TABLE ─────────────────────────────────────────
    with tabs[5]:
        st.markdown('<div class="section-header">📋 Complete Signal Summary — All Indices</div>', unsafe_allow_html=True)

        summary_rows = []
        for name, cfg in INDEX_CONFIG.items():
            s   = spot_data.get(name, {})
            f   = futures_data.get(name, {})
            o   = options_data.get(name, {})
            a   = atr_data.get(name, {})
            tb  = compute_trend_bias(s, f)
            ltp = s.get("ltp", 0)
            pcr = o.get("pcr", 0)
            atm = o.get("atm", 0)
            straddle = round((o.get("atm_ce_price",0) + o.get("atm_pe_price",0)), 2)

            pcr_lab, _, _ = pcr_signal(pcr)
            atr5  = a.get("atr5", 0)
            exp   = a.get("atr_expansion", 0)

            basis = round(f.get("fut_ltp", 0) - ltp, 2) if f.get("fut_ltp") and ltp else 0

            summary_rows.append({
                "Index":        f"{cfg['icon']} {name}",
                "LTP":          f"{ltp:,.2f}",
                "Change %":     f"{s.get('chg_pct',0):+.2f}%",
                "Gap %":        f"{s.get('gap_pct',0):+.2f}%",
                "Trend Bias":   tb["trend"],
                "Bias Score":   tb["score"],
                "PCR":          f"{pcr:.3f}" if pcr else "N/A",
                "PCR Signal":   pcr_lab,
                "ATM Strike":   f"{atm:,.0f}" if atm else "N/A",
                "Straddle":     f"₹{straddle:.2f}" if straddle else "N/A",
                "Fut Basis":    f"{basis:+.2f}" if basis else "N/A",
                "5D ATR":       f"{atr5:,.1f}" if atr5 else "N/A",
                "ATR Exp%":     f"{exp:.1f}%" if exp else "N/A",
                "Range Pos":    f"{s.get('range_pos',0):.1f}%",
                "VIX":          f"{vix_val:.2f}" if vix_val else "N/A",
            })

        df_summary = pd.DataFrame(summary_rows)
        st.dataframe(df_summary, use_container_width=True, hide_index=True)

        # Download
        csv = df_summary.to_csv(index=False)
        st.download_button(
            "⬇️ Download Summary CSV",
            csv,
            f"mft_index_snapshot_{_now().strftime('%Y%m%d_%H%M')}.csv",
            "text/csv"
        )

        st.markdown("#### 🧠 MFT Trading Decision Framework")
        st.markdown("""
        **Step 1 — Check VIX Regime**  
        VIX < 15 → Low volatility, safer for trend following. VIX > 25 → High vol, reduce size, widen SL.

        **Step 2 — Check Index Trend Bias Score**  
        Score > +30 → Bullish day — buy dips near S1 or LOD with ATR-based SL.  
        Score < −30 → Bearish day — sell rallies near R1 or HOD.  
        Score −30 to +30 → Range day — trade between R1 and S1 only.

        **Step 3 — Confirm with PCR**  
        PCR > 1.2 + Bullish trend = High conviction long setup.  
        PCR < 0.8 + Bearish trend = High conviction short setup.

        **Step 4 — Check Futures Basis**  
        Rising basis + rising price = Real buying (contango). 
        Falling basis + falling price = Real selling. Divergence = fade signal.

        **Step 5 — Set SL & Target using ATR**  
        SL = 0.5 × ATR. Target = 1.0–1.5 × ATR. Expand on trending days (ATR exp > 120%).
        """)

    # ── AUTO REFRESH ──────────────────────────────────────────────────────
    if auto_refresh:
        time.sleep(refresh_sec)
        st.rerun()

else:
    st.info("👈 Click **🚀 Fetch Live Data** in the sidebar to load index data from Zerodha.")
    st.markdown("""
    ### What this MFT Index Dashboard shows:
    
    | Module | Parameters | Purpose |
    |--------|-----------|---------|
    | **📌 Index Snapshot** | LTP, Change%, Gap%, Range Position | At-a-glance market view |
    | **📊 Options & PCR** | Put-Call Ratio, ATM CE/PE, Straddle | Sentiment & expected move |
    | **📈 Futures & OI** | Basis, OI, OI Signal (Long/Short buildup) | Smart money direction |
    | **📉 Volatility & ATR** | 5D/14D ATR, ATR Expansion %, VIX | Risk & position sizing |
    | **🧭 Intraday Stats** | Pivot levels, Range Position, HOD/LOD | Entry/exit levels |
    | **🎯 Trend Bias** | Multi-factor score (−100 to +100) | Directional conviction |
    
    ### Indices covered:
    - 🏦 **NIFTY 50** — Benchmark Index (Lot: 25)
    - 🏧 **BANKNIFTY** — Banking Sector (Lot: 15)
    - 💹 **FINNIFTY** — Financial Services (Lot: 25)
    - 📊 **MIDCPNIFTY** — Midcap Select (Lot: 75)
    - 🔶 **SENSEX** — BSE Benchmark (Lot: 10)
    
    ### Getting Started (for new MFT firms):
    1. Ensure Zerodha API is active with F&O permissions
    2. Click **🚀 Fetch Live Data** during market hours (9:15 AM – 3:30 PM IST)
    3. Start with the **Trend Bias** and **PCR** tab for directional view
    4. Use **ATR** for stop-loss sizing before placing orders
    5. Enable **Auto Refresh** every 60 seconds for live monitoring
    """)
