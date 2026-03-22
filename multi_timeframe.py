"""
multi_timeframe.py — Higher timeframe signal confirmation.

Before acting on a 5m signal, checks that the 1h timeframe agrees.
Prevents buying into short-term bounces within a larger downtrend.

Rules:
  - BUY  signal on 5m: only proceed if 1h signal is neutral or bullish
  - SELL signal on 5m: only proceed if 1h signal is neutral or bearish
  - If timeframes disagree strongly, confidence is reduced

The 1h candles are fetched separately and cached for 60 minutes.
"""

import time
import logging

logger = logging.getLogger("cryptobot")


class MultiTimeframe:
    def __init__(self, cfg, client, strategy):
        self.cfg      = cfg
        self.client   = client
        self.strategy = strategy
        self._cache   = {}   # pair -> (score, timestamp)
        self._ttl     = 3600  # re-fetch 1h candles every 60 min

    def get_htf_score(self, pair: str) -> float:
        """
        Returns the 1h timeframe signal score for a pair (-1.0..+1.0).
        Positive = higher timeframe is bullish, negative = bearish.
        Cached for 60 minutes.
        """
        if not getattr(self.cfg, "MTF_ENABLED", True):
            return 0.0

        now    = time.time()
        cached = self._cache.get(pair)
        if cached and (now - cached[1]) < self._ttl:
            return cached[0]

        try:
            candles_1h = self.client.get_candles(pair, "1h", limit=100)
            if candles_1h is None or len(candles_1h) < 30:
                return 0.0

            # Get raw technical score on 1h candles (no news/sm/cal — pure price)
            tech_score = self.strategy._get_technical_score(candles_1h)
            self._cache[pair] = (tech_score, now)
            logger.debug(f"MTF {pair} 1h score: {tech_score:+.3f}")
            return tech_score
        except Exception as e:
            logger.debug(f"MTF {pair}: failed — {e}")
            return 0.0

    def check_alignment(self, pair: str, signal: str, confidence: float) -> tuple[bool, float]:
        """
        Check if the 5m signal aligns with the 1h trend.
        Returns (allow_trade, adjusted_confidence).

        - Full alignment:    confidence unchanged
        - Partial agreement: confidence reduced by 20%
        - Disagreement:      trade blocked
        """
        htf = self.get_htf_score(pair)
        threshold = getattr(self.cfg, "MTF_AGREE_THRESHOLD", 0.2)

        if signal == "buy":
            if htf >= threshold:
                return True, confidence                       # 1h bullish — full go
            elif htf >= -threshold:
                return True, round(confidence * 0.8, 4)      # 1h neutral — proceed cautiously
            else:
                logger.info(f"{pair}: BUY blocked by MTF — 1h score={htf:+.3f} (bearish)")
                return False, confidence                      # 1h bearish — block

        elif signal == "sell":
            if htf <= -threshold:
                return True, confidence                       # 1h bearish — full go
            elif htf <= threshold:
                return True, round(confidence * 0.8, 4)      # 1h neutral — proceed cautiously
            else:
                logger.info(f"{pair}: SELL blocked by MTF — 1h score={htf:+.3f} (bullish)")
                return False, confidence                      # 1h bullish — block

        return True, confidence
