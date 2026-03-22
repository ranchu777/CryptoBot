"""
strategy.py — Trading signal generators + combined decision engine.

Each strategy scores a DataFrame of OHLCV candles and returns a numeric
confidence value:
  +1.0  strong buy
   0.0  neutral / no signal
  -1.0  strong sell

get_combined_signal() blends the technical score with the news sentiment
score and applies the aggression multiplier from config to decide whether
to act, and how boldly.
"""

import pandas as pd
import numpy as np
import logging

logger = logging.getLogger("cryptobot")


class Strategy:
    def __init__(self, name: str, cfg):
        self.name = name
        self.cfg = cfg
        logger.info(f"Strategy loaded: {name.upper()} | aggression={cfg.AGGRESSION}")

    # ------------------------------------------------------------------ #
    #  Public — combined signal                                           #
    # ------------------------------------------------------------------ #

    def get_combined_signal(
        self,
        df: pd.DataFrame,
        news_score: float = 0.0,
        smart_money_score: float = 0.0,
    ) -> tuple[str | None, float, str]:
        """
        Blend technical analysis, news sentiment, and smart money positioning.
        Also applies trend filter and momentum detection.
        """
        tech_score     = self._get_technical_score(df)
        momentum_score = self._momentum_score(df)
        tech_w   = self.cfg.TECHNICAL_WEIGHT
        news_w   = self.cfg.NEWS_WEIGHT
        sm_w     = getattr(self.cfg, "SMART_MONEY_WEIGHT", 0.0)
        aggr     = self.cfg.AGGRESSION

        # Normalise weights in case smart money is disabled
        if sm_w == 0.0:
            # Redistribute smart money weight back to technical and news
            total = tech_w + news_w
            tech_w = tech_w / total
            news_w = news_w / total

        if abs(momentum_score) > abs(tech_score):
            blended_tech = (tech_score + momentum_score) / 2
        else:
            blended_tech = tech_score

        combined = (
            blended_tech      * tech_w +
            news_score        * news_w +
            smart_money_score * sm_w
        )
        combined_boosted = combined * aggr

        buy_threshold  = self.cfg.BUY_THRESHOLD  / aggr
        sell_threshold = self.cfg.SELL_THRESHOLD / aggr

        # ── Trend filter ───────────────────────────────────────────────
        trend_ok   = True
        trend_note = ""
        if getattr(self.cfg, "TREND_FILTER_ENABLED", True):
            period = getattr(self.cfg, "TREND_EMA_PERIOD", 200)
            if len(df) >= period:
                trend_ema  = df["close"].ewm(span=period, adjust=False).mean().iloc[-1]
                current    = df["close"].iloc[-1]
                trend_ok   = current >= trend_ema
                pct_from   = (current - trend_ema) / trend_ema * 100
                trend_note = f" trend_ema={trend_ema:.2f} ({pct_from:+.1f}%)"
            else:
                trend_note = " trend_ema=insufficient data"
        # ──────────────────────────────────────────────────────────────

        reason = (
            f"tech={tech_score:+.3f} momentum={momentum_score:+.3f} "
            f"news={news_score:+.3f} sm={smart_money_score:+.3f} "
            f"combined={combined:+.3f} boosted={combined_boosted:+.3f} aggr={aggr}x"
            f"{trend_note}"
        )

        confidence = min(1.0, abs(combined_boosted))

        if combined_boosted >= buy_threshold:
            if not trend_ok:
                return None, confidence, reason + " [TREND FILTER: buy blocked]"
            return "buy", confidence, reason
        if combined_boosted <= -sell_threshold:
            return "sell", confidence, reason
        return None, confidence, reason

    def get_signal(self, df: pd.DataFrame) -> str | None:
        """Legacy single-signal method — used internally and for backwards compat."""
        signal, _, _ = self.get_combined_signal(df, news_score=0.0)
        return signal

    def _momentum_score(self, df: pd.DataFrame) -> float:
        """
        Detects fast price moves that lagging indicators (EMA, MACD) miss.

        Looks at the last MOMENTUM_LOOKBACK candles and calculates the total
        % move from open to close. If the move exceeds MOMENTUM_CANDLE_PCT,
        returns a proportional score in the direction of the move.

        Example: 5% bullish candle → score ~+0.83 (capped at ±1.0)
        This catches 10% rallies even when the EMA score is near zero.
        """
        lookback = getattr(self.cfg, "MOMENTUM_LOOKBACK", 3)
        threshold = getattr(self.cfg, "MOMENTUM_CANDLE_PCT", 3.0) / 100

        recent = df.tail(lookback)
        start_price = recent["open"].iloc[0]
        end_price   = recent["close"].iloc[-1]

        if start_price <= 0:
            return 0.0

        pct_move = (end_price - start_price) / start_price

        if abs(pct_move) < threshold:
            return 0.0

        # Scale: threshold move = 0.5 score, 2x threshold = 1.0 (capped)
        score = pct_move / (threshold * 2)
        return float(np.clip(score, -1.0, 1.0))

    # ------------------------------------------------------------------ #
    #  Technical scoring — returns float -1.0 to +1.0                    #
    # ------------------------------------------------------------------ #

    def _get_technical_score(self, df: pd.DataFrame) -> float:
        if self.name == "ema":
            return self._ema_score(df)
        elif self.name == "rsi":
            return self._rsi_score(df)
        elif self.name == "bb":
            return self._bb_score(df)
        elif self.name == "macd":
            return self._macd_score(df)
        return 0.0

    # ------------------------------------------------------------------ #
    #  Strategy 1: EMA Crossover (scored)                                 #
    # ------------------------------------------------------------------ #
    def _ema_score(self, df: pd.DataFrame) -> float:
        fast = self.cfg.EMA_FAST
        slow = self.cfg.EMA_SLOW
        ema_fast = df["close"].ewm(span=fast, adjust=False).mean()
        ema_slow = df["close"].ewm(span=slow, adjust=False).mean()
        gap      = (ema_fast - ema_slow) / ema_slow

        curr_gap   = gap.iloc[-1]
        prev_gap   = gap.iloc[-2]
        cross_up   = prev_gap <= 0 < curr_gap
        cross_down = prev_gap >= 0 > curr_gap

        if cross_up:   return  1.0
        if cross_down: return -1.0
        return float(np.clip(curr_gap * 50, -1.0, 1.0))

    # ------------------------------------------------------------------ #
    #  Strategy 2: RSI (scored)                                           #
    # ------------------------------------------------------------------ #
    def _rsi_score(self, df: pd.DataFrame) -> float:
        """
        Maps RSI value to a -1.0 to +1.0 scale.
        RSI=30 → +1.0 (strong buy), RSI=70 → -1.0 (strong sell), RSI=50 → 0.
        """
        rsi = self._calc_rsi(df["close"], self.cfg.RSI_PERIOD).iloc[-1]
        if pd.isna(rsi):
            return 0.0
        # Linear mapping: 30→+1, 50→0, 70→-1
        score = (50 - rsi) / 20
        return float(np.clip(score, -1.0, 1.0))

    @staticmethod
    def _calc_rsi(prices: pd.Series, period: int) -> pd.Series:
        delta = prices.diff()
        gain = delta.clip(lower=0).rolling(period).mean()
        loss = (-delta.clip(upper=0)).rolling(period).mean()
        rs = gain / loss.replace(0, np.nan)
        return 100 - (100 / (1 + rs))

    # ------------------------------------------------------------------ #
    #  Strategy 3: Bollinger Bands (scored)                               #
    # ------------------------------------------------------------------ #
    def _bb_score(self, df: pd.DataFrame) -> float:
        close = df["close"]
        sma   = close.rolling(self.cfg.BB_PERIOD).mean()
        std   = close.rolling(self.cfg.BB_PERIOD).std()
        upper = sma + self.cfg.BB_STD * std

        price = close.iloc[-1]
        mid   = sma.iloc[-1]
        top   = upper.iloc[-1]

        if pd.isna(top) or top == mid:
            return 0.0
        return float(np.clip(-(price - mid) / (top - mid), -1.0, 1.0))

    # ------------------------------------------------------------------ #
    #  Strategy 4: MACD (scored) — with quality filters                   #
    # ------------------------------------------------------------------ #
    def _macd_score(self, df: pd.DataFrame) -> float:
        """
        MACD with four quality filters to reduce false signals:

        1. Minimum histogram size  — crossover must be large enough relative
                                     to recent volatility to be meaningful
        2. Confirmation candle     — histogram must still agree on the candle
                                     AFTER the crossover (not just the crossover itself)
        3. RSI alignment           — buy signals blocked if RSI is overbought (>65),
                                     sell signals blocked if RSI is oversold (<35)
        4. Volume confirmation     — signal strength scaled down on below-average volume
        """
        close    = df["close"]
        volume   = df["volume"]

        # ── Core MACD calculation ──────────────────────────────────────
        ema_fast = close.ewm(span=self.cfg.MACD_FAST, adjust=False).mean()
        ema_slow = close.ewm(span=self.cfg.MACD_SLOW, adjust=False).mean()
        macd     = ema_fast - ema_slow
        signal   = macd.ewm(span=self.cfg.MACD_SIGNAL, adjust=False).mean()
        hist     = macd - signal

        # Need at least 3 candles for confirmation logic
        if len(hist) < 3:
            return 0.0

        curr      = hist.iloc[-1]   # latest candle
        prev      = hist.iloc[-2]   # crossover candle
        pre_prev  = hist.iloc[-3]   # candle before crossover

        hist_std = hist.rolling(20).std().iloc[-1]
        if pd.isna(hist_std) or hist_std == 0:
            return 0.0

        # ── Filter 1: Minimum histogram size ──────────────────────────
        # Crossover must move at least MIN_HIST_STD_MULT standard deviations
        # to be considered a real signal — filters out noise crossovers
        min_hist = hist_std * getattr(self.cfg, "MACD_MIN_HIST_MULT", 0.5)
        crossover_size = abs(curr)
        if crossover_size < min_hist:
            return 0.0   # too small to be meaningful

        # ── Filter 2: Confirmation candle ─────────────────────────────
        # A valid buy crossover:  pre_prev < 0, prev crossed to >= 0, curr still >= 0
        # A valid sell crossover: pre_prev > 0, prev crossed to <= 0, curr still <= 0
        # If curr flipped back already, it was a false crossover — ignore it
        bullish_cross = pre_prev < 0 and prev >= 0 and curr > 0
        bearish_cross = pre_prev > 0 and prev <= 0 and curr < 0

        if not bullish_cross and not bearish_cross:
            # No confirmed crossover — fall back to trend-following score
            return float(np.clip(curr / hist_std, -1.0, 1.0))

        # ── Filter 3: RSI alignment ────────────────────────────────────
        rsi = self._calc_rsi(close, self.cfg.RSI_PERIOD).iloc[-1]
        rsi_overbought = getattr(self.cfg, "MACD_RSI_OVERBOUGHT", 65)
        rsi_oversold   = getattr(self.cfg, "MACD_RSI_OVERSOLD",   35)

        if bullish_cross and not pd.isna(rsi) and rsi > rsi_overbought:
            # MACD says buy but RSI says overbought — move already exhausted
            return 0.0
        if bearish_cross and not pd.isna(rsi) and rsi < rsi_oversold:
            # MACD says sell but RSI says oversold — likely bottomed out
            return 0.0

        # ── Filter 4: Volume confirmation ─────────────────────────────
        # Scale signal strength by how much above/below average volume is.
        # Above-average volume = conviction behind the move.
        # Below-average volume = drift, less reliable.
        vol_period = getattr(self.cfg, "MACD_VOL_PERIOD", 20)
        avg_vol    = volume.rolling(vol_period).mean().iloc[-1]
        curr_vol   = volume.iloc[-1]
        if pd.isna(avg_vol) or avg_vol == 0:
            vol_ratio = 1.0
        else:
            # Scale: 2x average volume → factor 1.2, 0.5x average → factor 0.7
            vol_ratio = float(np.clip(0.5 + (curr_vol / avg_vol) * 0.5, 0.5, 1.5))

        # ── Final score ────────────────────────────────────────────────
        base_score = 1.0 if bullish_cross else -1.0
        return float(np.clip(base_score * vol_ratio, -1.0, 1.0))
