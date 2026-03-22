"""
smart_money.py — Binance top trader sentiment tracker.

Fetches the long/short position ratio of Binance's top traders (top 20% by PnL)
for each coin and converts it into a -1.0 to +1.0 sentiment score.

How it works:
  - Binance publishes the ratio of top traders holding long vs short positions
  - A ratio > 1.0 means more top traders are long than short (bullish signal)
  - A ratio < 1.0 means more top traders are short than long (bearish signal)
  - We fetch this every SMART_MONEY_CACHE_TTL seconds (default 15 min)

Endpoints used (no API key required — public data):
  GET /futures/data/topLongShortPositionRatio   — top trader position ratio
  GET /futures/data/globalLongShortAccountRatio — all traders ratio (as secondary)

Score formula:
  ratio = long_account_pct / short_account_pct
  score = clip((ratio - 1.0) * 2, -1.0, +1.0)

  ratio 2.0 (twice as many longs) → score +1.0 (strongly bullish)
  ratio 1.0 (equal)               → score  0.0 (neutral)
  ratio 0.5 (twice as many shorts) → score -1.0 (strongly bearish)

Usage:
    from smart_money import SmartMoneyTracker
    sm = SmartMoneyTracker(cfg)
    scores = sm.get_scores()  # {"BTC": +0.42, "ETH": -0.15, ...}
"""

import time
import logging
import requests

logger = logging.getLogger("cryptobot")

# Futures base URL — always public, no auth needed
_FUTURES_URL = "https://fapi.binance.com"

# Map spot symbols to futures contract symbols
_FUTURES_SYMBOLS = {
    "BTC":  "BTCUSDT",
    "ETH":  "ETHUSDT",
    "SOL":  "SOLUSDT",
    "BNB":  "BNBUSDT",
    "DOGE": "DOGEUSDT",
}


class SmartMoneyTracker:
    def __init__(self, cfg):
        self.cfg        = cfg
        self._cache     = {}
        self._cache_ttl = getattr(cfg, "SMART_MONEY_CACHE_TTL", 900)
        self.session    = requests.Session()
        self.session.headers.update({"User-Agent": "CryptoBot/1.0"})
        self._enabled        = getattr(cfg, "SMART_MONEY_ENABLED", True)
        self._leaderboard    = LeaderboardTracker(cfg) if getattr(cfg, "LEADERBOARD_ENABLED", True) else None
        # Weight split between long/short ratio and leaderboard
        self._ls_weight      = getattr(cfg, "LS_RATIO_WEIGHT", 0.5)
        self._lb_weight      = getattr(cfg, "LEADERBOARD_WEIGHT", 0.5)

    # ------------------------------------------------------------------ #
    #  Public                                                              #
    # ------------------------------------------------------------------ #

    def get_scores(self) -> dict:
        """
        Return smart money scores blending:
          - Binance top trader long/short ratio (50%)
          - Binance leaderboard top performers' positions (50%)
        """
        if not self._enabled:
            return {coin: 0.0 for coin in _FUTURES_SYMBOLS}

        now = time.time()
        if self._cache and all(
            (now - ts) < self._cache_ttl
            for _, ts in self._cache.values()
        ):
            scores = {coin: score for coin, (score, _) in self._cache.items()}
            logger.debug(f"SmartMoney: using cached scores {scores}")
            return scores

        # Fetch both signals
        ls_scores = {}
        lb_scores = {}

        for coin, symbol in _FUTURES_SYMBOLS.items():
            ls_scores[coin] = self._fetch_ratio_score(symbol)

        if self._leaderboard:
            lb_scores = self._leaderboard.get_scores()

        # Blend
        scores = {}
        for coin in _FUTURES_SYMBOLS:
            ls = ls_scores.get(coin, 0.0)
            lb = lb_scores.get(coin, 0.0)
            if lb_scores:
                blended = ls * self._ls_weight + lb * self._lb_weight
            else:
                blended = ls
            scores[coin]       = round(max(-1.0, min(1.0, blended)), 4)
            self._cache[coin]  = (scores[coin], now)

        self._log_table(scores, ls_scores, lb_scores)
        return scores

    def get_score(self, coin: str) -> float:
        return self.get_scores().get(coin, 0.0)

    # ------------------------------------------------------------------ #
    #  Fetching                                                            #
    # ------------------------------------------------------------------ #

    def _fetch_ratio_score(self, symbol: str) -> float:
        """
        Fetch top trader long/short position ratio and convert to -1.0..+1.0.
        Falls back to global account ratio if top trader data unavailable.
        """
        # Try top trader position ratio first (higher quality signal)
        score = self._fetch_endpoint(
            "/futures/data/topLongShortPositionRatio",
            symbol, period="15m", limit=1
        )
        if score is not None:
            return score

        # Fallback: global long/short account ratio
        score = self._fetch_endpoint(
            "/futures/data/globalLongShortAccountRatio",
            symbol, period="15m", limit=1
        )
        if score is not None:
            return score

        return 0.0

    def _fetch_endpoint(self, endpoint: str, symbol: str,
                        period: str = "15m", limit: int = 1) -> float | None:
        """Fetch a single long/short ratio endpoint and return a score."""
        try:
            r = self.session.get(
                _FUTURES_URL + endpoint,
                params={"symbol": symbol, "period": period, "limit": limit},
                timeout=8
            )
            if r.status_code == 404:
                return None   # symbol not on futures
            r.raise_for_status()
            data = r.json()

            if not data:
                return None

            # Response: [{"symbol": "BTCUSDT", "longShortRatio": "1.5423", ...}]
            latest  = data[-1] if isinstance(data, list) else data
            ratio   = float(
                latest.get("longShortRatio") or
                latest.get("longAccount") or
                1.0
            )

            # If the field is longAccount (0.0–1.0 fraction), convert to ratio
            if ratio <= 1.0 and ratio > 0:
                # It's a fraction — convert: fraction 0.6 → ratio 0.6/0.4 = 1.5
                if ratio != 1.0:
                    ratio = ratio / (1.0 - ratio)

            # Convert ratio to -1.0..+1.0 score
            # ratio=2.0 (2x more longs) → +1.0, ratio=0.5 → -1.0, ratio=1.0 → 0.0
            score = (ratio - 1.0) * 2.0
            return round(max(-1.0, min(1.0, score)), 4)

        except requests.RequestException as e:
            logger.debug(f"SmartMoney: {endpoint} {symbol} failed — {e}")
            return None
        except (ValueError, KeyError, IndexError) as e:
            logger.debug(f"SmartMoney: {symbol} parse error — {e}")
            return None

    # ------------------------------------------------------------------ #
    #  Logging                                                             #
    # ------------------------------------------------------------------ #

    def _log_table(self, scores: dict, ls_scores: dict = None, lb_scores: dict = None):
        """Print smart money table showing both signal sources."""
        ls_scores = ls_scores or {}
        lb_scores = lb_scores or {}
        coins     = list(scores.keys())
        col_coin  = max(len("Coin"), max(len(c) for c in coins))
        col_w     = 7

        show_lb = bool(lb_scores and any(v != 0.0 for v in lb_scores.values()))

        if show_lb:
            div = f"+{'-'*(col_coin+2)}+{'-'*(col_w+2)}+{'-'*(col_w+2)}+{'-'*(col_w+2)}+{'-'*10}+"
            hdr = f"| {'Coin':<{col_coin}} | {'L/S':>{col_w}} | {'Leaders':>{col_w}} | {'Final':>{col_w}} | {'Signal':<8} |"
        else:
            div = f"+{'-'*(col_coin+2)}+{'-'*(col_w+2)}+{'-'*(col_w+2)}+{'-'*10}+"
            hdr = f"| {'Coin':<{col_coin}} | {'L/S':>{col_w}} | {'Final':>{col_w}} | {'Signal':<8} |"

        logger.info("Smart Money:")
        logger.info(div)
        logger.info(hdr)
        logger.info(div)
        for coin, score in scores.items():
            mood = self._mood_label(score)
            ls   = ls_scores.get(coin, 0.0)
            lb   = lb_scores.get(coin, 0.0)
            if show_lb:
                logger.info(f"| {coin:<{col_coin}} | {ls:>+{col_w}.3f} | {lb:>+{col_w}.3f} | {score:>+{col_w}.3f} | {mood:<8} |")
            else:
                logger.info(f"| {coin:<{col_coin}} | {ls:>+{col_w}.3f} | {score:>+{col_w}.3f} | {mood:<8} |")
        logger.info(div)

    @staticmethod
    def _mood_label(score: float) -> str:
        if score >=  0.5: return "LONG"
        if score >=  0.2: return "mostly L"
        if score <= -0.5: return "SHORT"
        if score <= -0.2: return "mostly S"
        return "neutral"


# ============================================================
#  Binance Leaderboard tracker
# ============================================================

_LEADERBOARD_URL = "https://www.binance.com/bapi/futures/v3/public/future/leaderboard"

class LeaderboardTracker:
    """
    Tracks what Binance's top-ranked public traders are holding.
    Fetches the top N traders by PnL and reads their current open positions.
    Converts their aggregate positioning into a -1.0..+1.0 score per coin.
    """

    def __init__(self, cfg):
        self.cfg        = cfg
        self._cache     = {}
        self._cache_ttl = getattr(cfg, "LEADERBOARD_CACHE_TTL", 1800)  # 30 min
        self._top_n     = getattr(cfg, "LEADERBOARD_TOP_N", 10)
        self.session    = requests.Session()
        self.session.headers.update({
            "User-Agent":   "Mozilla/5.0",
            "Content-Type": "application/json",
            "Referer":      "https://www.binance.com/en/futures-activity/leaderboard",
        })

    def get_scores(self) -> dict:
        """Return leaderboard positioning scores per coin."""
        now = time.time()
        if self._cache and all((now - ts) < self._cache_ttl for _, ts in self._cache.values()):
            return {coin: score for coin, (score, _) in self._cache.items()}

        traders = self._fetch_top_traders()
        if not traders:
            logger.warning("Leaderboard: no traders fetched — returning neutral")
            return {coin: 0.0 for coin in _FUTURES_SYMBOLS}

        # Aggregate positions across all fetched traders
        coin_votes = {coin: [] for coin in _FUTURES_SYMBOLS}

        for trader in traders[:self._top_n]:
            uid = trader.get("encryptedUid", "")
            if not uid:
                continue
            positions = self._fetch_trader_positions(uid)
            for pos in positions:
                symbol = pos.get("symbol", "")
                amount = float(pos.get("amount", 0) or 0)
                # Match symbol to our coins
                for coin, futures_sym in _FUTURES_SYMBOLS.items():
                    if symbol == futures_sym:
                        # Positive amount = long, negative = short
                        coin_votes[coin].append(1.0 if amount > 0 else -1.0)

        scores = {}
        for coin, votes in coin_votes.items():
            if votes:
                # Average vote: +1.0 if all long, -1.0 if all short
                score = round(sum(votes) / len(votes), 4)
            else:
                score = 0.0
            scores[coin] = score
            self._cache[coin] = (score, now)

        logger.info(
            f"Leaderboard: {len(traders)} traders sampled | "
            f"scores: { {k: f'{v:+.2f}' for k, v in scores.items()} }"
        )
        return scores

    def _fetch_top_traders(self) -> list:
        """Fetch top traders by PnL from Binance leaderboard."""
        try:
            r = self.session.post(
                _LEADERBOARD_URL + "/getLeaderboardRank",
                json={
                    "isShared":    True,
                    "isTrader":    True,
                    "periodType":  "WEEKLY",
                    "statisticsType": "PNL",
                },
                timeout=10
            )
            r.raise_for_status()
            data = r.json()
            traders = data.get("data") or []
            logger.debug(f"Leaderboard: fetched {len(traders)} top traders")
            return traders
        except Exception as e:
            logger.warning(f"Leaderboard: fetch top traders failed — {e}")
            return []

    def _fetch_trader_positions(self, uid: str) -> list:
        """Fetch open positions for a specific trader UID."""
        try:
            r = self.session.post(
                _LEADERBOARD_URL + "/getOtherPosition",
                json={"encryptedUid": uid, "tradeType": "PERPETUAL"},
                timeout=8
            )
            r.raise_for_status()
            data = r.json()
            return data.get("data", {}).get("otherPositionRetList") or []
        except Exception as e:
            logger.debug(f"Leaderboard: positions for {uid} failed — {e}")
            return []
