"""
config.py — All settings in one place.
Edit these values to tune your bot's behaviour.
"""

import os
import sys
from dotenv import load_dotenv

load_dotenv()  # reads from .env file


class ConfigValidationError(Exception):
    """Raised when configuration parameters are invalid."""
    pass


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
        self.RSI_OVERSOLD = 33
        self.RSI_OVERBOUGHT = 68

        # Bollinger Bands
        self.BB_PERIOD = 20
        self.BB_STD    = 2.0
        # BB_OFFSET shifts bands inward (positive) or outward (negative).
        # 0.0  = standard bands at ±2σ (default)
        # 0.5  = bands at ±1.5σ — more signals, price reaches bands more often
        # 1.0  = bands at ±1σ  — very sensitive, use with low aggression
        # -0.5 = bands at ±2.5σ — fewer but stronger signals
        self.BB_OFFSET = -3.0

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
        self.STOP_LOSS_PCT    = 2.0   # exit if price drops 3%
        self.TAKE_PROFIT_PCT  = 4.0   # exit if price rises 8%

        # --- Trailing stop loss ---
        # Once price gains TRAILING_STOP_ACTIVATION_PCT above entry, the stop loss
        # switches to trailing mode — fixed stop is replaced entirely.
        self.TRAILING_STOP_ENABLED        = True
        self.TRAILING_STOP_ACTIVATION_PCT = 2.0   # trailing activates after +1% gain
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

        # --- Fear & Greed Index ---
        self.FNG_ENABLED   = True
        self.FNG_CACHE_TTL = 3600    # update once per hour
        self.FNG_WEIGHT    = 0.10    # contribution to combined signal

        # --- Funding Rate ---
        self.FUNDING_ENABLED   = True
        self.FUNDING_CACHE_TTL = 900   # 15 min
        self.FUNDING_WEIGHT    = 0.05

        # --- Open Interest ---
        self.OI_ENABLED   = True
        self.OI_CACHE_TTL = 300      # 5 min

        # --- Volatility filter (ATR-based) ---
        self.VOLATILITY_FILTER_ENABLED = True
        self.VOL_NORMAL_THRESHOLD      = 0.015   # ATR/price > 1.5% = reduced size
        self.VOL_HIGH_THRESHOLD        = 0.030   # ATR/price > 3.0% = half size
        self.VOL_EXTREME_THRESHOLD     = 0.050   # ATR/price > 5.0% = skip trade

        # --- BTC Correlation filter ---
        self.BTC_CORRELATION_FILTER = True
        self.BTC_DROP_BLOCK_PCT     = 2.0   # block ALT buys if BTC drops 2% in 2 candles

        # --- Multi-timeframe confirmation ---
        self.MTF_ENABLED         = True
        self.MTF_AGREE_THRESHOLD = 0.2   # 1h score must be > 0.2 for full buy confidence

        # --- Aggression & signal blending ---
        self.AGGRESSION = 1.0

        # Weight of each signal source — must sum to 1.0
        self.TECHNICAL_WEIGHT   = 0.28
        self.NEWS_WEIGHT        = 0.20
        self.SMART_MONEY_WEIGHT = 0.20
        self.CALENDAR_WEIGHT    = 0.10
        self.FNG_WEIGHT         = 0.10
        self.FUNDING_WEIGHT     = 0.07
        self.ORB_WEIGHT = 0.05

        # --- Opening Range Breakout (ORB) ---
        self.ORB_ENABLED          = True
        self.ORB_RETEST_CANDLES   = 6      # 30 min retest window (6 x 5m candles)
        self.ORB_RANGE_WINDOW_MINS = 10    # capture range in first 10 min of UTC day
        self.ORB_RR_RATIO         = 2.0   # 2:1 risk-to-reward target

        # Combined (boosted) score thresholds to trigger a trade
        self.BUY_THRESHOLD  = 0.25
        self.SELL_THRESHOLD = 0.25

        # --- Economic calendar (ForexFactory) ---
        # Fetches this week's economic events from ForexFactory (free, no key needed).
        # The calendar only updates once per week so 6 hours is plenty.
        # Rate limit: ForexFactory allows ~2 requests per 5 minutes max.
        self.CALENDAR_ENABLED     = True
        self.CALENDAR_CACHE_TTL   = 21600  # fetch once every 6 hours
        self.CALENDAR_WINDOW_MINS = 120    # consider events within ±2 hours
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
        # Binance requires ~$5 minimum per order — these are set conservatively higher
        # to avoid partial fills and dust, but low enough to work with small accounts
        self.MIN_ORDER_USDT = {
            "BTCUSDT":  1000,
            "ETHUSDT":  1000,
            "SOLUSDT":  150,
            "BNBUSDT":  150,
            "DOGEUSDT": 150,
        }

        # Validate configuration
        self._validate()

    def _validate(self):
        """Validate that all configuration parameters are in reasonable ranges."""
        errors = []

        # --- API Key validation ---
        if not self.API_KEY or not self.API_KEY.strip():
            errors.append(
                f"API_KEY is empty. Set BINANCE_{'TESTNET_' if self.TESTNET else 'LIVE_'}KEY "
                f"in your .env file and re-run."
            )
        if not self.API_SECRET or not self.API_SECRET.strip():
            errors.append(
                f"API_SECRET is empty. Set BINANCE_{'TESTNET_' if self.TESTNET else 'LIVE_'}SECRET "
                f"in your .env file and re-run."
            )

        # --- Risk parameters ---
        if self.STOP_LOSS_PCT <= 0 or self.STOP_LOSS_PCT > 50:
            errors.append(f"STOP_LOSS_PCT must be 0 < x <= 50, got {self.STOP_LOSS_PCT}")
        if self.TAKE_PROFIT_PCT <= 0 or self.TAKE_PROFIT_PCT > 100:
            errors.append(f"TAKE_PROFIT_PCT must be 0 < x <= 100, got {self.TAKE_PROFIT_PCT}")
        if self.POSITION_SIZE_PCT <= 0 or self.POSITION_SIZE_PCT > 25:
            errors.append(f"POSITION_SIZE_PCT must be 0 < x <= 25, got {self.POSITION_SIZE_PCT}")
        if self.MAX_POSITIONS < 1 or self.MAX_POSITIONS > 20:
            errors.append(f"MAX_POSITIONS must be 1 <= x <= 20, got {self.MAX_POSITIONS}")
        if self.MIN_RESERVE_USDT < 0:
            errors.append(f"MIN_RESERVE_USDT must be >= 0, got {self.MIN_RESERVE_USDT}")
        if self.AGGRESSION <= 0 or self.AGGRESSION > 5:
            errors.append(f"AGGRESSION must be 0 < x <= 5, got {self.AGGRESSION}")

        # --- Signal thresholds ---
        if self.BUY_THRESHOLD <= 0 or self.BUY_THRESHOLD > 1:
            errors.append(f"BUY_THRESHOLD must be 0 < x <= 1, got {self.BUY_THRESHOLD}")
        if self.SELL_THRESHOLD <= 0 or self.SELL_THRESHOLD > 1:
            errors.append(f"SELL_THRESHOLD must be 0 < x <= 1, got {self.SELL_THRESHOLD}")

        # --- Weight validation (should sum to ~1.0, allow ±0.05 tolerance) ---
        total_weight = (
            self.TECHNICAL_WEIGHT + self.NEWS_WEIGHT + self.SMART_MONEY_WEIGHT +
            self.CALENDAR_WEIGHT + self.FNG_WEIGHT + self.FUNDING_WEIGHT + self.ORB_WEIGHT
        )
        if abs(total_weight - 1.0) > 0.05:
            errors.append(
                f"Signal weights must sum to ~1.0 (±0.05 tolerance), got {total_weight:.2f}. "
                f"Check TECHNICAL_WEIGHT, NEWS_WEIGHT, etc."
            )
        if any(w < 0 or w > 1 for w in [
            self.TECHNICAL_WEIGHT, self.NEWS_WEIGHT, self.SMART_MONEY_WEIGHT,
            self.CALENDAR_WEIGHT, self.FNG_WEIGHT, self.FUNDING_WEIGHT, self.ORB_WEIGHT
        ]):
            errors.append("All signal weights must be 0.0 <= x <= 1.0")

        # --- Trend filter ---
        if self.TREND_EMA_PERIOD < 20:
            errors.append(f"TREND_EMA_PERIOD should be >= 20, got {self.TREND_EMA_PERIOD}")

        # --- Drawdown circuit breaker ---
        if self.MAX_DRAWDOWN_PCT <= 0 or self.MAX_DRAWDOWN_PCT > 50:
            errors.append(f"MAX_DRAWDOWN_PCT must be 0 < x <= 50, got {self.MAX_DRAWDOWN_PCT}")

        # --- Trailing stop ---
        if self.TRAILING_STOP_ACTIVATION_PCT < 0 or self.TRAILING_STOP_ACTIVATION_PCT > 10:
            errors.append(
                f"TRAILING_STOP_ACTIVATION_PCT must be 0 <= x <= 10, got {self.TRAILING_STOP_ACTIVATION_PCT}"
            )

        # --- Volatility thresholds ---
        if self.VOL_NORMAL_THRESHOLD <= 0 or self.VOL_NORMAL_THRESHOLD >= self.VOL_HIGH_THRESHOLD:
            errors.append("VOL_NORMAL_THRESHOLD must be > 0 and < VOL_HIGH_THRESHOLD")
        if self.VOL_HIGH_THRESHOLD >= self.VOL_EXTREME_THRESHOLD:
            errors.append("VOL_HIGH_THRESHOLD must be < VOL_EXTREME_THRESHOLD")

        if errors:
            print("=" * 70, file=sys.stderr)
            print("CONFIGURATION ERROR", file=sys.stderr)
            print("=" * 70, file=sys.stderr)
            for i, err in enumerate(errors, 1):
                print(f"{i}. {err}", file=sys.stderr)
            print("=" * 70, file=sys.stderr)
            raise ConfigValidationError(f"{len(errors)} configuration error(s) found — see above")

