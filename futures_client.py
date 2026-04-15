"""
futures_client.py — Shared Binance Futures API client.

Consolidates common API calls used by smart_money.py and market_filters.py
to eliminate code duplication and ensure consistent error handling.
"""

import time
import logging
import requests

logger = logging.getLogger("cryptobot")

_FUTURES_URL = "https://fapi.binance.com"

_FUTURES_SYMBOLS = {
    "BTC":  "BTCUSDT",
    "ETH":  "ETHUSDT",
    "SOL":  "SOLUSDT",
    "BNB":  "BNBUSDT",
    "DOGE": "DOGEUSDT",
}


class BinanceFuturesClient:
    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": "CryptoBot/1.0"})

    def _get(self, endpoint: str, params: dict = None, timeout: int = 8) -> dict | list | None:
        """Internal GET request with error handling."""
        try:
            r = self.session.get(_FUTURES_URL + endpoint, params=params, timeout=timeout)
            if r.status_code == 404:
                return None  # symbol not available
            r.raise_for_status()
            return r.json()
        except Exception as e:
            logger.debug(f"Futures API {endpoint}: {e}")
            return None

    def get_funding_rate(self, symbol: str) -> float | None:
        """Get current funding rate for a symbol."""
        data = self._get("/fapi/v1/premiumIndex", {"symbol": symbol})
        if data:
            return float(data.get("lastFundingRate", 0))
        return None

    def get_open_interest_hist(self, symbol: str, period: str = "5m", limit: int = 3) -> list | None:
        """Get open interest history."""
        return self._get("/futures/data/openInterestHist", {
            "symbol": symbol,
            "period": period,
            "limit": limit
        })

    def get_top_long_short_ratio(self, symbol: str, period: str = "15m", limit: int = 1) -> dict | None:
        """Get top trader long/short position ratio."""
        data = self._get("/futures/data/topLongShortPositionRatio", {
            "symbol": symbol,
            "period": period,
            "limit": limit
        })
        return data[-1] if data and isinstance(data, list) else data

    def get_global_long_short_ratio(self, symbol: str, period: str = "15m", limit: int = 1) -> dict | None:
        """Get global long/short account ratio."""
        data = self._get("/futures/data/globalLongShortAccountRatio", {
            "symbol": symbol,
            "period": period,
            "limit": limit
        })
        return data[-1] if data and isinstance(data, list) else data