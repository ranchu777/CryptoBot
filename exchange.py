"""
exchange.py — Binance API wrapper.

Connection resilience:
  - Automatic retry with exponential backoff on ConnectionReset / timeout
  - Session recycled at cycle start to prevent stale connections
  - Signed requests get a fresh timestamp on every retry attempt
"""

import time
import hmac
import hashlib
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
import pandas as pd
import logging

logger = logging.getLogger("cryptobot")

_MAX_RETRIES   = 3
_RETRY_BACKOFF = 1.0

_KLINE_COLS = [
    "open_time", "open", "high", "low", "close", "volume",
    "close_time", "quote_vol", "trades", "taker_buy_base",
    "taker_buy_quote", "ignore",
]
_KEEP_COLS = ["open", "high", "low", "close", "volume"]

_QTY_PRECISION = {
    "BTCUSDT":  5,
    "ETHUSDT":  4,
    "SOLUSDT":  2,
    "BNBUSDT":  3,
    "DOGEUSDT": 0,
}


def _make_session(api_key: str) -> requests.Session:
    s = requests.Session()
    s.headers.update({
        "X-MBX-APIKEY": api_key,
        "Content-Type": "application/json",
        "Connection": "close",
    })
    adapter = HTTPAdapter(
        max_retries=Retry(
            total=_MAX_RETRIES,
            backoff_factor=_RETRY_BACKOFF,
            status_forcelist=[429, 500, 502, 503, 504],
            allowed_methods=["GET", "POST"],
            raise_on_status=False,
        )
    )
    s.mount("https://", adapter)
    s.mount("http://",  adapter)
    return s


class BinanceClient:
    def __init__(self, cfg):
        self.cfg         = cfg
        self._api_key    = cfg.API_KEY
        self._secret     = cfg.API_SECRET.encode("utf-8")
        self.session     = _make_session(cfg.API_KEY)
        self._positions  = {}

    def recycle_session(self):
        try:
            self.session.close()
        except Exception:
            pass
        self.session = _make_session(self._api_key)

    def _sign(self, params: dict) -> dict:
        query = "&".join(f"{k}={v}" for k, v in params.items())
        sig = hmac.new(self._secret, query.encode("utf-8"), hashlib.sha256).hexdigest()
        params["signature"] = sig
        return params

    def _get(self, endpoint: str, params: dict = None, signed: bool = False):
        params = params or {}
        last_err = None
        for attempt in range(1, _MAX_RETRIES + 1):
            p = dict(params)
            if signed:
                p["timestamp"] = int(time.time() * 1000)
                p = self._sign(p)
            try:
                r = self.session.get(self.cfg.BASE_URL + endpoint, params=p, timeout=10)
                if r.status_code == 429:
                    wait = int(r.headers.get("Retry-After", 10))
                    logger.warning(f"Rate limited on {endpoint} — waiting {wait}s")
                    time.sleep(wait)
                    continue
                r.raise_for_status()
                return r.json()
            except (requests.ConnectionError, requests.Timeout) as e:
                last_err = e
                wait = _RETRY_BACKOFF * (2 ** (attempt - 1))
                logger.warning(f"GET {endpoint} attempt {attempt}/{_MAX_RETRIES} — retrying in {wait:.1f}s")
                time.sleep(wait)
                self.recycle_session()
            except requests.RequestException as e:
                logger.error(f"GET {endpoint} failed: {e}")
                return None
        logger.error(f"GET {endpoint} failed after {_MAX_RETRIES} attempts: {last_err}")
        return None

    def _post(self, endpoint: str, params: dict):
        last_err = None
        for attempt in range(1, _MAX_RETRIES + 1):
            p = dict(params)
            p["timestamp"] = int(time.time() * 1000)
            p = self._sign(p)
            try:
                r = self.session.post(self.cfg.BASE_URL + endpoint, params=p, timeout=10)
                if r.status_code == 429:
                    wait = int(r.headers.get("Retry-After", 10))
                    logger.warning(f"Rate limited on {endpoint} — waiting {wait}s")
                    time.sleep(wait)
                    continue
                r.raise_for_status()
                return r.json()
            except (requests.ConnectionError, requests.Timeout) as e:
                last_err = e
                wait = _RETRY_BACKOFF * (2 ** (attempt - 1))
                logger.warning(f"POST {endpoint} attempt {attempt}/{_MAX_RETRIES} — retrying in {wait:.1f}s")
                time.sleep(wait)
                self.recycle_session()
            except requests.RequestException as e:
                logger.error(f"POST {endpoint} failed: {e}")
                return None
        logger.error(f"POST {endpoint} failed after {_MAX_RETRIES} attempts: {last_err}")
        return None

    def ping(self) -> bool:
        return self._get("/api/v3/ping") is not None

    def get_all_balances(self) -> dict:
        data = self._get("/api/v3/account", signed=True)
        if not data:
            return {}
        return {
            b["asset"]: float(b["free"])
            for b in data.get("balances", [])
            if float(b["free"]) > 0
        }

    def get_usdt_balance(self) -> float:
        return self.get_all_balances().get("USDT", 0.0)

    def get_candles(self, symbol: str, interval: str, limit: int = 100) -> pd.DataFrame | None:
        data = self._get("/api/v3/klines", {"symbol": symbol, "interval": interval, "limit": limit})
        if not data:
            return None
        df = pd.DataFrame(data, columns=_KLINE_COLS)
        return df[_KEEP_COLS].astype(float)

    def get_current_price(self, symbol: str) -> float:
        data = self._get("/api/v3/ticker/price", {"symbol": symbol})
        return float(data["price"]) if data else 0.0

    def sync_positions(self, pairs: list) -> dict:
        balances = self.get_all_balances()
        synced = {}
        for pair in pairs:
            qty = balances.get(pair.replace("USDT", ""), 0.0)
            if qty > 0:
                self._positions[pair] = qty
                synced[pair] = qty
        return synced

    def get_position(self, symbol: str) -> float:
        return self._positions.get(symbol, 0.0)

    def place_order(self, symbol: str, side: str, quantity: float) -> dict | None:
        precision = _QTY_PRECISION.get(symbol, 4)
        qty_str   = f"{quantity:.{precision}f}"
        params    = {"symbol": symbol, "side": side, "type": "MARKET", "quantity": qty_str}
        if self.cfg.TESTNET:
            logger.info(f"[TESTNET] {side} {qty_str} {symbol}")
        order = self._post("/api/v3/order", params)
        if order and order.get("orderId"):
            if side == "BUY":
                self._positions[symbol] = float(qty_str)
            else:
                self._positions.pop(symbol, None)
            return order
        return None

    def cancel_all_orders(self, symbol: str):
        self._post("/api/v3/openOrders", {"symbol": symbol})
