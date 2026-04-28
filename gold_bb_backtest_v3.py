"""
╔══════════════════════════════════════════════════════════════════════════════╗
║  GOLD MCX — Bollinger %B Option Strategy Backtester  v3                    ║
║  Data Source : Zerodha Kite API (fetches 30-min, resamples to 45-min)      ║
║  Strategy    : Pine v2 — %B + Bull Market Band + Flip Logic                ║
╚══════════════════════════════════════════════════════════════════════════════╝
Run:
    pip install kiteconnect pyotp pandas numpy tabulate requests --break-system-packages
    python gold_bb_backtest.py
"""

import os, sys, time, math
from datetime import datetime, timedelta, timezone
import subprocess

# ── auto-install ───────────────────────────────────────────────────────────────
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
#  STRATEGY PARAMETERS  (v2 Pine Script)
# ══════════════════════════════════════════════════════════════════════════════
BB_LENGTH     = 20
BB_MULT       = 2.0
COOLDOWN_BARS = 5

# Entry thresholds
CALL_LOWER    = -0.20
CALL_UPPER    =  0.05
PUT_LOWER     =  1.05
PUT_UPPER     =  1.30

# v2 special exit triggers (all in %B space)
CALL_EXIT_TRIG_PREV  = 0.9    # pct_b[1] >= 0.9  AND  open_pctb < 0.9
CALL_EXIT_EXTRA_PREV = 0.5    # pct_b[1] >= 0.5  AND  open_pctb < 0.5
CALL_EXIT_FORCE      = 1.0    # pct_b > 1.0  (when holdCall active)
PUT_EXIT_TRIG_PREV   = 0.1    # pct_b[1] <= 0.1  AND  open_pctb > 0.1
PUT_EXIT_FORCE       = -0.2   # pct_b < -0.2  (when holdPut active)

INITIAL_CAPITAL = 100_000     # Rs 1 lakh
TRADE_FRACTION  = 1.0
BROKERAGE_PCT   = 0.0003
SLIPPAGE_PCT    = 0.001

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
#  FETCH GOLD MCX 30-MIN DATA
# ══════════════════════════════════════════════════════════════════════════════
def get_gold_instrument_token(kite: KiteConnect):
    instruments = kite.instruments("MCX")
    df = pd.DataFrame(instruments)
    gold = df[
        df["tradingsymbol"].str.startswith("GOLD") &
        (df["instrument_type"] == "FUT") &
        ~df["tradingsymbol"].str.startswith("GOLDM")
    ].copy()
    gold["expiry"] = pd.to_datetime(gold["expiry"])
    future_gold = gold[gold["expiry"] >= pd.Timestamp.today()].sort_values("expiry")
    if future_gold.empty:
        raise RuntimeError("No active GOLD futures found on MCX")
    row = future_gold.iloc[0]
    print(f"Instrument: {row['tradingsymbol']}  |  Token: {row['instrument_token']}")
    return int(row["instrument_token"]), row["tradingsymbol"]


def fetch_ohlc(kite: KiteConnect, token: int, days: int = 365) -> pd.DataFrame:
    end   = datetime.now(IST).replace(hour=23, minute=59, second=0, microsecond=0)
    start = end - timedelta(days=days)
    all_candles = []
    chunk_start = start
    while chunk_start < end:
        chunk_end = min(chunk_start + timedelta(days=58), end)
        print(f"  Fetching {chunk_start.date()} -> {chunk_end.date()} ...", end=" ")
        try:
            candles = kite.historical_data(
                token,
                chunk_start.strftime("%Y-%m-%d %H:%M:%S"),
                chunk_end.strftime("%Y-%m-%d %H:%M:%S"),
                "30minute",        # Kite does not support 45min; fetch 30min and resample
            )
            all_candles.extend(candles)
            print(f"{len(candles)} bars")
        except Exception as e:
            print(f"WARNING: {e}")
        chunk_start = chunk_end + timedelta(minutes=30)
        time.sleep(0.35)

    if not all_candles:
        raise RuntimeError("No data returned — check instrument token or date range.")

    df = pd.DataFrame(all_candles)
    df["date"] = pd.to_datetime(df["date"]).dt.tz_localize(None)
    df = df.set_index("date").sort_index().drop_duplicates()

    # ── Resample 30-min → 45-min candles ─────────────────────────────────
    df = (df.resample("45min", origin="start_day")
            .agg({"open": "first", "high": "max",
                  "low": "min",   "close": "last", "volume": "sum"})
            .dropna(subset=["open", "close"]))

    print(f"  Resampled to 45-min: {len(df)} bars")
    return df


# ══════════════════════════════════════════════════════════════════════════════
#  WEEKLY BULL MARKET BAND  (20W SMA + 21W EMA — Pine request.security port)
# ══════════════════════════════════════════════════════════════════════════════
def add_weekly_band(df: pd.DataFrame) -> pd.DataFrame:
    weekly_close = df["close"].resample("W").last().dropna()
    w_sma = weekly_close.rolling(20).mean()
    w_ema = weekly_close.ewm(span=21, adjust=False).mean()
    df = df.copy()
    df["w_sma"] = w_sma.reindex(df.index, method="ffill")
    df["w_ema"] = w_ema.reindex(df.index, method="ffill")
    return df


# ══════════════════════════════════════════════════════════════════════════════
#  INDICATORS
# ══════════════════════════════════════════════════════════════════════════════
def calculate_indicators(df: pd.DataFrame) -> pd.DataFrame:
    c = df["close"]
    o = df["open"]
    h = df["high"]
    lw = df["low"]

    # Bollinger Bands  (population std = Pine ta.stdev)
    basis = c.rolling(BB_LENGTH).mean()
    dev   = c.rolling(BB_LENGTH).std(ddof=0)
    upper = basis + BB_MULT * dev
    lower = basis - BB_MULT * dev
    pct_b = (c - lower) / (upper - lower)

    # Open price in %B space (for exit trigger comparisons)
    open_pctb = (o - lower) / (upper - lower)

    # Candle direction
    bullish = (c > o).astype(int)
    bearish = (c < o).astype(int)

    # ATR volatility filter
    prev_c = c.shift(1)
    tr     = pd.concat([h - lw, (h - prev_c).abs(), (lw - prev_c).abs()], axis=1).max(axis=1)
    atr    = tr.ewm(span=14, adjust=False).mean()
    vol_filter = (atr > atr.rolling(14).mean()).astype(int)

    df = df.copy()
    df["basis"]      = basis
    df["upper"]      = upper
    df["lower"]      = lower
    df["pct_b"]      = pct_b
    df["open_pctb"]  = open_pctb
    df["bullish"]    = bullish
    df["bearish"]    = bearish
    df["vol_filter"] = vol_filter
    return df


# ══════════════════════════════════════════════════════════════════════════════
#  BACKTEST ENGINE  — v2 Pine Logic
#
#  Changes vs v1:
#  - Trend filter (SMA20/50) removed  — v2 Pine removed it
#  - Weekly Bull Market Band added    — informational only (not a hard filter)
#  - CALL exit: callExitTrigger (pctB[1]>=0.9, open<0.9)
#               callExtraExit  (pctB[1]>=0.5, open<0.5)
#               holdCall path: open>=0.9 -> wait -> force when pctB>1.0
#    -> all flip to PUT
#  - PUT exit:  putExitTrigger  (pctB[1]<=0.1, open>0.1)
#               holdPut path: open<=0.1 -> wait -> force when pctB<-0.2
#    -> all flip to CALL
# ══════════════════════════════════════════════════════════════════════════════
def run_backtest(df: pd.DataFrame) -> dict:
    df = calculate_indicators(df)
    df = add_weekly_band(df)
    df = df.dropna(subset=["pct_b", "vol_filter", "w_sma"]).copy()

    equity          = INITIAL_CAPITAL
    call_open       = False
    put_open        = False
    call_entry      = None
    call_entry_time = None
    put_entry       = None
    put_entry_time  = None
    last_trade_bar  = None
    hold_call       = False
    hold_put        = False

    trades = []

    def _close_call(exit_px, exit_ts, reason):
        nonlocal equity, call_open, hold_call
        cost    = call_entry * (1 + SLIPPAGE_PCT + BROKERAGE_PCT)
        revenue = exit_px   * (1 - SLIPPAGE_PCT - BROKERAGE_PCT)
        pnl_pct = (revenue - cost) / cost
        pnl     = equity * TRADE_FRACTION * pnl_pct
        equity += pnl
        trades.append({
            "type": "CALL", "reason": reason,
            "entry_time": call_entry_time, "exit_time": exit_ts,
            "entry_px": round(call_entry, 2), "exit_px": round(exit_px, 2),
            "pnl": round(pnl, 2), "pnl_pct": round(pnl_pct * 100, 3),
            "equity": round(equity, 2), "win": pnl > 0,
        })
        call_open = False
        hold_call = False

    def _close_put(exit_px, exit_ts, reason):
        nonlocal equity, put_open, hold_put
        price_move = (put_entry - exit_px) / put_entry
        pnl_pct    = price_move - SLIPPAGE_PCT * 2 - BROKERAGE_PCT * 2
        pnl        = equity * TRADE_FRACTION * pnl_pct
        equity    += pnl
        trades.append({
            "type": "PUT", "reason": reason,
            "entry_time": put_entry_time, "exit_time": exit_ts,
            "entry_px": round(put_entry, 2), "exit_px": round(exit_px, 2),
            "pnl": round(pnl, 2), "pnl_pct": round(pnl_pct * 100, 3),
            "equity": round(equity, 2), "win": pnl > 0,
        })
        put_open = False
        hold_put = False

    rows      = list(df.iterrows())
    n         = len(rows)
    pct_b_arr = df["pct_b"].values
    opb_arr   = df["open_pctb"].values

    for i, (ts, row) in enumerate(rows):
        if i == 0:
            continue

        pct_b     = pct_b_arr[i]
        pct_b_1   = pct_b_arr[i - 1]   # Pine's percentB[1]
        open_pctb = opb_arr[i]          # current open in %B
        bull      = row["bullish"]
        bear      = row["bearish"]
        vf        = row["vol_filter"]
        close     = row["close"]
        can_trade = (last_trade_bar is None) or (i - last_trade_bar > COOLDOWN_BARS)

        # ── Entry conditions (v2: no trend filter) ────────────────────────
        buy_call = (CALL_LOWER <= pct_b <= CALL_UPPER and
                    bull and not call_open and not put_open and vf and can_trade)
        buy_put  = ((PUT_LOWER <= pct_b or pct_b > PUT_UPPER) and
                    bear and not put_open and not call_open and vf and can_trade)

        # ── CALL exit triggers ─────────────────────────────────────────────
        call_exit_trig  = (pct_b_1 >= CALL_EXIT_TRIG_PREV  and open_pctb < CALL_EXIT_TRIG_PREV)
        call_exit_extra = (pct_b_1 >= CALL_EXIT_EXTRA_PREV and open_pctb < CALL_EXIT_EXTRA_PREV)
        call_force_now  = pct_b > CALL_EXIT_FORCE

        # ── PUT exit triggers ──────────────────────────────────────────────
        put_exit_trig  = (pct_b_1 <= PUT_EXIT_TRIG_PREV and open_pctb > PUT_EXIT_TRIG_PREV)
        put_force_now  = pct_b < PUT_EXIT_FORCE

        # ══════════ CALL MANAGEMENT ══════════════════════════════════════
        if call_open:
            if call_exit_trig or call_exit_extra:
                reason = "ExitTrig->FlipPUT" if call_exit_trig else "ExtraExit->FlipPUT"
                _close_call(close, ts, reason)
                # Flip to PUT
                put_open       = True
                put_entry      = close * (1 + SLIPPAGE_PCT)
                put_entry_time = ts
                last_trade_bar = i
                hold_put       = False

            elif open_pctb >= CALL_EXIT_TRIG_PREV:
                hold_call = True

            elif hold_call and call_force_now:
                _close_call(close, ts, "ForceExit->FlipPUT")
                put_open       = True
                put_entry      = close * (1 + SLIPPAGE_PCT)
                put_entry_time = ts
                last_trade_bar = i
                hold_put       = False

        # ══════════ PUT MANAGEMENT ═══════════════════════════════════════
        elif put_open:
            if put_exit_trig:
                _close_put(close, ts, "ExitTrig->FlipCALL")
                call_open       = True
                call_entry      = close * (1 + SLIPPAGE_PCT)
                call_entry_time = ts
                last_trade_bar  = i
                hold_call       = False

            elif open_pctb <= PUT_EXIT_TRIG_PREV:
                hold_put = True

            elif hold_put and put_force_now:
                _close_put(close, ts, "ForceExit->FlipCALL")
                call_open       = True
                call_entry      = close * (1 + SLIPPAGE_PCT)
                call_entry_time = ts
                last_trade_bar  = i
                hold_call       = False

        # ══════════ FRESH ENTRIES ════════════════════════════════════════
        else:
            if buy_call:
                call_open       = True
                call_entry      = close * (1 + SLIPPAGE_PCT)
                call_entry_time = ts
                last_trade_bar  = i
                hold_call       = False

            elif buy_put:
                put_open        = True
                put_entry       = close * (1 + SLIPPAGE_PCT)
                put_entry_time  = ts
                last_trade_bar  = i
                hold_put        = False

    # Close any open trade at end of data
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
def compute_metrics(result: dict) -> dict:
    trades       = result["trades"]
    final_equity = result["final_equity"]
    df           = result["df"]

    if not trades:
        print("WARNING: No trades generated — check data range or parameters.")
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
    equity_curve = [INITIAL_CAPITAL] + list(tdf["equity"].values)
    peak = INITIAL_CAPITAL; max_dd = 0; max_dd_pct = 0
    for eq in equity_curve:
        peak = max(peak, eq)
        dd = peak - eq
        dd_pct = dd / peak * 100
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
    years        = days_in_data / 365
    cagr         = ((final_equity / INITIAL_CAPITAL) ** (1 / years) - 1) * 100 if years > 0 else 0
    calmar       = cagr / max_dd_pct if max_dd_pct else 0

    tdf["bars_held"] = (tdf["exit_time"] - tdf["entry_time"]).dt.total_seconds() / 2700  # 45-min bars
    avg_bars_held    = tdf["bars_held"].mean()

    # Consecutive streaks
    max_w = max_l = wins_s = losses_s = 0
    for w in tdf["win"]:
        if w:  wins_s += 1; losses_s = 0
        else:  losses_s += 1; wins_s = 0
        max_w = max(max_w, wins_s); max_l = max(max_l, losses_s)

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
        "initial_capital":   INITIAL_CAPITAL,
        "final_equity":      round(final_equity, 2),
        "total_return_pct":  round((final_equity - INITIAL_CAPITAL) / INITIAL_CAPITAL * 100, 2),
        "max_consec_wins":   max_w,
        "max_consec_losses": max_l,
        "avg_bars_held":     round(avg_bars_held, 1),
        "call_trades":       len(calls),
        "call_wins":         int(calls["win"].sum()) if len(calls) else 0,
        "put_trades":        len(puts),
        "put_wins":          int(puts["win"].sum()) if len(puts) else 0,
        "data_start":        str(df.index[0].date()),
        "data_end":          str(df.index[-1].date()),
        "tdf":               tdf,
    }


# ══════════════════════════════════════════════════════════════════════════════
#  PRINT REPORT  (terminal only — no file saving)
# ══════════════════════════════════════════════════════════════════════════════
def print_report(m: dict, symbol: str):
    tdf = m.pop("tdf")
    W = 68

    print("\n" + "=" * W)
    print(f"  BACKTEST REPORT  --  {symbol}  (45-min Bollinger %B v3)")
    print("=" * W)

    overview = [
        ["Data Period",     f"{m['data_start']}  ->  {m['data_end']}"],
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
        ["  CALL Wins/Total",   cwr],
        ["  PUT  Wins/Total",   pwr],
        ["Avg Win  (Rs)",       f"Rs {m['avg_win']:>10,.2f}"],
        ["Avg Loss (Rs)",       f"Rs {m['avg_loss']:>10,.2f}"],
        ["Profit Factor",       f"{m['profit_factor']:.3f}"],
        ["Expectancy / Trade",  f"Rs {m['expectancy']:>10,.2f}"],
        ["Avg Hold (bars/hrs)", f"{m['avg_bars_held']} bars  (~{m['avg_bars_held']*0.75:.1f} hrs)"],
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
    print("\n====================================================")
    print("  Gold MCX -- Bollinger %B Strategy Backtester v3")
    print("====================================================")
    print("  Strategy : %B Entries + Bull Market Band (20W SMA / 21W EMA)")
    print("  Exits    : ExitTrig / ExtraExit / ForceExit with CALL<->PUT flip")
    print("  Data     : MCX GOLD 45-min (fetched as 30-min, resampled)")
    print("====================================================\n")

    kite = zerodha_login()
    token, symbol = get_gold_instrument_token(kite)

    print(f"\nFetching 365 days of data for {symbol} (30-min -> resampled to 45-min) ...")
    df = fetch_ohlc(kite, token, days=365)
    print(f"Loaded {len(df)} bars  ({df.index[0].date()} -> {df.index[-1].date()})")

    print("\nRunning backtest ...")
    result  = run_backtest(df)
    metrics = compute_metrics(result)

    if metrics:
        print_report(metrics, symbol)


if __name__ == "__main__":
    main()
