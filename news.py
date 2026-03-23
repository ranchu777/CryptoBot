"""
news.py — Crypto news sentiment analyser.

Fetches headlines from CryptoPanic (free, no key required for public feed)
and scores them per coin on a scale of -1.0 (very bearish) to +1.0 (very bullish).

Score breakdown:
  - Keyword sentiment  : bullish / bearish word matches
  - Recency weighting  : newer articles score higher
  - Vote signals       : CryptoPanic community upvotes/downvotes (if available)
  - Panic flag penalty : articles flagged as FUD get a penalty

Usage:
    from news import NewsSentiment
    ns = NewsSentiment(cfg)
    scores = ns.get_scores()   # {"BTC": 0.42, "ETH": -0.15, ...}
"""

import time
import re
import logging
import requests
from datetime import datetime, timezone

logger = logging.getLogger("cryptobot")


# ── Sentiment keyword lists ──────────────────────────────────────────────────

BULLISH_WORDS = [
    # Price action
    "surge", "surges", "surging",
    "rally", "rallies", "rallying", "rallied",
    "jump", "jumps", "jumping", "jumped",
    "climb", "climbs", "climbing", "climbed",
    "rise", "rises", "rising", "risen", "rose",
    "soar", "soars", "soaring", "soared",
    "spike", "spikes", "spiking", "spiked",
    "gain", "gains", "gaining", "gained",
    "pump", "pumps", "pumping", "pumped",
    "rebound", "rebounds", "rebounding", "rebounded",
    "recover", "recovers", "recovering", "recovered", "recovery",
    "breakout", "breaks out", "broke out",
    "higher", "high", "tops", "top",
    "outperform", "outperforms", "outperformed",
    # Fundamentals / sentiment
    "bullish", "bull run", "bull market",
    "all-time high", "ath", "record high", "new high",
    "buy", "buying", "accumulate", "accumulation",
    "adoption", "partnership", "upgrade", "mainnet",
    "launch", "launches", "launched",
    "institutional", "etf approved", "etf approval",
    "approval", "approved", "legal tender",
    "listing", "listed",
    "investment", "invest", "inflows", "inflow",
    "backed", "support", "strong", "strength",
    "milestone", "integration", "growth", "positive",
    "moon", "mooning",
]

BEARISH_WORDS = [
    # Price action
    "crash", "crashes", "crashing", "crashed",
    "dump", "dumps", "dumping", "dumped",
    "drop", "drops", "dropping", "dropped",
    "fall", "falls", "falling", "fell", "fallen",
    "plunge", "plunges", "plunging", "plunged",
    "slide", "slides", "sliding", "slid",
    "tumble", "tumbles", "tumbling", "tumbled",
    "sink", "sinks", "sinking", "sank",
    "slump", "slumps", "slumping", "slumped",
    "decline", "declines", "declining", "declined",
    "lower", "down", "downtrend",
    "correction", "sell-off", "selloff",
    "liquidation", "liquidated", "wiped",
    # Fundamentals / sentiment
    "bearish", "bear market",
    "ban", "banned", "banning",
    "hack", "hacked", "exploit", "exploited",
    "scam", "fraud", "ponzi",
    "bankrupt", "bankruptcy", "insolvent",
    "lawsuit", "charges", "investigation",
    "regulatory", "crackdown",
    "fear", "panic", "fud",
    "outflows", "outflow", "weakness",
    "loss", "losses", "losing",
    "delisted", "delist", "warning",
    "vulnerable", "attack",
    "concern", "concerns", "risk",
    "sec",
]

# Map coin symbols to ALL common names used in crypto news headlines
COIN_KEYWORDS = {
    "BTC":  ["bitcoin", "btc", "xbt"],
    "ETH":  ["ethereum", "eth", "ether"],          # CoinDesk uses "Ether"
    "SOL":  ["solana", "sol"],
    "BNB":  ["bnb", "binance coin"],               # removed "binance" — too generic
    "DOGE": ["dogecoin", "doge"],
}


# Precompiled word-boundary patterns — prevents "sec" matching "second", etc.
_BULLISH_RE = re.compile(
    r"\b(" + "|".join(re.escape(w) for w in BULLISH_WORDS) + r")\b",
    re.IGNORECASE
)
_BEARISH_RE = re.compile(
    r"\b(" + "|".join(re.escape(w) for w in BEARISH_WORDS) + r")\b",
    re.IGNORECASE
)

# Per-coin filter patterns — compiled once, reused every cycle
_COIN_RE: dict[str, re.Pattern] = {
    coin: re.compile(
        r"\b(" + "|".join(re.escape(kw) for kw in kws) + r")\b",
        re.IGNORECASE
    )
    for coin, kws in COIN_KEYWORDS.items()
}


class NewsSentiment:
    def __init__(self, cfg):
        self.cfg = cfg
        self.api_key        = getattr(cfg, "CRYPTOPANIC_KEY", "")
        self.freecrypto_key = getattr(cfg, "FREECRYPTOAPI_KEY", "")
        self._cache     = {}
        self._cache_ttl = getattr(cfg, "NEWS_CACHE_TTL", 300)
        # Shared session for CryptoPanic / RSS
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": "CryptoBot/1.0"})
        # Separate persistent session for FreeCryptoAPI (different auth header)
        self._fcapi_session = None
        if self.freecrypto_key:
            self._fcapi_session = requests.Session()
            self._fcapi_session.headers.update({
                "Authorization": f"Bearer {self.freecrypto_key}",
                "User-Agent": "CryptoBot/1.0",
            })

    # ------------------------------------------------------------------ #
    #  Public                                                              #
    # ------------------------------------------------------------------ #

    def get_scores(self) -> dict:
        """
        Return sentiment scores blending text headlines and FreeCryptoAPI price data.

        Article handling:
          - Coin-specific articles (mention the coin by name) → scored per coin
          - General market articles (no coin name) → scored as market-wide sentiment
            and blended into every coin at a lower weight (MARKET_SENTIMENT_WEIGHT)
          - Both fetches run in parallel
        """
        now = time.time()
        if self._cache and all((now - ts) < self._cache_ttl for _, ts in self._cache.values()):
            scores = {coin: score for coin, (score, _) in self._cache.items()}
            logger.debug(f"News: using cached scores {scores}")
            return scores

        # Fetch text articles and FreeCryptoAPI price signals in parallel
        from concurrent.futures import ThreadPoolExecutor
        with ThreadPoolExecutor(max_workers=2) as ex:
            text_future  = ex.submit(self._fetch_articles)
            price_future = ex.submit(self._fetch_freecryptoapi) if self._fcapi_session else None

        text_articles = text_future.result()
        price_signals = price_future.result() if price_future else {}

        if text_articles:
            sample = [a.get("title", "")[:80] for a in text_articles[:5]]
            logger.info(f"News: article sample — {sample}")

        if not text_articles and not price_signals:
            logger.warning("News: no data from any source, returning neutral scores")
            return {coin: 0.0 for coin in COIN_KEYWORDS}

        # Separate coin-specific articles from general market articles
        coin_matched = set()
        for coin in COIN_KEYWORDS:
            for a in self._filter_articles(text_articles, coin):
                coin_matched.add(id(a))

        general_articles = [a for a in text_articles if id(a) not in coin_matched]
        market_score     = self._score_articles(general_articles) if general_articles else 0.0
        market_weight    = getattr(self.cfg, "MARKET_SENTIMENT_WEIGHT", 0.2)

        logger.info(
            f"News: {len(text_articles)} total | "
            f"{len(coin_matched)} coin-specific | "
            f"{len(general_articles)} general market (score={market_score:+.3f})"
        )

        fcapi_weight = getattr(self.cfg, "FREECRYPTOAPI_WEIGHT", 0.5)
        # When FreeCryptoAPI is available, split remaining weight between text and market
        if price_signals:
            text_w   = (1.0 - fcapi_weight) * (1.0 - market_weight)
            market_w = (1.0 - fcapi_weight) * market_weight
            price_w  = fcapi_weight
        else:
            text_w   = 1.0 - market_weight
            market_w = market_weight
            price_w  = 0.0

        scores = {}
        for coin in COIN_KEYWORDS:
            relevant    = self._filter_articles(text_articles, coin)
            coin_score  = self._score_articles(relevant) if relevant else 0.0
            price_score = price_signals.get(coin, 0.0)
            blended     = (
                coin_score   * text_w   +
                market_score * market_w +
                price_score  * price_w
            )
            final = round(max(-1.0, min(1.0, blended)), 4)
            scores[coin] = final
            self._cache[coin] = (final, now)
            logger.debug(
                f"News: {coin} coin={coin_score:+.3f} market={market_score:+.3f} "
                f"price={price_score:+.3f} → final={final:+.3f} "
                f"({len(relevant)} coin-specific + {len(general_articles)} general)"
            )

        self._log_sentiment_table(scores, text_articles, price_signals, general_articles, market_score)
        return scores

    def get_score(self, coin: str) -> float:
        """Return sentiment score for a single coin symbol (e.g. 'BTC')."""
        return self.get_scores().get(coin, 0.0)

    # ------------------------------------------------------------------ #
    #  Fetching                                                            #
    # ------------------------------------------------------------------ #

    def _fetch_articles(self) -> list:
        """
        Fetch latest crypto news from CryptoPanic.
        - With API key: uses v2 JSON API (free plan)
        - Without API key: falls back to public RSS feed (no auth needed)
        """
        if self.api_key:
            return self._fetch_json_api()
        else:
            return self._fetch_rss_fallback()

    def _fetch_json_api(self) -> list:
        """
        CryptoPanic JSON API — tries v2 plan URLs then falls back to v1.
        The v2 URL requires the plan slug (e.g. 'free', 'starter', 'pro').
        We try the most common ones in order before falling back to v1.
        """
        base_params = {
            "auth_token": self.api_key,
            "public":     "true",
            "kind":       "news",
        }
        # Try v2 plan slugs in order, then v1 as final fallback
        urls = [
            "https://cryptopanic.com/api/v1/posts/",         # v1 — most widely working
            "https://cryptopanic.com/api/free/v2/posts/",    # v2 free plan
            "https://cryptopanic.com/api/starter/v2/posts/", # v2 starter plan
            "https://cryptopanic.com/api/pro/v2/posts/",     # v2 pro plan
        ]
        for url in urls:
            try:
                r = self.session.get(url, params=base_params, timeout=10)
                if r.status_code == 404:
                    continue   # wrong plan slug, try next
                r.raise_for_status()
                data = r.json()
                articles = data.get("results", [])
                # v2 uses 'instruments', v1 uses 'currencies' — normalise to 'currencies'
                for a in articles:
                    if "instruments" in a and "currencies" not in a:
                        a["currencies"] = a["instruments"]
                logger.info(
                    f"News: fetched {len(articles)} articles "
                    f"(CryptoPanic {url.split('/api/')[1].split('/posts')[0]})"
                )
                return articles
            except requests.RequestException as e:
                logger.debug(f"News: {url} failed — {e}")
                continue

        logger.info("News: CryptoPanic API unavailable, using RSS fallback")
        return self._fetch_rss_fallback()

    def _fetch_rss_fallback(self) -> list:
        """
        RSS fallback — no authentication needed.
        Tries CryptoPanic RSS first, then CoinDesk RSS as a second backup.
        """
        rss_sources = [
            ("CryptoPanic", "https://cryptopanic.com/news/rss/"),
            ("CoinDesk",    "https://www.coindesk.com/arc/outboundfeeds/rss/"),
        ]
        for name, url in rss_sources:
            try:
                r = self.session.get(url, timeout=10)
                r.raise_for_status()
                articles = self._parse_rss(r.text)
                if articles:
                    logger.info(f"News: fetched {len(articles)} articles ({name} RSS)")
                    return articles
            except requests.RequestException as e:
                logger.debug(f"News: {name} RSS failed — {e}")
                continue

        logger.error("News: all sources failed — running without news sentiment this cycle")
        return []

    @staticmethod
    def _parse_rss(xml_text: str) -> list:
        """Parse RSS XML into the same dict shape as the JSON API response.
        Handles both plain text and CDATA-wrapped fields (used by CoinDesk).
        """
        import re
        from email.utils import parsedate_to_datetime

        def get_tag(item_text: str, t: str) -> str:
            m = re.search(rf"<{t}[^>]*>(.*?)</{t}>", item_text, re.DOTALL)
            if not m:
                return ""
            val = m.group(1).strip()
            # Strip CDATA wrapper: <![CDATA[...]]>
            cdata = re.match(r"<!\[CDATA\[(.*?)\]\]>", val, re.DOTALL)
            return cdata.group(1).strip() if cdata else val

        articles = []
        items = re.findall(r"<item>(.*?)</item>", xml_text, re.DOTALL)
        for item in items:
            title = re.sub(r"<[^>]+>", "", get_tag(item, "title")).strip()
            if not title:
                continue   # skip empty titles — they won't score anything

            pub_raw = get_tag(item, "pubDate")
            try:
                pub_dt  = parsedate_to_datetime(pub_raw).astimezone(timezone.utc)
                pub_iso = pub_dt.isoformat()
            except Exception:
                pub_iso = ""

            categories = re.findall(r"<category[^>]*>(.*?)</category>", item, re.DOTALL)
            currencies = [{"code": c.strip().upper()} for c in categories if c.strip()]

            articles.append({
                "title":        title,
                "published_at": pub_iso,
                "kind":         "news",
                "votes":        {},
                "currencies":   currencies,
            })
        return articles

    def _fetch_freecryptoapi(self) -> dict:
        """
        Fetch 24h % change from FreeCryptoAPI and convert to -1.0..+1.0 score.
        Uses persistent session created at __init__.
        ±10% change maps to ±1.0.
        """
        symbol_map = {"BTC": "BTC", "ETH": "ETH", "SOL": "SOL", "BNB": "BNB", "DOGE": "DOGE"}
        price_scores = {}
        fetched = 0

        for coin, symbol in symbol_map.items():
            try:
                r = self._fcapi_session.get(
                    "https://api.freecryptoapi.com/v1/getData",
                    params={"symbol": symbol},
                    timeout=8
                )
                if r.status_code == 401:
                    logger.error("FreeCryptoAPI: invalid key — check FREECRYPTOAPI_KEY in .env")
                    return {}
                if r.status_code == 404:
                    continue
                r.raise_for_status()
                data = r.json()

                # Log raw response at DEBUG level only — avoids cluttering INFO logs
                if not price_scores:
                    logger.debug(f"FreeCryptoAPI raw sample ({symbol}): {data}")

                # Response shape: {"status": "success", "symbols": [{"symbol": "BTC", "daily_change_percentage": "-0.39", ...}]}
                symbols_list = data.get("symbols") or []
                coin_data = symbols_list[0] if symbols_list else {}

                pct = float(
                    coin_data.get("daily_change_percentage") or
                    coin_data.get("percent_change_24h") or
                    coin_data.get("change_24h") or
                    coin_data.get("price_change_percent_24h") or
                    coin_data.get("change24h") or
                    coin_data.get("priceChangePercent") or
                    coin_data.get("percentChange24h") or
                    coin_data.get("percent_change") or
                    coin_data.get("changePercent") or
                    coin_data.get("change_percent") or 0.0
                )
                price_scores[coin] = round(max(-1.0, min(1.0, pct / 10.0)), 4)
                logger.debug(f"FreeCryptoAPI: {coin} 24h={pct:+.2f}% → {price_scores[coin]:+.3f}")
                fetched += 1
                logger.debug(f"FreeCryptoAPI: {coin} 24h={pct:+.2f}% → {price_scores[coin]:+.3f}")
            except Exception as e:
                logger.debug(f"FreeCryptoAPI: {coin} failed — {e}")

        if fetched:
            logger.info(f"FreeCryptoAPI: price signals for {fetched} coins")
        else:
            logger.warning("FreeCryptoAPI: no price signals fetched")
        return price_scores

    def _filter_articles(self, articles: list, coin: str) -> list:
        """Return articles relevant to the given coin using precompiled regex."""
        if not articles:
            return []
        pattern   = _COIN_RE.get(coin)
        keywords  = COIN_KEYWORDS.get(coin, [])
        relevant  = []
        for a in articles:
            title = a.get("title") or ""
            currencies = [c.get("code", "").lower() for c in (a.get("currencies") or [])]
            if (pattern and pattern.search(title)) or any(kw in currencies for kw in keywords):
                relevant.append(a)
        return relevant

    def _score_articles(self, articles: list) -> float:
        """
        Score a list of articles on a -1.0 to +1.0 scale.

        Each article contributes a weighted sentiment value.
        Weights factor in:
          - Recency (exponential decay over 6 hours)
          - CryptoPanic vote ratio (upvotes vs downvotes)
          - FUD/panic flag penalty
        """
        if not articles:
            return 0.0

        now = datetime.now(timezone.utc)
        total_weight = 0.0
        weighted_score = 0.0

        for a in articles:
            title = (a.get("title") or "").lower()

            # --- Keyword sentiment (word-boundary matched, no false substrings) ---
            bull = len(_BULLISH_RE.findall(title))
            bear = len(_BEARISH_RE.findall(title))
            if bull == 0 and bear == 0:
                keyword_score = 0.0
            else:
                keyword_score = (bull - bear) / (bull + bear)

            # --- Vote sentiment ---
            votes = a.get("votes") or {}
            up   = float(votes.get("positive", 0) or 0)
            down = float(votes.get("negative", 0) or 0)
            if up + down > 0:
                vote_score = (up - down) / (up + down)
            else:
                vote_score = 0.0

            # --- Recency weight (half-life = 3 hours) ---
            try:
                pub = datetime.fromisoformat(
                    a.get("published_at", "").replace("Z", "+00:00")
                )
                age_hours = (now - pub).total_seconds() / 3600
            except Exception:
                age_hours = 6.0
            recency_weight = max(0.05, 2 ** (-age_hours / 3))

            # --- Panic/FUD flag penalty ---
            kind = (a.get("kind") or "").lower()
            panic_penalty = -0.3 if kind in ("panic", "fud") else 0.0

            # --- Combine ---
            article_score = (
                keyword_score * 0.6 +
                vote_score    * 0.4 +
                panic_penalty
            )
            article_score = max(-1.0, min(1.0, article_score))

            logger.debug(
                f"  article: bull={bull} bear={bear} kw={keyword_score:+.2f} "
                f"vote={vote_score:+.2f} weight={recency_weight:.3f} "
                f"score={article_score:+.2f} | {title[:60]}"
            )

            weighted_score += article_score * recency_weight
            total_weight   += recency_weight

        if total_weight == 0:
            return 0.0

        raw = weighted_score / total_weight
        return round(max(-1.0, min(1.0, raw)), 4)

    # ------------------------------------------------------------------ #
    #  Logging                                                             #
    # ------------------------------------------------------------------ #

    def _log_sentiment_table(
        self,
        scores: dict,
        articles: list,
        price_signals: dict = None,
        general_articles: list = None,
        market_score: float = 0.0,
    ):
        """Print sentiment summary table including general market article count."""
        price_signals    = price_signals or {}
        general_articles = general_articles or []
        show_price       = bool(price_signals)
        coins            = list(scores.keys())

        col_coin  = max(len("Coin"),  max(len(c) for c in coins))
        col_score = 7
        col_mood  = 8
        col_coin_n = max(len("Coin art"), 8)
        col_price = 7

        if show_price:
            div = (f"+{'-'*(col_coin+2)}+{'-'*(col_score+2)}+{'-'*(col_price+2)}"
                   f"+{'-'*(col_mood+2)}+{'-'*(col_coin_n+2)}+")
            hdr = (f"| {'Coin':<{col_coin}} | {'Final':>{col_score}} "
                   f"| {'Price':>{col_price}} | {'Mood':<{col_mood}} "
                   f"| {'Coin art':>{col_coin_n}} |")
        else:
            div = (f"+{'-'*(col_coin+2)}+{'-'*(col_score+2)}"
                   f"+{'-'*(col_mood+2)}+{'-'*(col_coin_n+2)}+")
            hdr = (f"| {'Coin':<{col_coin}} | {'Score':>{col_score}} "
                   f"| {'Mood':<{col_mood}} | {'Coin art':>{col_coin_n}} |")

        logger.info(div)
        logger.info(hdr)
        logger.info(div)
        for coin, score in scores.items():
            relevant = self._filter_articles(articles, coin)
            mood     = self._mood_label(score)
            if show_price:
                price_score = price_signals.get(coin, 0.0)
                logger.info(
                    f"| {coin:<{col_coin}} | {score:>+{col_score}.3f} "
                    f"| {price_score:>+{col_price}.3f} | {mood:<{col_mood}} "
                    f"| {len(relevant):>{col_coin_n}} |"
                )
            else:
                logger.info(
                    f"| {coin:<{col_coin}} | {score:>+{col_score}.3f} "
                    f"| {mood:<{col_mood}} | {len(relevant):>{col_coin_n}} |"
                )
        logger.info(div)
        # Footer showing general market articles
        logger.info(
            f"  general market: {len(general_articles)} articles "
            f"(score={market_score:+.3f}) applied to all coins at "
            f"{getattr(self.cfg, 'MARKET_SENTIMENT_WEIGHT', 0.2):.0%} weight"
        )

    @staticmethod
    def _mood_label(score: float) -> str:
        if score >=  0.5: return "BULLISH"
        if score >=  0.2: return "positive"
        if score <= -0.5: return "BEARISH"
        if score <= -0.2: return "negative"
        return "neutral"
