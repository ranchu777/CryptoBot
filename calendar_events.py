"""
calendar_events.py — Economic calendar integration via ForexFactory JSON feed.

Source: https://nfs.faireconomy.media/ff_calendar_thisweek.json
  - Free, no API key required
  - Updates weekly, rate limited to 2 requests per 5 minutes
  - Cached locally for 1 hour to stay well within rate limits

How it works:
  1. Fetches this week's economic events once per hour
  2. On each bot cycle, scans for events happening within a configurable
     window (default: ±2 hours from now)
  3. Scores events by impact and relevance to crypto markets
  4. Returns a -1.0 to +1.0 signal that feeds into the combined signal

Event scoring logic:
  - High impact USD events (Fed rate, CPI, NFP, GDP):  strong effect  ±0.8
  - High impact events other currencies:               moderate       ±0.4
  - Medium impact USD events:                          mild           ±0.3
  - Low impact / other:                                ignored         0.0

  - Actual > Forecast (beat):  bullish  +score
  - Actual < Forecast (miss):  bearish  -score
  - No actual yet (upcoming):  caution  -score * 0.5  (uncertainty penalty)

Usage:
    from calendar_events import EconomicCalendar
    cal = EconomicCalendar(cfg)
    score, events = cal.get_score()
    # score: -1.0 to +1.0
    # events: list of active event dicts for logging
"""

import time
import json
import logging
import os
import requests
from datetime import datetime, timezone, timedelta

logger = logging.getLogger("cryptobot")

_CALENDAR_URL   = "https://nfs.faireconomy.media/ff_calendar_thisweek.json"
_CACHE_FILE     = "calendar_cache.json"

# Keywords that make a USD event highly relevant to crypto markets
_CRYPTO_RELEVANT_KEYWORDS = [
    "fed", "fomc", "federal reserve", "interest rate", "rate decision",
    "cpi", "inflation", "pce", "nonfarm", "nfp", "payroll",
    "gdp", "unemployment", "jobs", "sec", "crypto", "bitcoin",
    "jerome powell", "powell", "treasury", "debt ceiling",
    "recession", "financial stability",
]

# Event titles that are high impact for crypto specifically
_HIGH_CRYPTO_IMPACT = [
    "fomc", "federal funds rate", "fed rate", "interest rate decision",
    "cpi", "consumer price index", "nonfarm payroll", "non-farm payroll",
    "gdp", "unemployment rate", "sec", "crypto",
]


class EconomicCalendar:
    def __init__(self, cfg):
        self.cfg          = cfg
        self._events      = []
        self._last_fetch  = 0.0
        self._cache_ttl   = getattr(cfg, "CALENDAR_CACHE_TTL", 21600)
        self._window_mins = getattr(cfg, "CALENDAR_WINDOW_MINS", 120)
        self._enabled     = getattr(cfg, "CALENDAR_ENABLED", True)
        self.session      = requests.Session()
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 CryptoBot/1.0",
            "Accept":     "application/json",
        })
        # Load from local file cache on startup — avoids fetching on every restart
        self._load_file_cache()

    # ------------------------------------------------------------------ #
    #  File cache                                                          #
    # ------------------------------------------------------------------ #

    def _load_file_cache(self):
        """Load cached events from disk if still fresh enough to use."""
        try:
            if not os.path.exists(_CACHE_FILE):
                return
            with open(_CACHE_FILE, "r") as f:
                saved = json.load(f)

            fetch_time = float(saved.get("fetch_time", 0))
            age        = time.time() - fetch_time

            # Re-parse stored events (stored without _parsed_time since it's not JSON serialisable)
            raw_events = saved.get("events", [])
            if raw_events:
                self._events     = self._parse_events(raw_events)
                self._last_fetch = fetch_time

            if age < self._cache_ttl:
                logger.info(
                    f"Calendar: loaded {len(self._events)} events from local cache "
                    f"(age {age/3600:.1f}h — no fetch needed)"
                )
            else:
                logger.debug(
                    f"Calendar: local cache is {age/3600:.1f}h old — will refresh on next cycle"
                )
        except Exception as e:
            logger.debug(f"Calendar: could not read local cache — {e}")

    def _save_file_cache(self, raw_events: list):
        """Persist raw events to disk so restarts don't need a new fetch."""
        try:
            # Strip _parsed_time before saving (datetime not JSON serialisable)
            saveable = [
                {k: v for k, v in ev.items() if k != "_parsed_time"}
                for ev in raw_events
            ]
            with open(_CACHE_FILE, "w") as f:
                json.dump({"fetch_time": time.time(), "events": saveable}, f, indent=2)
            logger.debug(f"Calendar: saved {len(saveable)} events to {_CACHE_FILE}")
        except Exception as e:
            logger.debug(f"Calendar: could not save local cache — {e}")

    # ------------------------------------------------------------------ #
    #  Public                                                              #
    # ------------------------------------------------------------------ #

    def get_score(self) -> tuple[float, list]:
        """
        Return (score, active_events) for current market conditions.

        score:         -1.0 to +1.0 — net effect of nearby economic events
        active_events: list of event dicts happening within the window
        """
        if not self._enabled:
            return 0.0, []

        self._refresh_if_needed()

        if not self._events:
            return 0.0, []

        now    = datetime.now(timezone.utc)
        window = timedelta(minutes=self._window_mins)

        active   = []
        scores   = []

        for event in self._events:
            event_time = event.get("_parsed_time")
            if not event_time:
                continue

            # Only consider events within ±window of now
            delta = abs((event_time - now).total_seconds()) / 60
            if delta > self._window_mins:
                continue

            score = self._score_event(event, event_time, now)
            if score == 0.0:
                continue

            active.append(event)
            scores.append(score)

        if not scores:
            return 0.0, []

        # Average all active event scores, clamp to ±1.0
        net = sum(scores) / len(scores)
        net = round(max(-1.0, min(1.0, net)), 4)

        return net, active

    # ------------------------------------------------------------------ #
    #  Fetching                                                            #
    # ------------------------------------------------------------------ #

    def _refresh_if_needed(self):
        """Fetch fresh calendar data if cache has expired."""
        if time.time() - self._last_fetch < self._cache_ttl:
            return
        try:
            r = self.session.get(_CALENDAR_URL, timeout=10)
            if r.status_code == 429:
                # Rate limited — back off for 2 hours before retrying
                self._last_fetch = time.time() + 3600
                logger.warning(
                    "Calendar: rate limited by ForexFactory (429). "
                    "Backing off for 2 hours. Using cached events if available."
                )
                return
            r.raise_for_status()
            raw = r.json()
            self._events     = self._parse_events(raw)
            self._last_fetch = time.time()
            self._save_file_cache(raw)   # persist to disk
            logger.info(f"Calendar: loaded {len(self._events)} events for this week")
        except Exception as e:
            # On any failure, wait 30 minutes before retrying instead of every cycle
            self._last_fetch = time.time() + 1800
            logger.warning(f"Calendar: fetch failed — {e}. Retrying in 30 minutes.")

    def _parse_events(self, raw: list) -> list:
        """Parse raw JSON events, adding a parsed datetime field."""
        parsed = []
        for ev in raw:
            try:
                dt_str = ev.get("date", "")
                if not dt_str:
                    continue
                # ForexFactory format: "2026-03-22T13:30:00-04:00"
                from dateutil import parser as dateutil_parser
                ev["_parsed_time"] = dateutil_parser.parse(dt_str).astimezone(timezone.utc)
                parsed.append(ev)
            except Exception:
                continue
        return parsed

    # ------------------------------------------------------------------ #
    #  Scoring                                                             #
    # ------------------------------------------------------------------ #

    def _score_event(self, event: dict, event_time: datetime, now: datetime) -> float:
        """Score a single event. Returns -1.0 to +1.0 or 0.0 if irrelevant."""
        title   = (event.get("title") or "").lower()
        country = (event.get("country") or "").upper()
        impact  = (event.get("impact") or "").lower()
        actual  = event.get("actual")
        forecast = event.get("forecast")
        previous = event.get("previous")

        # Base weight by impact and country
        if impact == "high" and country == "USD":
            base = 0.8
        elif impact == "high":
            base = 0.4
        elif impact == "medium" and country == "USD":
            base = 0.3
        else:
            # Low impact or non-USD medium — skip unless it's crypto-specific
            if not any(kw in title for kw in ["crypto", "bitcoin", "sec", "etf"]):
                return 0.0
            base = 0.2

        # Boost for events directly relevant to crypto
        if any(kw in title for kw in _CRYPTO_RELEVANT_KEYWORDS):
            base = min(1.0, base * 1.25)

        is_upcoming = event_time > now

        # If actual result is available — score by beat/miss vs forecast
        if actual and forecast:
            try:
                act_val  = self._parse_number(actual)
                fore_val = self._parse_number(forecast)
                if act_val is not None and fore_val is not None and fore_val != 0:
                    diff_pct  = (act_val - fore_val) / abs(fore_val)
                    magnitude = min(1.0, abs(diff_pct) * 5)

                    # For inflation/unemployment events, lower than forecast = bullish
                    # (Fed less likely to hike; economy not overheating)
                    inverse = any(kw in title for kw in [
                        "cpi", "inflation", "pce", "unemployment", "jobless",
                        "initial claims", "continuing claims"
                    ])
                    direction = (-1.0 if diff_pct > 0 else 1.0) if inverse else (1.0 if diff_pct > 0 else -1.0)
                    return round(direction * base * magnitude, 4)
            except Exception:
                pass

        # If actual vs previous available (no forecast)
        if actual and previous and not forecast:
            try:
                act_val  = self._parse_number(actual)
                prev_val = self._parse_number(previous)
                if act_val is not None and prev_val is not None and prev_val != 0:
                    diff_pct = (act_val - prev_val) / abs(prev_val)
                    direction = 1.0 if diff_pct > 0 else -1.0
                    return round(direction * base * 0.5, 4)
            except Exception:
                pass

        # Upcoming high-impact event with no result yet — uncertainty penalty
        if is_upcoming:
            mins_away = (event_time - now).total_seconds() / 60
            # Closer = more uncertainty = stronger caution signal
            urgency = max(0.2, 1.0 - (mins_away / self._window_mins))
            return round(-base * 0.4 * urgency, 4)   # mild bearish (caution)

        return 0.0

    @staticmethod
    def _parse_number(value: str) -> float | None:
        """Parse values like '3.2%', '-150K', '1.5M', '2.1B'."""
        if not value:
            return None
        v = value.strip().replace(",", "").replace("%", "")
        multiplier = 1.0
        if v.upper().endswith("K"):
            multiplier, v = 1_000, v[:-1]
        elif v.upper().endswith("M"):
            multiplier, v = 1_000_000, v[:-1]
        elif v.upper().endswith("B"):
            multiplier, v = 1_000_000_000, v[:-1]
        try:
            return float(v) * multiplier
        except ValueError:
            return None

    # ------------------------------------------------------------------ #
    #  Logging                                                             #
    # ------------------------------------------------------------------ #

    def log_active_events(self, active_events: list, score: float):
        """Log active events and their net score."""
        if not active_events:
            return
        logger.info(f"Calendar: {len(active_events)} active event(s) | net score={score:+.3f}")
        for ev in active_events:
            t      = ev.get("_parsed_time")
            tstr   = t.strftime("%H:%M UTC") if t else "?"
            impact = ev.get("impact", "?").upper()
            title  = ev.get("title", "?")
            actual = ev.get("actual") or "pending"
            fore   = ev.get("forecast") or "—"
            logger.info(f"  [{impact}] {tstr} {ev.get('country','')} — {title} | actual={actual} forecast={fore}")
