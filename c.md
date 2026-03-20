# CryptoBot — Binance Algo Trader

A clean, beginner-friendly algorithmic trading bot for Binance.
Supports testnet (paper trading) and live trading.

---

## Quick Start (5 steps)

### 1. Install Python
Download Python 3.11+ from https://python.org if you don't have it.

### 2. Install dependencies
Open a terminal in this folder and run:
```
pip install -r requirements.txt
```

### 3. Set up API keys
Copy the example env file:
```
cp .env.example .env
```
Then open `.env` in a text editor and fill in your keys.

**For testnet (paper trading — START HERE):**
- Go to https://testnet.binance.vision
- Log in with your GitHub account
- Click "Generate HMAC_SHA256 Key"
- Copy the API Key and Secret into `.env`

**For live trading (real money — do this later):**
- Go to https://www.binance.com → Profile → API Management
- Create a new API key
- Enable: "Enable Reading" and "Enable Spot & Margin Trading"
- Restrict access to your IP address
- Copy into `.env`

### 4. Run the bot (testnet mode — default)
```
python bot.py
```

Or pick a specific strategy:
```
python bot.py --strategy rsi
python bot.py --strategy bb --timeframe 15m
python bot.py --strategy macd --pairs BTCUSDT ETHUSDT
```

### 5. Go live (when you're confident)
```
python bot.py --live
```
You'll be prompted to confirm before it starts.

---

## Strategies

| Name | Flag | Description |
|------|------|-------------|
| EMA Crossover | `--strategy ema` | Buys golden cross, sells death cross |
| RSI Reversal | `--strategy rsi` | Buys oversold bounces |
| Bollinger Bands | `--strategy bb` | Buys lower band, sells upper band |
| MACD | `--strategy macd` | Trades MACD/signal line crossovers |

---

## Tuning the bot

All settings are in `config.py`. Key ones:

| Setting | Default | What it does |
|---------|---------|-------------|
| `POSITION_SIZE_PCT` | 5% | How much of your balance per trade |
| `STOP_LOSS_PCT` | 2% | Exits if price drops this much |
| `TAKE_PROFIT_PCT` | 4% | Exits if price rises this much |
| `MAX_POSITIONS` | 2 | Max open trades at once |
| `EMA_FAST / EMA_SLOW` | 9 / 21 | EMA strategy sensitivity |

---

## File structure

```
cryptobot/
├── bot.py          # Main entry point — run this
├── config.py       # All settings
├── exchange.py     # Binance API connection
├── strategy.py     # Trading signal logic
├── risk.py         # Position sizing, stop loss
├── logger.py       # Logging setup
├── requirements.txt
├── .env.example    # Copy to .env and fill in keys
└── logs/
    └── bot.log     # Full log with every decision
```

---

## Safety tips

1. Always run testnet for at least 2 weeks before going live
2. Start with small position sizes (1–2%) when going live
3. Never put more money on the exchange than you can afford to lose
4. Keep `MAX_POSITIONS` low (1–2) while learning
5. Check `logs/bot.log` to understand every decision the bot makes
6. Restrict your API key to your IP address on Binance
