"""
config.py — All settings in one place.
Edit these values to tune your bot's behaviour.
"""

import os
from dotenv import load_dotenv

load_dotenv()  # reads from .env file


class Config:
    def __init__(self, testnet: bool = True):
        self.TESTNET = testnet

        # --- API Keys (loaded from .env) ---
        if testnet:
            self.API_KEY    = os.getenv("BINANCE_TESTNET_KEY", "")
            self.API_SECRET = os.getenv("BINANCE_TESTNET_SECRET", "")
            self.BASE_URL   = "https://testnet.binance.vision"
        else:
            self.API_KEY    = os.getenv("BINANCE_LIVE_KEY", "")
            self.API_SECRET = os.getenv("BINANCE_LIVE_SECRET", "")
            self.BASE_URL   = "https://api.binance.com"

        # --- Strategy parameters ---
        # EMA Crossover
        self.EMA_FAST   = 9
        self.EMA_SLOW   = 21

        # RSI
        self.RSI_PERIOD   = 14
        self.RSI_OVERSOLD = 30
        self.RSI_OVERBOUGHT = 70

        # Bollinger Bands
        self.BB_PERIOD = 20
        self.BB_STD    = 2.0

        # MACD
        self.MACD_FAST   = 12
        self.MACD_SLOW   = 26
        self.MACD_SIGNAL = 9

        # MACD quality filters — reduce false signals on short timeframes
        # Minimum histogram size as a multiple of its 20-candle std dev
        # Higher = fewer but stronger signals (0.3 = loose, 0.8 = strict)
        self.MACD_MIN_HIST_MULT  = 0.5
        # RSI thresholds for MACD alignment filter
        self.MACD_RSI_OVERBOUGHT = 65   # block MACD buys above this RSI
        self.MACD_RSI_OVERSOLD   = 35   # block MACD sells below this RSI
        # Volume lookback for volume confirmation filter
        self.MACD_VOL_PERIOD     = 20

        # --- Risk management ---
        # % of available balance to use per trade (scaled by confidence when bold)
        self.POSITION_SIZE_PCT = 5.0      # base % per trade

        # Stop loss / take profit as % of entry price
        self.STOP_LOSS_PCT    = 3.0   # exit if price drops 3%
        self.TAKE_PROFIT_PCT  = 8.0   # exit if price rises 8%

        # --- Trailing stop loss ---
        # Once price gains TRAILING_STOP_ACTIVATION_PCT above entry, the stop loss
        # switches to trailing mode — fixed stop is replaced entirely.
        self.TRAILING_STOP_ENABLED        = True
        self.TRAILING_STOP_ACTIVATION_PCT = 1.0   # trailing activates after +1% gain
        self.TRAILING_STOP_REPLACE_FIXED  = True   # replace fixed stop once trailing is active

        # Max open positions at once
        self.MAX_POSITIONS = 6

        # Min USDT to keep in reserve (don't trade it all)
        self.MIN_RESERVE_USDT = 500.0

        # --- Trend filter (downtrend protection) ---
        # Only allow new BUY orders when price is above the trend EMA.
        # Prevents buying into a sustained downtrend (e.g. -10% day).
        # Set TREND_FILTER_ENABLED = False to disable.
        self.TREND_FILTER_ENABLED = True
        self.TREND_EMA_PERIOD     = 200   # 200-candle EMA — standard trend indicator

        # --- Daily drawdown circuit breaker ---
        # If session losses exceed this % of starting balance, stop opening
        # new positions for the rest of the session. Exits are still allowed.
        self.DRAWDOWN_CIRCUIT_BREAKER    = True
        self.MAX_DRAWDOWN_PCT            = 5.0   # halt new buys after 5% session loss

        # --- Aggression & signal blending ---
        self.AGGRESSION = 1.5

        # Weight of each signal source — must sum to 1.0
        # Smart money now carries significant weight given two strong sources
        self.TECHNICAL_WEIGHT   = 0.40
        self.NEWS_WEIGHT        = 0.25
        self.SMART_MONEY_WEIGHT = 0.35   # 35% — top trader L/S ratio + leaderboard

        # Combined (boosted) score thresholds to trigger a trade
        self.BUY_THRESHOLD  = 0.25
        self.SELL_THRESHOLD = 0.25

        # --- Smart money (top trader long/short ratio) ---
        self.SMART_MONEY_ENABLED   = True
        self.SMART_MONEY_CACHE_TTL = 900   # 15 minutes
        # Weight split within the smart money signal
        # Leaderboard is disabled by default — Binance blocks direct API access to it.
        # The L/S ratio uses the official public Futures API and works reliably.
        self.LS_RATIO_WEIGHT       = 1.0   # 100% from long/short ratio
        self.LEADERBOARD_WEIGHT    = 0.0   # disabled

        # --- Leaderboard tracker ---
        # NOTE: Binance does not expose leaderboard data through a public API.
        # The internal endpoint is blocked for programmatic access.
        # Set to True only if you are routing through a proxy that can access it.
        self.LEADERBOARD_ENABLED   = False
        self.LEADERBOARD_TOP_N     = 10
        self.LEADERBOARD_CACHE_TTL = 1800

        # --- Pyramiding (position scaling) ---
        # Allow adding to a winning position when signal confidence stays high.
        self.PYRAMID_ENABLED       = True
        self.PYRAMID_MAX_ADDONS    = 1      # max 1 add-on (2 total: 1 entry + 1 add-on)
        self.PYRAMID_MIN_GAIN_PCT  = 0.0    # no price gain required — confidence only
        self.PYRAMID_MIN_CONFIDENCE = 0.70  # 70% confidence required
        self.PYRAMID_ADDON_SIZE_PCT = 0.25  # add-on is 25% of original position size
        # If price moves more than this % in a single candle, treat it as
        # a strong momentum signal and bypass the normal threshold.
        # Catches fast 5-10% moves the EMA/RSI would otherwise lag behind.
        self.MOMENTUM_CANDLE_PCT = 3.0   # 3% single-candle move triggers momentum buy
        self.MOMENTUM_LOOKBACK   = 3     # check last N candles for the move

        # When news sentiment is this strongly bearish, block all buys
        # regardless of technical signal (circuit breaker)
        self.NEWS_BLOCK_BUY_BELOW  = -0.6
        # When news is this strongly bullish, block all sells
        self.NEWS_BLOCK_SELL_ABOVE =  0.6

        # Scale position size up/down based on signal confidence
        # e.g. 90% confidence trade at aggression 1.5 → 5% * 1.5 * 0.9 = 6.75%
        self.SCALE_SIZE_WITH_CONFIDENCE = True

        # --- News sentiment ---
        # Free CryptoPanic key (optional — raises rate limit from 5/min to 50/min)
        # Get one at: https://cryptopanic.com/developers/api/
        self.CRYPTOPANIC_KEY = os.getenv("CRYPTOPANIC_KEY", "")

        # FreeCryptoAPI key — used for 24h price change sentiment signal
        # Get one at: https://freecryptoapi.com/panel
        # Authentication: Bearer token in Authorization header
        self.FREECRYPTOAPI_KEY = os.getenv("FREECRYPTOAPI_KEY", "")

        # Weight of FreeCryptoAPI price signal vs text-based news (0.0 to 1.0)
        # 0.5 = equal weight between price momentum and headline sentiment
        self.FREECRYPTOAPI_WEIGHT = 0.5   # 50% price, 50% text

        # Weight of general market articles (not coin-specific) in each coin's score
        # e.g. 0.2 = 20% of the text portion comes from general regulatory/market news
        self.MARKET_SENTIMENT_WEIGHT = 0.2

        # How long to cache news scores before re-fetching (seconds)
        # 3600 = fetch news once per hour regardless of candle timeframe
        self.NEWS_CACHE_TTL = 3600

        # --- Pairs ---
        self.DEFAULT_PAIRS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "DOGEUSDT"]

        # Minimum order sizes on Binance (USDT notional)
        self.MIN_ORDER_USDT = {
            "BTCUSDT":  1000,
            "ETHUSDT":  1000,
            "SOLUSDT":  500,
            "BNBUSDT":  500,
            "DOGEUSDT": 500,
        }
