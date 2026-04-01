# CryptoBot — Binance Algo Trader

Algorithmic trading bot for Binance supporting BTC, ETH, SOL, BNB, and DOGE.
Blends technical analysis, news sentiment, smart money positioning, economic calendar events, Fear & Greed index, funding rates, and open interest into a single trading signal.
Runs in testnet (paper trading) mode by default — no real money at risk until you're ready.

---

## Table of Contents

1. [Installation](#installation)
2. [Testing](#testing)
3. [Running the bot](#running-the-bot)
4. [Selling positions](#selling-positions)
5. [Backtesting](#backtesting)
6. [Performance dashboard](#performance-dashboard)
7. [Strategies](#strategies)
8. [Configuration reference](#configuration-reference)
9. [Signal sources and weights](#signal-sources-and-weights)
10. [Risk management](#risk-management)
11. [Protection mechanisms](#protection-mechanisms)
12. [Pyramiding (position scaling)](#pyramiding-position-scaling)
13. [File structure](#file-structure)
14. [Understanding the logs](#understanding-the-logs)
15. [Safety tips](#safety-tips)

---

## Installation

### Step 1 — Install Python

Download Python 3.11 or newer from https://python.org

```bash
python3 --version   # should print 3.11 or higher
```

### Step 2 — Install dependencies

Open a terminal inside the `cryptobot` folder:
```bash
pip3 install -r requirements.txt
```

### Step 3 — Set up your API keys

```bash
# Mac / Linux
cp .env.example .env

# Windows
copy .env.example .env
```

Open `.env` in any text editor and fill in your keys:

```
BINANCE_TESTNET_KEY=your_key_here
BINANCE_TESTNET_SECRET=your_secret_here
BINANCE_LIVE_KEY=your_live_key_here
BINANCE_LIVE_SECRET=your_live_secret_here
FREECRYPTOAPI_KEY=your_key_here
CRYPTOPANIC_KEY=your_key_here   # optional
```

**Binance testnet keys (start here — paper trading, no real money):**
1. Go to https://testnet.binance.vision
2. Log in with your GitHub account
3. Click "Generate HMAC_SHA256 Key"
4. Copy the API Key and Secret into `.env`

**Binance live keys (when you're ready for real trading):**
1. Go to https://www.binance.com → Profile → API Management
2. Create a new API key
3. Enable: "Enable Reading" + "Enable Spot & Margin Trading" only
4. Restrict access to your IP address for safety
5. Copy into `.env` under `BINANCE_LIVE_KEY` and `BINANCE_LIVE_SECRET`

**FreeCryptoAPI key (24h price momentum signals):**
- Register at https://freecryptoapi.com/panel — free tier available

**CryptoPanic key (optional — news headlines with higher rate limit):**
- Register at https://cryptopanic.com/developers/api — free tier available

---

## Testing

Before running the bot with real market data, verify that all bug fixes and validations are working correctly:

```bash
# Run the comprehensive test suite (11 tests)
python3 test_fixes_v2.py
```

**What this tests:**
- ✅ Config validation (API keys and parameter ranges)
- ✅ Division by zero protections (drawdown & EMA)
- ✅ Atomic file writes (crash-safe position storage)
- ✅ Symbol validation (prevents invalid trading pairs)
- ✅ Order execution verification (checks actual fills)
- ✅ CLI pair validation (validates input pairs)
- ✅ OHLCV data validation (backtest data integrity)
- ✅ Float precision handling (prevents rounding errors)
- ✅ Error handling framework (clear error messages)

**Expected output:**
```
🎉 ALL TESTS PASSED! All 11 bug fixes verified successfully.
✅ PASSED: 11/11
```

If all tests pass, the bot is ready to use. If any tests fail, review the output for specific issues to fix.

---

## Running the bot

### Basic usage

```bash
# Testnet (paper trading) — default, always start here
python3 bot.py

# Live trading — real money, be careful
python3 bot.py --live
```

### Choose a strategy

```bash
python3 bot.py --strategy ema       # EMA Crossover (default — most balanced)
python3 bot.py --strategy rsi       # RSI Reversal (best for sideways markets)
python3 bot.py --strategy bb        # Bollinger Bands (best for ranging markets)
python3 bot.py --strategy macd      # MACD (best for trending markets on 15m/1h)
```

### Choose trading pairs

```bash
# All 5 pairs (default)
python3 bot.py

# Specific pairs only
python3 bot.py --pairs BTCUSDT ETHUSDT

# Single pair
python3 bot.py --pairs DOGEUSDT
```

### Choose candle timeframe

Longer timeframes produce fewer but higher-quality signals.

```bash
python3 bot.py --timeframe 1m       # 1 minute — very active, noisy
python3 bot.py --timeframe 5m       # 5 minutes (default)
python3 bot.py --timeframe 15m      # 15 minutes — recommended for MACD
python3 bot.py --timeframe 1h       # 1 hour — slowest, most reliable signals
```

### Adjust aggression

Aggression controls how boldly the bot acts on signals. Lower = fewer trades with higher conviction. Higher = more trades but more risk.

```bash
python3 bot.py --aggression 0.5     # conservative — only very strong signals
python3 bot.py --aggression 1.0     # balanced
python3 bot.py --aggression 1.5     # bold (default)
python3 bot.py --aggression 2.0     # aggressive — trades frequently, higher risk
```

### Disable news sentiment

```bash
python3 bot.py --no-news            # technical signals only, faster cycles
```

### Combine options

```bash
# Balanced MACD on 15m candles for BTC and ETH only
python3 bot.py --strategy macd --timeframe 15m --pairs BTCUSDT ETHUSDT --aggression 1.2

# Conservative live trading — RSI only, no news
python3 bot.py --strategy rsi --aggression 0.8 --live --no-news

# Aggressive testnet run across all pairs
python3 bot.py --aggression 2.0 --timeframe 5m
```

---

## Selling positions

These commands execute immediately and exit without starting the trading loop.

```bash
# Sell all open positions (testnet)
python3 bot.py --sell-all

# Sell all open positions (live — prompts for confirmation)
python3 bot.py --sell-all --live

# Sell specific coins (both formats work)
python3 bot.py --sell BTCUSDT
python3 bot.py --sell BTC

# Sell multiple coins at once
python3 bot.py --sell BTC ETH DOGE --live
```

---

## Backtesting

Test a strategy against real historical data before going live. Run `backtest.py` independently — it does not require the bot to be running.

### Basic usage

```bash
# Test current config on BTC, last 30 days
python3 backtest.py

# Test a specific strategy
python3 backtest.py --strategy macd --timeframe 15m --days 60

# Test all 5 pairs
python3 backtest.py --all-pairs --days 30

# Test a specific aggression level before changing config
python3 backtest.py --aggression 0.8 --days 90

# Test with a custom starting balance
python3 backtest.py --balance 50000 --days 30
```

### Backtest minimum order sizes

The backtest uses lower minimum order sizes than the live bot to allow realistic position sizing with typical backtest balances ($10,000 default):

- **BTCUSDT/ETHUSDT**: $50 minimum (vs $1000 live)
- **SOLUSDT/BNBUSDT/DOGEUSDT**: $10 minimum (vs $150 live)

This prevents the "0 trades" issue that would occur if using live exchange minimums with small position sizes.

### Trend filter and downtrends

If the market was in a downtrend during your test period, the 200 EMA trend filter will block all buy signals and you will see 0 trades. This is correct behaviour — the filter is protecting you. The backtest will automatically re-run without the filter so you can see what would have happened without protection:

```
⚠  0 trades — 2212 buy signals blocked by 200 EMA trend filter
   This period is a downtrend. Auto-running without trend filter for comparison...
```

To manually disable the trend filter for a backtest:
```bash
python3 backtest.py --no-trend-filter --days 90
```

### Reading backtest output

```
=======================================================
  BTCUSDT Backtest Results
=======================================================
  Balance:       $ 10,000.00 → $ 10,847.32
  Strategy P&L:  +8.47%   ($+847.32)
  Buy & Hold:    +3.21%
  ─────────────────────────────────────────────
  Trades:        24  (16 wins / 8 losses)
  Win rate:      66.7%
  Avg win:       $+124.50   Avg loss: $-63.20
  Profit factor: 2.48
  Max drawdown:  4.32%
  Sharpe ratio:  1.847
  ─────────────────────────────────────────────
  Signal breakdown:
    Buy signals:          89
    Sell signals:        112
    Neutral:             643
    Trend filter blocked:  23
  ─────────────────────────────────────────────
  Exits by reason:
    stop_loss            8 trades   $-505.60
    take_profit         11 trades   $+832.40
    trailing_stop        5 trades   $+520.52
```

- **Profit factor** above 1.5 is good. Above 2.0 is excellent.
- **Sharpe ratio** above 1.0 is acceptable. Above 2.0 is strong.
- **Max drawdown** is the worst peak-to-trough loss during the period.
- **vs Buy & Hold** tells you whether your strategy actually beat just holding.

### Backtest workflow for config changes

Before changing any setting in `config.py`, test it first:

```bash
# Current config baseline
python3 backtest.py --days 60 --strategy ema

# Test with higher aggression
python3 backtest.py --days 60 --strategy ema --aggression 2.0

# Test with different strategy
python3 backtest.py --days 60 --strategy macd --timeframe 15m

# Then open the dashboard to compare all runs
python3 dashboard.py
```

---

## Performance dashboard

Reads `logs/bot.log` and `backtest_results.json` to generate a visual HTML dashboard.

```bash
# Generate and open in browser automatically
python3 dashboard.py

# Generate without opening browser
python3 dashboard.py --no-open

# Custom file paths
python3 dashboard.py --log logs/bot.log --backtest backtest_results.json --output my_dashboard.html
```

The dashboard has two tabs:

**Live Trading tab** — shows portfolio value over time, win rate, P&L, exit reason breakdown (stop loss vs take profit vs trailing stop), performance per pair, and full trade history.

**Backtests tab** — shows every backtest run side by side in a comparison table. Each row includes strategy, timeframe, aggression, period, P&L, win rate, max drawdown, trades, Sharpe ratio, and how it compares to buy-and-hold. Rows with 0 trades due to the trend filter are highlighted in amber with an explanation. All equity curves are overlaid on the same chart so you can visually compare configs.

---

## Strategies

| Strategy | Flag | Best for | Avoid when |
|----------|------|----------|------------|
| EMA Crossover | `--strategy ema` | Trending markets, any timeframe | Sideways/choppy markets |
| RSI Reversal | `--strategy rsi` | Ranging markets, bounce trading | Strong sustained downtrends |
| Bollinger Bands | `--strategy bb` | Low-volatility ranging periods | Strong breakouts / rallies |
| MACD | `--strategy macd` | Trending markets on 15m or 1h | Short 5m timeframes during volatility |

**Recommendation by market condition:**

| Market | Best strategy | Timeframe |
|--------|--------------|-----------|
| Strong uptrend | EMA or MACD | 15m or 1h |
| Sideways range | RSI or BB | 5m or 15m |
| High volatility / news day | RSI with low aggression | 15m |
| Unknown / mixed | EMA (default) | 5m |

### MACD quality filters

The MACD strategy includes four filters that reduce false signals on short timeframes. All are configurable in `config.py`:

```python
self.MACD_MIN_HIST_MULT  = 0.5   # min histogram size (0.3=loose, 0.8=strict)
self.MACD_RSI_OVERBOUGHT = 65    # block MACD buys above this RSI value
self.MACD_RSI_OVERSOLD   = 35    # block MACD sells below this RSI value
self.MACD_VOL_PERIOD     = 20    # volume lookback for confirmation
```

## Strategy by market condition

Use this as a quick reference when deciding which strategy and settings to run.

| Market | Strategy | Timeframe | Aggression | Notes |
|--------|----------|-----------|------------|-------|
| Strong bull run | MACD | 15m | 1.8 | Momentum captures full moves; pyramid on |
| Steady uptrend | EMA | 15m or 1h | 1.5 | Most reliable in trending conditions |
| Sideways / ranging | RSI or BB | 5m or 15m | 1.0 | Mean-reversion works well in ranges |
| Bearish / downtrend | RSI | 15m | 0.8 | Catches oversold bounces; tight stops |

### Bullish market — recommended config

EMA or MACD with wider stops and higher take profit to let winners run:

```bash
python3 bot.py --strategy ema --timeframe 15m --aggression 1.8
python3 bot.py --strategy macd --timeframe 15m --aggression 1.5
```

```python
# config.py adjustments for bull market
self.STOP_LOSS_PCT              = 4.0    # wider — give positions room to breathe
self.TAKE_PROFIT_PCT            = 12.0   # higher — let winners run
self.MAX_POSITIONS              = 5      # more exposure during uptrend
self.PYRAMID_ENABLED            = True   # scale into winning positions
self.PYRAMID_MIN_CONFIDENCE     = 0.65   # lower bar for add-ons
self.TRAILING_STOP_ACTIVATION_PCT = 2.0  # activate trailing after +2%
```

When smart money shows LONG signals (e.g. SOL +0.648, DOGE +0.662) the combined score is boosted significantly — expect higher confidence entries and larger position sizes via confidence scaling.

### Bearish market — recommended config

RSI with tight stops and lower aggression. The 200 EMA trend filter will block most buys automatically — this is correct behaviour, not a bug.

```bash
python3 bot.py --strategy rsi --timeframe 15m --aggression 0.8
```

```python
# config.py adjustments for bear market
self.STOP_LOSS_PCT              = 2.0    # tight — cut losses fast
self.TAKE_PROFIT_PCT            = 4.0    # take profits quickly on bounces
self.MAX_POSITIONS              = 2      # minimal exposure
self.BTC_DROP_BLOCK_PCT         = 1.5    # more sensitive BTC correlation filter
self.TRAILING_STOP_ACTIVATION_PCT = 0.5  # trailing activates sooner
```

> **Note:** BB is dangerous in a bear market. Price can "walk the lower band" for weeks, triggering repeated buy signals while price keeps falling. Avoid BB during sustained downtrends.

### Sideways / ranging market — recommended config

RSI or BB — both are mean-reversion strategies that work well when price bounces between support and resistance.

```bash
python3 bot.py --strategy rsi --timeframe 5m --aggression 1.0
python3 bot.py --strategy bb  --timeframe 15m --aggression 1.0
```

```python
# config.py adjustments for ranging market
self.STOP_LOSS_PCT   = 3.0
self.TAKE_PROFIT_PCT = 6.0
self.MAX_POSITIONS   = 4
self.AGGRESSION      = 1.0
```

---

## Security

### API key safety

- **Never share your `.env` file** — it contains your Binance API keys
- **Restrict your live API key to your IP address** in Binance API Management — this prevents anyone who steals the key from using it elsewhere
- **Only enable the minimum permissions** — "Enable Reading" and "Enable Spot & Margin Trading" only. Never enable withdrawals.
- **Use testnet keys for development** — testnet keys cannot access real funds even if leaked

### What the bot logs

The log file (`logs/bot.log`) contains trade decisions, prices, and P&L — but **never logs API keys, secrets, or raw account data**. It is safe to share for debugging.

What IS logged: signal scores, trade prices, P&L, strategy decisions, error messages.
What is NOT logged: API keys, API secrets, full account balances breakdown, raw HTTP responses.

### Git / version control

A `.gitignore` file is included that prevents the following from being accidentally committed:

```
.env                  # your API keys — NEVER commit this
positions.json        # contains your buy prices and quantities
backtest_results.json # contains trade history
logs/                 # contains trade decisions
dashboard.html        # generated output
```

If you use Git, always verify `.env` is listed as untracked before pushing:
```bash
git status   # .env should appear under "Untracked files", never under "Changes to commit"
```

---

All settings live in `config.py`. Edit them directly, then backtest before going live.

### Risk management

```python
self.STOP_LOSS_PCT    = 3.0   # exit if price drops 3% from entry
self.TAKE_PROFIT_PCT  = 8.0   # exit if price rises 8% from entry
self.POSITION_SIZE_PCT = 5.0  # use 5% of available balance per trade
self.MAX_POSITIONS    = 6     # max 6 open trades at once
self.MIN_RESERVE_USDT = 500.0 # always keep $500 in reserve, never trade it
```

**Example — conservative settings:**
```python
self.STOP_LOSS_PCT     = 2.0
self.TAKE_PROFIT_PCT   = 5.0
self.POSITION_SIZE_PCT = 3.0
self.MAX_POSITIONS     = 3
self.MIN_RESERVE_USDT  = 1000.0
```

**Example — aggressive settings:**
```python
self.STOP_LOSS_PCT     = 5.0
self.TAKE_PROFIT_PCT   = 12.0
self.POSITION_SIZE_PCT = 8.0
self.MAX_POSITIONS     = 6
self.MIN_RESERVE_USDT  = 200.0
```

### Trailing stop loss

Once price gains `TRAILING_STOP_ACTIVATION_PCT` from entry, the fixed stop loss is replaced by a trailing stop that follows the price up, always sitting `STOP_LOSS_PCT`% below the highest price reached.

```python
self.TRAILING_STOP_ENABLED        = True
self.TRAILING_STOP_ACTIVATION_PCT = 1.0   # trailing activates after +1% gain
self.TRAILING_STOP_REPLACE_FIXED  = True  # replace fixed stop once trailing is active
```

**Example — how it works:**
```
Entry:          74,000  →  fixed stop at 71,780 (-3%)
Price → 74,740  (+1%)   →  trailing ACTIVATES at 72,498
Price → 77,000  (+4%)   →  trailing moves up to 74,690
Price → 74,690  (falls) →  SELL — locked in +0.9% profit instead of -3%
```

**To disable trailing stop and use fixed only:**
```python
self.TRAILING_STOP_ENABLED = False
```

### Strategy parameters

```python
# EMA Crossover
self.EMA_FAST = 9    # fast line period (lower = more responsive)
self.EMA_SLOW = 21   # slow line period (higher = smoother)

# RSI
self.RSI_PERIOD     = 14   # lookback period
self.RSI_OVERSOLD   = 30   # buy signal below this
self.RSI_OVERBOUGHT = 70   # sell signal above this

# Bollinger Bands
self.BB_PERIOD = 20    # moving average period
self.BB_STD    = 2.0   # standard deviation width (higher = wider bands)

# MACD
self.MACD_FAST   = 12
self.MACD_SLOW   = 26
self.MACD_SIGNAL = 9
```

**Example — more sensitive EMA (catches moves faster, more false signals):**
```python
self.EMA_FAST = 5
self.EMA_SLOW = 13
```

**Example — wider RSI bands (fewer but stronger signals):**
```python
self.RSI_OVERSOLD   = 25
self.RSI_OVERBOUGHT = 75
```

### Signal blending weights

All six signal sources contribute to the final decision. Weights must sum to 1.0.

```python
self.TECHNICAL_WEIGHT   = 0.30   # EMA / RSI / BB / MACD price analysis
self.NEWS_WEIGHT        = 0.20   # headline sentiment + FreeCryptoAPI
self.SMART_MONEY_WEIGHT = 0.20   # Binance top trader long/short ratio
self.CALENDAR_WEIGHT    = 0.10   # economic events (Fed, CPI, NFP, GDP)
self.FNG_WEIGHT         = 0.10   # Fear & Greed index
self.FUNDING_WEIGHT     = 0.10   # Binance futures funding rate
```

**Example — trust technicals more, ignore macro:**
```python
self.TECHNICAL_WEIGHT   = 0.55
self.NEWS_WEIGHT        = 0.25
self.SMART_MONEY_WEIGHT = 0.20
self.CALENDAR_WEIGHT    = 0.00
self.FNG_WEIGHT         = 0.00
self.FUNDING_WEIGHT     = 0.00
```

**Example — balance all sources equally:**
```python
self.TECHNICAL_WEIGHT   = 0.25
self.NEWS_WEIGHT        = 0.20
self.SMART_MONEY_WEIGHT = 0.20
self.CALENDAR_WEIGHT    = 0.15
self.FNG_WEIGHT         = 0.10
self.FUNDING_WEIGHT     = 0.10
```

> **Important:** Always backtest after changing weights. If weights don't sum to 1.0 the bot will normalise them automatically.

### Aggression and thresholds

```python
self.AGGRESSION     = 1.5   # signal strength multiplier
self.BUY_THRESHOLD  = 0.25  # boosted score must exceed this to buy
self.SELL_THRESHOLD = 0.25  # boosted score must fall below -this to sell
```

Higher aggression + lower thresholds = more trades. Lower aggression + higher thresholds = fewer, higher-conviction trades.

**Example — high conviction only:**
```python
self.AGGRESSION     = 1.0
self.BUY_THRESHOLD  = 0.40
self.SELL_THRESHOLD = 0.40
```

---

## Signal sources and weights

### Technical analysis (30%)

Price-based indicators computed from candle data. Provides the core trading signal.

### News sentiment (20%)

Fetches headlines from CryptoPanic RSS and FreeCryptoAPI 24h price change. General market articles (SEC rulings, Fed decisions) are scored separately and applied to all coins.

```python
self.NEWS_CACHE_TTL          = 3600   # fetch news once per hour
self.NEWS_BLOCK_BUY_BELOW    = -0.6   # block all buys if news is this bearish
self.NEWS_BLOCK_SELL_ABOVE   = 0.6    # suppress sells if news is this bullish
self.MARKET_SENTIMENT_WEIGHT = 0.2    # weight of general vs coin-specific news
self.FREECRYPTOAPI_WEIGHT    = 0.5    # weight of price signal vs text headlines
```

### Smart money — top trader L/S ratio (20%)

Fetches the long/short position ratio of Binance's top traders (top 20% by PnL) from the public Futures API. No API key needed.

```python
self.SMART_MONEY_ENABLED   = True
self.SMART_MONEY_CACHE_TTL = 900    # refresh every 15 minutes
```

When more top traders are long than short, score is positive (bullish). When more are short, score is negative (bearish).

### Economic calendar (10%)

Fetches this week's economic events from ForexFactory (free, no key needed). Events within ±2 hours of now are scored. A Fed rate decision or CPI print that beats forecast is bullish; a miss is bearish. Upcoming unresolved events create a mild caution signal.

```python
self.CALENDAR_ENABLED     = True
self.CALENDAR_CACHE_TTL   = 3600   # refresh once per hour
self.CALENDAR_WINDOW_MINS = 120    # consider events within ±2 hours
```

**Example — tighter event window (only care about imminent events):**
```python
self.CALENDAR_WINDOW_MINS = 60   # ±1 hour only
```

### Fear & Greed Index (10%)

Fetches the Crypto Fear & Greed Index from alternative.me (free, no key). Extreme fear is a contrarian buy signal; extreme greed is a caution signal.

```python
self.FNG_ENABLED   = True
self.FNG_CACHE_TTL = 3600   # update once per hour
```

### Funding rate (10%)

Fetches the Binance futures funding rate per coin. High positive funding means longs are paying shorts — market is overextended and likely to correct. No API key needed.

```python
self.FUNDING_ENABLED   = True
self.FUNDING_CACHE_TTL = 900   # refresh every 15 minutes
```

---

## Risk management

### Volatility filter

Reduces position size or skips trades entirely when the market is erratic. Uses ATR (Average True Range) as a % of price.

```python
self.VOLATILITY_FILTER_ENABLED = True
self.VOL_NORMAL_THRESHOLD      = 0.015   # ATR/price > 1.5% → reduce size
self.VOL_HIGH_THRESHOLD        = 0.030   # ATR/price > 3.0% → half size
self.VOL_EXTREME_THRESHOLD     = 0.050   # ATR/price > 5.0% → skip trade
```

**Example — stricter thresholds (less trading during volatility):**
```python
self.VOL_NORMAL_THRESHOLD  = 0.010   # 1% triggers reduction
self.VOL_HIGH_THRESHOLD    = 0.020   # 2% halves size
self.VOL_EXTREME_THRESHOLD = 0.035   # 3.5% skips trade
```

### BTC correlation filter

Blocks ALT coin buys if BTC drops sharply in the last 2 candles. ALTs almost always follow BTC down.

```python
self.BTC_CORRELATION_FILTER = True
self.BTC_DROP_BLOCK_PCT     = 2.0   # block ALT buys if BTC drops 2% in 2 candles
```

**Example — more sensitive:**
```python
self.BTC_DROP_BLOCK_PCT = 1.5   # block if BTC drops 1.5%
```

### Multi-timeframe confirmation

Before acting on a 5m signal, checks that the 1h trend agrees. Prevents buying into short-term bounces within a larger downtrend.

```python
self.MTF_ENABLED         = True
self.MTF_AGREE_THRESHOLD = 0.2   # 1h score must be > 0.2 for full confidence
```

If the 1h is neutral, the trade still proceeds but confidence is reduced 20%. If the 1h is bearish, the buy is blocked entirely.

**To disable multi-timeframe check:**
```python
self.MTF_ENABLED = False
```

### Trend filter (200 EMA)

Blocks all buy signals when price is below the 200-candle EMA. Prevents buying into sustained downtrends. This is the most important protection — it would have prevented the -$1,500 loss scenario.

```python
self.TREND_FILTER_ENABLED = True
self.TREND_EMA_PERIOD     = 200
```

**To disable (not recommended for live trading):**
```python
self.TREND_FILTER_ENABLED = False
```

### Drawdown circuit breaker

If your session losses exceed `MAX_DRAWDOWN_PCT` of starting balance, all new buys stop for the rest of the session. Existing positions are still managed by stop loss / take profit.

```python
self.DRAWDOWN_CIRCUIT_BREAKER = True
self.MAX_DRAWDOWN_PCT         = 5.0   # halt new buys after 5% session loss
```

**Example — stricter circuit breaker:**
```python
self.MAX_DRAWDOWN_PCT = 3.0   # halt after 3% loss
```

---

## Pyramiding (position scaling)

The bot can add to a winning position if the signal confidence stays high. Each add-on is 25% of the original position size.

```python
self.PYRAMID_ENABLED        = True
self.PYRAMID_MAX_ADDONS     = 1      # max 1 add-on (2 total buys per position)
self.PYRAMID_MIN_CONFIDENCE = 0.70   # signal must be 70%+ confident
self.PYRAMID_ADDON_SIZE_PCT = 0.25   # add-on is 25% of original entry size
```

**Example with BTC:**
```
BUY  0.100 BTC @ 74,000  =  $7,400   (initial entry)
ADD  0.025 BTC @ 74,500  =  $1,863   (25% of initial, if conf > 70%)
Avg entry: $74,100 | Total: 0.125 BTC
```

**To disable pyramiding:**
```python
self.PYRAMID_ENABLED = False
```

---

## File structure

```
cryptobot/
├── bot.py               # Main entry point — run this to start trading
├── backtest.py          # Backtester — test strategies on historical data
├── dashboard.py         # Dashboard generator — creates HTML report
├── config.py            # All settings — edit this to tune the bot
├── strategy.py          # EMA / RSI / BB / MACD signal logic
├── exchange.py          # Binance API connection and order management
├── risk.py              # Position sizing, stop loss, trailing stop, trade tracking
├── news.py              # CryptoPanic + FreeCryptoAPI sentiment analysis
├── smart_money.py       # Binance top trader L/S ratio
├── market_filters.py    # Fear & Greed, funding rate, OI, volatility, BTC correlation
├── multi_timeframe.py   # 1h timeframe confirmation filter
├── calendar_events.py   # ForexFactory economic calendar
├── logger.py            # Logging setup
├── requirements.txt     # Python dependencies
├── .env.example         # Copy to .env and fill in your API keys
├── positions.json       # Auto-generated — stores buy prices across restarts
├── backtest_results.json # Auto-generated — stores all backtest run history
├── dashboard.html       # Auto-generated by dashboard.py
└── logs/
    └── bot.log          # Full log of every decision, signal, and trade
```

---

## Understanding the logs

### Holdings table (printed every cycle)

```
| Asset | Quantity    | Bought At  |       Price | Value (USDT) | Unrealised P&L  |
| BTC   | 0.08370     | 73,882.35  |  74,012.00  |     6,197.20 | +10.87 (+0.18%) |
| ETH   | 2.66340 +1x |  2,318.48  |   2,325.00  |     6,192.36 |  +17.20 (+0.3%) |
| DOGE  | 43552.00000 |          — |      0.1009 |     4,395.27 |               — |
```

- `Bought At` shows the real price the bot paid. `—` means the position was held before the bot started (buy price unknown).
- `+1x` in Quantity means one add-on buy was placed on this position.
- `Unrealised P&L` only shows when the buy price is known.
- `positions.json` stores buy prices across restarts so they are never lost.

### Signal debug lines

```
BTCUSDT | price=74012 | signal=buy | conf=0.82 | tech=+0.512 mom=+0.000 news=+0.142 sm=+0.380 cal=-0.050 fng=+0.200 fund=+0.100 combined=+0.340 boosted=+0.510 aggr=1.5x trend_ema=71420.00 (+3.6%)
```

Each component of the signal is shown so you can understand exactly what drove the decision.

### Smart money table (every 15 minutes)

```
Smart Money:
+------+---------+---------+---------+----------+
| Coin |     L/S | Leaders |   Final | Signal   |
| BTC  |  +0.480 |  +0.000 |  +0.480 | mostly L |
| DOGE |  -0.600 |  +0.000 |  -0.600 | SHORT    |
```

### News sentiment table (every hour)

```
| Coin | Final  |  Price | Mood     | Coin art |
| BTC  | +0.312 | -0.028 | positive |        8 |
  general market: 15 articles (score=-0.300) applied to all coins at 20% weight
```

### Protection events

```
ETHUSDT: BUY blocked — BTC dropped -2.3% in last 2 candles
SOLUSDT: BUY blocked by MTF — 1h score=-0.412 (bearish)
DRAWDOWN CIRCUIT BREAKER TRIGGERED — session loss 5.0% exceeds limit 5.0%. New buys halted.
[HIGH] 14:30 UTC USD — Federal Funds Rate | actual=pending forecast=5.25%
```

---

## Safety tips

1. **Always run testnet for at least 2 weeks** before switching to live
2. **Backtest any config change** before using it with real money — `python3 backtest.py`
3. **Start with small position sizes** (2–3%) when going live for the first time
4. **Never deposit more than you can afford to lose** on any exchange
5. **Restrict your Binance API key to your IP address** — do this in API Management settings
6. **Check the dashboard regularly** — `python3 dashboard.py` shows win rate and P&L trends
7. **Use `--sell-all` before major news events** (Fed meetings, CPI prints) if you want zero exposure
8. **Keep `MAX_POSITIONS` at 2–3** while you're still learning how the bot behaves
9. **The trend filter is your best friend** — if it's blocking all trades, the market is in a downtrend and that's correct
10. **Never disable the drawdown circuit breaker** for live trading
