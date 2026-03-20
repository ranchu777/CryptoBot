# CryptoBot — Binance Algo Trader

Algorithmic trading bot for Binance supporting BTC, ETH, SOL, BNB, and DOGE.
Combines technical analysis with live news sentiment for smarter trade decisions.
Runs in testnet (paper trading) mode by default — no real money at risk until you're ready.

---

## Installation

### Step 1 — Install Python

Download Python 3.11 or newer from https://python.org

Verify it's installed:
```bash
python3 --version
```

### Step 2 — Install dependencies

Open a terminal inside the `cryptobot` folder and run:
```bash
pip3 install -r requirements.txt
```

### Step 3 — Set up your API keys

Copy the example env file:
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
FREECRYPTOAPI_KEY=your_key_here
CRYPTOPANIC_KEY=your_key_here   # optional
```

**Getting Binance testnet keys (start here — no real money):**
1. Go to https://testnet.binance.vision
2. Log in with your GitHub account
3. Click "Generate HMAC_SHA256 Key"
4. Copy the API Key and Secret into `.env`

**Getting Binance live keys (when you're ready):**
1. Go to https://www.binance.com → Profile → API Management
2. Create a new API key
3. Enable: "Enable Reading" + "Enable Spot & Margin Trading" only
4. Restrict access to your IP address for safety
5. Copy into `.env` under `BINANCE_LIVE_KEY` and `BINANCE_LIVE_SECRET`

**Getting FreeCryptoAPI key (price momentum signals):**
- Go to https://freecryptoapi.com/panel and register

**Getting CryptoPanic key (optional — news headlines):**
- Go to https://cryptopanic.com/developers/api and register free

---

## Running the bot

### Basic usage

```bash
# Testnet (paper trading) — default, safe to run
python3 bot.py

# Live trading — real money
python3 bot.py --live
```

### Choose a strategy

```bash
python3 bot.py --strategy ema       # EMA Crossover (default)
python3 bot.py --strategy rsi       # RSI Reversal
python3 bot.py --strategy bb        # Bollinger Bands
python3 bot.py --strategy macd      # MACD
```

### Choose trading pairs

```bash
# Trade specific pairs only
python3 bot.py --pairs BTCUSDT ETHUSDT

# Trade a single pair
python3 bot.py --pairs DOGEUSDT
```

### Choose candle timeframe

```bash
python3 bot.py --timeframe 1m       # 1 minute candles
python3 bot.py --timeframe 5m       # 5 minutes (default)
python3 bot.py --timeframe 15m      # 15 minutes
python3 bot.py --timeframe 1h       # 1 hour
```

### Adjust aggression

```bash
python3 bot.py --aggression 0.5     # conservative — fewer trades
python3 bot.py --aggression 1.0     # balanced
python3 bot.py --aggression 1.5     # bold (default)
python3 bot.py --aggression 2.0     # aggressive — more trades, higher risk
```

### Disable news sentiment

```bash
# Use technical analysis only, skip news fetching
python3 bot.py --no-news
```

### Combine options

```bash
python3 bot.py --strategy rsi --timeframe 15m --pairs BTCUSDT ETHUSDT --aggression 1.2
python3 bot.py --strategy macd --live --no-news
```

---

## Selling positions

These commands place market sell orders immediately and exit — they do not start the trading loop.

### Sell everything

```bash
# Testnet
python3 bot.py --sell-all

# Live (prompts for confirmation)
python3 bot.py --sell-all --live
```

### Sell specific coins

```bash
# Single coin (both formats accepted)
python3 bot.py --sell BTCUSDT
python3 bot.py --sell BTC

# Multiple coins at once
python3 bot.py --sell BTCUSDT ETHUSDT DOGEUSDT
python3 bot.py --sell BTC ETH DOGE

# Live (prompts for confirmation)
python3 bot.py --sell BTCUSDT --live
```

The output shows a full summary table including bought price, sold price, and P&L for each position.

---

## Strategies

| Name | Flag | How it works |
|------|------|-------------|
| EMA Crossover | `--strategy ema` | Buys when fast EMA crosses above slow EMA (golden cross), exits on reverse |
| RSI Reversal | `--strategy rsi` | Buys when RSI is oversold (below 30), exits when overbought (above 70) |
| Bollinger Bands | `--strategy bb` | Buys when price touches lower band, exits at upper band |
| MACD | `--strategy macd` | Buys on MACD/signal line bullish crossover, exits on bearish crossover |

All strategies blend with news sentiment automatically. Use `--no-news` to disable this.

---

## Configuration

All settings are in `config.py`. The key ones to tune:

**Risk management:**

| Setting | Default | What it does |
|---------|---------|-------------|
| `STOP_LOSS_PCT` | 3% | Exit if price drops this much from entry |
| `TAKE_PROFIT_PCT` | 8% | Exit if price rises this much from entry |
| `POSITION_SIZE_PCT` | 5% | % of available balance used per trade |
| `MAX_POSITIONS` | 4 | Maximum number of open trades at once |
| `MIN_RESERVE_USDT` | 50 | USDT to always keep in reserve, never trade |
| `MIN_ORDER_USDT` | varies | Minimum order size per pair |

**Strategy parameters:**

| Setting | Default | What it does |
|---------|---------|-------------|
| `AGGRESSION` | 1.5 | Signal strength multiplier (0.5–2.0) |
| `BUY_THRESHOLD` | 0.25 | Minimum combined score to trigger a buy |
| `SELL_THRESHOLD` | 0.25 | Minimum combined score to trigger a sell |
| `EMA_FAST / EMA_SLOW` | 9 / 21 | EMA crossover periods |
| `RSI_PERIOD` | 14 | RSI calculation period |
| `MOMENTUM_CANDLE_PCT` | 3% | % move in one candle that triggers momentum buy |

**News and sentiment:**

| Setting | Default | What it does |
|---------|---------|-------------|
| `NEWS_CACHE_TTL` | 3600 | Seconds between news fetches (3600 = 1 hour) |
| `TECHNICAL_WEIGHT` | 0.65 | Weight of technical signals in final score |
| `NEWS_WEIGHT` | 0.35 | Weight of news sentiment in final score |
| `FREECRYPTOAPI_WEIGHT` | 0.5 | Weight of price momentum vs text headlines |
| `MARKET_SENTIMENT_WEIGHT` | 0.2 | Weight of general market news on each coin |
| `NEWS_BLOCK_BUY_BELOW` | -0.6 | Block buys if news sentiment is this bearish |
| `NEWS_BLOCK_SELL_ABOVE` | 0.6 | Suppress sells if news is this bullish |

---

## File structure

```
cryptobot/
├── bot.py            # Main entry point — run this
├── config.py         # All settings
├── exchange.py       # Binance API connection and order management
├── strategy.py       # EMA / RSI / BB / MACD signal logic + momentum detection
├── risk.py           # Position sizing, stop loss, trade tracking
├── news.py           # CryptoPanic + FreeCryptoAPI sentiment analysis
├── logger.py         # Logging setup
├── requirements.txt  # Python dependencies
├── .env.example      # Copy to .env and fill in your API keys
├── positions.json    # Auto-generated — stores buy prices across restarts
└── logs/
    └── bot.log       # Full log of every decision, trade, and signal
```

---

## Understanding the logs

Every cycle the bot prints a holdings table:

```
| Asset | Quantity  | Bought At  |      Price | Value (USDT) | Unrealised P&L  |
| BTC   | 0.08370   | 73,882.35  | 74,012.00  |     6,197.20 | +10.87 (+0.18%) |
| ETH   | 2.66340   |          — |  2,325.00  |     6,192.36 |               — |
```

- `Bought At` shows the actual price the bot paid. Shows `—` for coins held before the bot was started (buy price unknown).
- `Unrealised P&L` is the current gain or loss on the position. Only shown when buy price is known.
- A `positions.json` file is created automatically to remember buy prices across restarts.

Signal debug lines show exactly what drove each decision:
```
BTCUSDT | price=74012.00 | signal=buy | conf=0.87 | tech=+0.732 momentum=+0.000 news=+0.142 combined=+0.580 boosted=+0.870 aggr=1.5x
```

News sentiment table printed every hour:
```
| Coin | Final  |  Price | Mood     | Coin art |
| BTC  | +0.312 | -0.028 | positive |        8 |
| ETH  | +0.140 | +0.040 | neutral  |        1 |
  general market: 15 articles (score=-0.300) applied to all coins at 20% weight
```

---

## Safety tips

1. **Always run testnet for at least 2 weeks** before switching to live
2. **Start with small position sizes** (1–2%) when going live for the first time
3. **Never deposit more than you can afford to lose** on any exchange
4. **Restrict your Binance API key to your IP address** — do this in API Management settings
5. **Check `logs/bot.log` regularly** to understand every trade the bot makes
6. **Use `--sell-all` before shutting down** if you want a clean exit at market price
7. **Keep `MAX_POSITIONS` at 2–3** while you're still learning how the bot behaves
