"""
market_filters.py — Market condition filters and supplementary signals.

Provides five independent signals/filters that run each cycle:

1. Fear & Greed Index  — alternative.me, free, no key
   Score 0-100: <20 extreme fear (buy), >80 extreme greed (sell)
   Converted to -1.0..+1.0 contribution to combined signal

2. Funding Rate        — Binance Futures public API, no key
   Positive funding = longs pay shorts = market overextended long → caution
   Negative funding = shorts pay longs = market oversold → potential bounce

3. Open Interest       — Binance Futures public API, no key
   Rising OI + rising price = trend confirmation (boost signal)
   Rising OI + falling price = distribution (warn against buying)
   Falling OI = trend weakening (reduce confidence)

4. Volatility filter   — computed from candle data (ATR)
   Extreme ATR spike = erratic market = reduce position size / skip trades

5. BTC Correlation filter — computed from candle data
   If BTC drops sharply this cycle, suppress ALT buys regardless of signal
"""

import time
import logging
import requests
import numpy as np
from futures_client import BinanceFuturesClient

logger = logging.getLogger("cryptobot")

_FUTURES_URL  = "https://fapi.binance.com"
_FNG_URL      = "https://api.alternative.me/fng/?limit=1"

_FUTURES_SYMBOLS = {
    "BTC":  "BTCUSDT",
    "ETH":  "ETHUSDT",
    "SOL":  "SOLUSDT",
    "BNB":  "BNBUSDT",
    "DOGE": "DOGEUSDT",
}


class MarketFilters:
    def __init__(self, cfg):
        self.cfg     = cfg
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": "CryptoBot/1.0"})
        self.futures_client = BinanceFuturesClient()

        # Per-signal caches
        self._fng_cache        = None   # (score, timestamp)
        self._funding_cache    = {}     # coin -> (rate, timestamp)
        self._oi_cache         = {}     # coin -> (oi, timestamp)
        self._fng_ttl          = getattr(cfg, "FNG_CACHE_TTL", 3600)       # 1 hour
        self._funding_ttl      = getattr(cfg, "FUNDING_CACHE_TTL", 900)    # 15 min
        self._oi_ttl           = getattr(cfg, "OI_CACHE_TTL", 300)         # 5 min

    # ------------------------------------------------------------------ #
    #  1. Fear & Greed Index                                               #
    # ------------------------------------------------------------------ #

    def get_fear_greed_score(self) -> float:
        """
        Returns -1.0..+1.0 from the Crypto Fear & Greed Index.
        <20 extreme fear → +0.8 (contrarian buy signal)
        >80 extreme greed → -0.8 (contrarian sell signal)
        50 neutral → 0.0
        """
        if not getattr(self.cfg, "FNG_ENABLED", True):
            return 0.0

        now = time.time()
        if self._fng_cache and (now - self._fng_cache[1]) < self._fng_ttl:
            return self._fng_cache[0]

        try:
            r = self.session.get(_FNG_URL, timeout=8)
            r.raise_for_status()
            value = int(r.json()["data"][0]["value"])
            # Map 0-100 to -1..+1, inverted (fear = buy, greed = sell)
            # 0=extreme fear→+1, 50=neutral→0, 100=extreme greed→-1
            score = round((50 - value) / 50, 4)
            score = max(-1.0, min(1.0, score))
            self._fng_cache = (score, now)
            logger.info(f"Fear&Greed: index={value} → score={score:+.3f}")
            return score
        except Exception as e:
            logger.debug(f"Fear&Greed: fetch failed — {e}")
            return self._fng_cache[0] if self._fng_cache else 0.0

    # ------------------------------------------------------------------ #
    #  2. Funding Rate                                                     #
    # ------------------------------------------------------------------ #

    def get_funding_scores(self) -> dict:
        """
        Returns funding rate scores per coin (-1.0..+1.0).
        High positive funding (longs paying) → bearish (overextended)
        High negative funding (shorts paying) → bullish (oversold)
        """
        if not getattr(self.cfg, "FUNDING_ENABLED", True):
            return {coin: 0.0 for coin in _FUTURES_SYMBOLS}

        now    = time.time()
        scores = {}

        for coin, symbol in _FUTURES_SYMBOLS.items():
            cached = self._funding_cache.get(coin)
            if cached and (now - cached[1]) < self._funding_ttl:
                scores[coin] = cached[0]
                continue

            funding_rate = self.futures_client.get_funding_rate(symbol)
            if funding_rate is not None:
                # Typical range: -0.01% to +0.1% per 8 hours
                # Scale: 0.01% (0.0001) → full score ±1.0
                score = round(max(-1.0, min(1.0, -funding_rate / 0.0001)), 4)
                self._funding_cache[coin] = (score, now)
                scores[coin] = score
                logger.debug(f"Funding {coin}: rate={funding_rate:.5f} → score={score:+.3f}")
            else:
                logger.debug(f"Funding {coin}: failed")
                scores[coin] = self._funding_cache.get(coin, (0.0,))[0]

        return scores

    # ------------------------------------------------------------------ #
    #  3. Open Interest                                                    #
    # ------------------------------------------------------------------ #

    def get_oi_scores(self, current_prices: dict) -> dict:
        """
        Returns open interest trend scores per coin (-1.0..+1.0).
        Rising OI + rising price = trend confirmed → boost
        Rising OI + falling price = distribution → warn
        Falling OI = trend weakening → neutral/slight negative
        """
        if not getattr(self.cfg, "OI_ENABLED", True):
            return {coin: 0.0 for coin in _FUTURES_SYMBOLS}

        now    = time.time()
        scores = {}

        for coin, symbol in _FUTURES_SYMBOLS.items():
            data = self.futures_client.get_open_interest_hist(symbol, "5m", 3)
            if not data or len(data) < 2:
                scores[coin] = 0.0
                continue

            oi_old = float(data[0]["sumOpenInterest"])
            oi_new = float(data[-1]["sumOpenInterest"])
            oi_chg = (oi_new - oi_old) / oi_old if oi_old > 0 else 0

            price = current_prices.get(coin, 0)
            cached_price = self._oi_cache.get(coin, {}).get("price", price)
            price_chg    = (price - cached_price) / cached_price if cached_price > 0 else 0

            # Rising OI + rising price = bullish confirmation
            # Rising OI + falling price = bearish divergence
            if oi_chg > 0.002:       # OI up meaningfully
                score = 0.6 if price_chg >= 0 else -0.6
            elif oi_chg < -0.002:    # OI falling = weakening trend
                score = -0.2
            else:
                score = 0.0

            self._oi_cache[coin] = {"score": score, "price": price, "ts": now}
            scores[coin] = score
            logger.debug(f"OI {coin}: oi_chg={oi_chg:+.4f} price_chg={price_chg:+.4f} → {score:+.2f}")

        return scores

    # ------------------------------------------------------------------ #
    #  4. Volatility filter (ATR-based)                                    #
    # ------------------------------------------------------------------ #

    def get_volatility_multiplier(self, df) -> float:
        """
        Returns a position size multiplier based on current volatility.
        Normal volatility  → 1.0 (no change)
        High volatility    → 0.5 (halve position size)
        Extreme volatility → 0.0 (skip trade entirely)

        Uses ATR(14) normalised by price. If ATR/price > threshold, reduce size.
        """
        if not getattr(self.cfg, "VOLATILITY_FILTER_ENABLED", True):
            return 1.0

        try:
            high  = df["high"]
            low   = df["low"]
            close = df["close"]

            prev_close = close.shift(1)
            tr = np.maximum(
                high - low,
                np.maximum(abs(high - prev_close), abs(low - prev_close))
            )
            atr    = tr.rolling(14).mean().iloc[-1]
            price  = close.iloc[-1]
            atr_pct = atr / price

            normal_threshold  = getattr(self.cfg, "VOL_NORMAL_THRESHOLD", 0.015)   # 1.5%
            high_threshold    = getattr(self.cfg, "VOL_HIGH_THRESHOLD",   0.030)   # 3.0%
            extreme_threshold = getattr(self.cfg, "VOL_EXTREME_THRESHOLD", 0.050)  # 5.0%

            if atr_pct >= extreme_threshold:
                logger.info(f"Volatility EXTREME (ATR={atr_pct:.2%}) — skipping trade")
                return 0.0
            elif atr_pct >= high_threshold:
                logger.debug(f"Volatility HIGH (ATR={atr_pct:.2%}) — reducing size 50%")
                return 0.5
            elif atr_pct >= normal_threshold:
                # Linear interpolation between 1.0 and 0.5
                ratio = (atr_pct - normal_threshold) / (high_threshold - normal_threshold)
                return round(1.0 - (ratio * 0.5), 2)
            return 1.0
        except Exception:
            return 1.0

    # ------------------------------------------------------------------ #
    #  5. BTC Correlation filter                                           #
    # ------------------------------------------------------------------ #

    def check_btc_correlation(self, btc_candles, pair: str) -> bool:
        """
        Returns True if it's safe to buy the given pair.
        Returns False if BTC is dropping sharply — suppress ALT buys.

        Uses BTC's last N candles to detect a sharp decline.
        If BTC dropped more than BTC_DROP_BLOCK_PCT in the last candle,
        block buys on all ALTs.
        """
        if not getattr(self.cfg, "BTC_CORRELATION_FILTER", True):
            return True
        if pair == "BTCUSDT":
            return True   # BTC always evaluates itself
        if btc_candles is None or len(btc_candles) < 3:
            return True

        try:
            threshold = getattr(self.cfg, "BTC_DROP_BLOCK_PCT", 2.0) / 100
            close     = btc_candles["close"]
            # Check last 2 candles for a sharp BTC drop
            recent_drop = (close.iloc[-1] - close.iloc[-3]) / close.iloc[-3]
            if recent_drop <= -threshold:
                logger.info(
                    f"{pair}: BUY blocked — BTC dropped {recent_drop:.1%} "
                    f"in last 2 candles (threshold -{threshold:.1%})"
                )
                return False
            return True
        except Exception:
            return True

    # ------------------------------------------------------------------ #
    #  Logging                                                             #
    # ------------------------------------------------------------------ #

    def log_market_conditions(self, fng: float, funding: dict, oi: dict):
        """Print a compact market conditions table."""
        coins = list(_FUTURES_SYMBOLS.keys())
        logger.info(f"Market conditions | Fear&Greed={fng:+.3f}")
        logger.info(f"  {'Coin':<6} {'Funding':>9} {'OI':>8}")
        logger.info(f"  {'------':<6} {'---------':>9} {'--------':>8}")
        for coin in coins:
            f = funding.get(coin, 0.0)
            o = oi.get(coin, 0.0)
            logger.info(f"  {coin:<6} {f:>+9.3f} {o:>+8.3f}")
