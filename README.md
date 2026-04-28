# Strategy — NSE/MCX Trading Tools

Collection of **backtesting, optimization, scanning, and dashboard tools** for NSE equities, NSE F&O indices, and MCX commodity options. All tools use **Zerodha Kite API** for live and historical data.

---

## Project Files

| File | Role |
|---|---|
| `bb_backtest.py` | Universal Bollinger %B options strategy backtester — MCX + NSE equities |
| `bb_backtest_old.py` | Previous version of the backtester |
| `bb_optimize.py` | Grid-search parameter optimizer for `bb_backtest.py` — auto-patches best params |
| `bb_optimize_old.py` | Previous version of the optimizer |
| `gold_bb_backtest_v3.py` | GOLD MCX-specific Bollinger %B backtester (v3, Pine Script v2 logic) |
| `bullish_scanner_dashboard.py` | Streamlit intraday bullish stock scanner |
| `bullish_scanner_dashboard_old.py` | Previous version of the scanner |
| `index_dashboard_strike.py` | Streamlit index quant dashboard — OI, PCR, IV, Futures basis, Trend |
| `index_dashboard_strike_new.py` | Updated version of the index dashboard |
| `stock_analysis.py` | CLI stock analysis tool — Fundamental + Technical + News + Risk |

---

## Tool Details

### `bb_backtest.py` — Bollinger %B Options Backtester

Backtests a **%B + RSI + Bull Market Band + CALL↔PUT Flip** options strategy on 45-min candles.

**Supported instruments:**

| Category | Symbols |
|---|---|
| MCX Futures | GOLD, GOLDM, SILVER, SILVERM, NATURALGAS, CRUDEOIL, COPPER, ZINC, ALUMINIUM |
| NSE Equities | NTPC, RELIANCE, TCS, INFY, HDFCBANK, ICICIBANK, SBIN, TATASTEEL, ONGC, BHARTIARTL + any valid NSE symbol |

**Usage:**
```bash
python bb_backtest.py GOLD
python bb_backtest.py NATURALGAS --tf 30
python bb_backtest.py NTPC --tf 15 --days 180
python bb_backtest.py --symbol SILVER --tf 60 --days 180 --capital 200000
```

**Parameters:**

| Flag | Default | Description |
|---|---|---|
| `--symbol` | `GOLD` | Instrument name |
| `--days` | `365` | Lookback days for historical data |
| `--capital` | `100000` | Starting capital in ₹ |
| `--bb-len` | `20` | Bollinger Band length |
| `--bb-mult` | `2.0` | Bollinger Band multiplier |
| `--cooldown` | `3` | Bars cooldown between trades |
| `--tf` | `45` | Candle timeframe in minutes (15/30/45/60) |

**Strategy logic:**
- Entry: `%B` crosses signal threshold + RSI filter confirms direction
- Bull Market Band: shifts bias to CALL side in uptrend
- Flip Logic: switches CALL→PUT or PUT→CALL based on band position
- Brokerage: 0.03% per leg, Slippage: 0.1% per leg

---

### `bb_optimize.py` — Parameter Optimizer

Grid-searches all key parameters and ranks by composite score. Auto-patches `bb_backtest.py` with the best found parameters.

**Scoring formula:**
```
Score = Sharpe×40 + ProfitFactor×30 + WinRate×20 + CAGR×10
```

**Usage:**
```bash
python bb_optimize.py GOLD
python bb_optimize.py NATURALGAS --tf 30
python bb_optimize.py NTPC --tf 15 --days 180
python bb_optimize.py GOLD --quick        # fewer combos, faster
python bb_optimize.py GOLD --no-patch     # show best params, don't update bb_backtest.py
```

**Output:** Top-10 parameter sets ranked by score, with Sharpe, PnL, Win Rate, CAGR per combination.

---

### `gold_bb_backtest_v3.py` — GOLD MCX Backtester (v3)

GOLD-specific backtester implementing **Pine Script v2** Bollinger %B logic. Fetches 30-min candles from Zerodha, resamples to 45-min internally.

```bash
python gold_bb_backtest_v3.py
```

---

### `bullish_scanner_dashboard.py` — Intraday Bullish Scanner

Streamlit dashboard that screens NSE F&O stocks for intraday bullish setups in real-time.

**Screens for:**
- Pre-open price > Prev Close (gap-up / bullish open)
- 52-Week High breakers
- High Volume movers (2× average volume)
- Strong momentum (% change, RSI proxy, VWAP above open)

**Run:**
```bash
streamlit run bullish_scanner_dashboard.py
```

---

### `index_dashboard_strike.py` / `index_dashboard_strike_new.py` — Index Quant Dashboard

Streamlit dashboard for MFT (Market/Futures/Trading) research across all 5 indices.

**Indices covered:** NIFTY 50, BANKNIFTY, FINNIFTY, MIDCPNIFTY, SENSEX

**Parameters displayed:**

| Category | Metrics |
|---|---|
| Price | LTP, Open, High, Low, Change % |
| OI | Open Interest, OI Change, PCR (Put-Call Ratio) |
| Futures | Premium, Basis, Basis % |
| Volatility | IV (ATM options), VIX, ATR, Range Expansion |
| Trend | EMA structure, Price vs VWAP, Trend Bias |
| Intraday | HOD/LOD proximity, Range Position |

**Run:**
```bash
streamlit run index_dashboard_strike_new.py
```

---

### `stock_analysis.py` — Stock Analysis CLI Tool

Full fundamental + technical + news analysis for any NSE/BSE stock, printed as a formatted CLI report.

**Analysis sections:**
- **Fundamental:** P/E, P/B, EPS, Revenue, Debt/Equity, ROE, Promoter holding
- **Technical:** SMA 20/50/200, RSI, MACD, Bollinger Bands, VWAP, ATR, trend signals
- **News:** Latest headlines from Yahoo Finance
- **Risk:** Beta, 52-week range position, volatility assessment

**Usage:**
```bash
python stock_analysis.py RELIANCE
python stock_analysis.py TCS
python stock_analysis.py INFY
python stock_analysis.py HDFCBANK
```

---

## Architecture

```
Zerodha Kite API (historical + live data)
        │
        ├── bb_backtest.py          ← historical OHLCV → backtest P&L report
        │       ▲
        │       └── bb_optimize.py  ← grid-search → auto-patch best params
        │
        ├── gold_bb_backtest_v3.py  ← GOLD-specific backtest
        │
        ├── bullish_scanner_dashboard.py  ← live scan → Streamlit UI
        │
        ├── index_dashboard_strike_new.py ← live index data → Streamlit UI
        │
        └── stock_analysis.py       ← fundamental + technical → CLI report
                    +
            yfinance (fundamentals + news)
```

---

## Usage Summary

```bash
# Backtest
python bb_backtest.py GOLD --tf 45 --days 365
python bb_backtest.py RELIANCE --tf 15 --days 180

# Optimize
python bb_optimize.py GOLD --tf 45
python bb_optimize.py NATURALGAS --quick

# GOLD specific
python gold_bb_backtest_v3.py

# Streamlit dashboards
streamlit run bullish_scanner_dashboard.py
streamlit run index_dashboard_strike_new.py

# Stock analysis
python stock_analysis.py RELIANCE
python stock_analysis.py TCS
```

---

## Configuration

All Zerodha credentials via environment variables:

| Variable | Description |
|---|---|
| `KITE_API_KEY` | Zerodha API key |
| `KITE_SECRET` | Zerodha API secret |
| `KITE_USER_ID` | Zerodha user ID |
| `KITE_PASSWORD` | Zerodha password |
| `KITE_TOTP_KEY` | TOTP secret for 2FA auto-login |
| `KITE_PIN` | Zerodha PIN |

---

## Prerequisites

All dependencies are auto-installed on first run. Or install manually:

```bash
pip install kiteconnect pyotp pandas numpy tabulate requests \
            streamlit yfinance pandas-ta colorama --break-system-packages
```

- Python 3.9+
- Valid Zerodha Kite Connect API subscription
- Active Zerodha session (auto-login via TOTP on each run)
