"""
risk.py — Position sizing, stop loss, take profit, and trade tracking.

Entry prices are persisted to positions.json so real buy prices survive
bot restarts. Synced positions (pre-existing at startup) are tracked
separately and display as unknown buy price until the bot places its own order.
"""

import json
import logging
import os
import tempfile
from datetime import datetime, timezone

logger = logging.getLogger("cryptobot")

_POSITIONS_FILE = "positions.json"


class RiskManager:
    def __init__(self, cfg):
        self.cfg = cfg
        self._entries   = {}
        self._trade_log = []
        self._total_pnl = 0.0
        self._wins      = 0
        self._losses    = 0
        self._session_start_balance = None   # set on first cycle
        self._buys_halted           = False  # True when drawdown limit hit
        self._load_positions()

    # ------------------------------------------------------------------ #
    #  Persistence                                                         #
    # ------------------------------------------------------------------ #

    def _load_positions(self):
        """Load saved entry prices from disk on startup."""
        if not os.path.exists(_POSITIONS_FILE):
            return
        try:
            with open(_POSITIONS_FILE, "r") as f:
                saved = json.load(f)
            for symbol, data in saved.items():
                self._entries[symbol] = {
                    "price":      float(data["price"]),
                    "qty":        float(data["qty"]),
                    "time":       data.get("time", ""),
                    "synced":     False,
                    "known":      True,
                    "addons":     int(data.get("addons", 0)),
                    "addon_qty":  float(data.get("addon_qty", data["qty"])),
                    "peak_price": float(data.get("peak_price", data["price"])),
                }
            if self._entries:
                logger.info(f"Loaded {len(self._entries)} saved positions: {list(self._entries.keys())}")
        except Exception as e:
            logger.warning(f"Could not load positions.json: {e}")

    def _save_positions(self):
        """Write current known entry prices to disk using atomic writes."""
        to_save = {
            sym: {
                "price":      e["price"],
                "qty":        e["qty"],
                "time":       e.get("time", ""),
                "addons":     e.get("addons", 0),
                "addon_qty":  e.get("addon_qty", e["qty"]),
                "peak_price": e.get("peak_price", e["price"]),
            }
            for sym, e in self._entries.items()
            if e.get("known", False)
        }
        try:
            # Atomic write: write to temp file first, then rename
            temp_fd, temp_path = tempfile.mkstemp(suffix='.json', dir='.')
            try:
                with os.fdopen(temp_fd, 'w') as f:
                    json.dump(to_save, f, indent=2)
                os.replace(temp_path, _POSITIONS_FILE)
            except Exception:
                # Clean up temp file on error
                try:
                    os.unlink(temp_path)
                except Exception:
                    pass
                raise
        except Exception as e:
            logger.warning(f"Could not save positions.json: {e}")

    # ------------------------------------------------------------------ #
    #  Position tracking                                                   #
    # ------------------------------------------------------------------ #

    def check_drawdown(self, current_balance: float) -> bool:
        """
        Check if session drawdown exceeds MAX_DRAWDOWN_PCT.
        Call once per cycle with the current USDT balance.
        Returns True if buys should be halted, False if trading can continue.
        """
        if not getattr(self.cfg, "DRAWDOWN_CIRCUIT_BREAKER", True):
            return False

        # Record starting balance on first call
        if self._session_start_balance is None:
            self._session_start_balance = current_balance
            logger.info(f"Drawdown circuit breaker armed — session start balance: {current_balance:.2f} USDT")
            return False

        # Safety check: prevent division by zero
        if self._session_start_balance <= 0:
            logger.warning("Session start balance is <= 0, cannot calculate drawdown")
            return False

        max_dd = getattr(self.cfg, "MAX_DRAWDOWN_PCT", 5.0) / 100
        drawdown = (self._session_start_balance - current_balance) / self._session_start_balance

        if drawdown >= max_dd and not self._buys_halted:
            self._buys_halted = True
            logger.warning(
                f"DRAWDOWN CIRCUIT BREAKER TRIGGERED — "
                f"session loss {drawdown:.1%} exceeds limit {max_dd:.1%}. "
                f"New buys halted. Existing positions still managed by SL/TP."
            )
        elif drawdown < max_dd and self._buys_halted:
            # Balance recovered — re-enable buys
            self._buys_halted = False
            logger.info(f"Drawdown recovered to {drawdown:.1%} — buys re-enabled.")

        return self._buys_halted

    def calculate_quantity(
        self,
        balance: float,
        price: float,
        symbol: str,
        confidence: float = 1.0,
    ) -> float | None:
        if price <= 0:
            return None
        if len(self._entries) >= self.cfg.MAX_POSITIONS:
            logger.debug(f"Max positions ({self.cfg.MAX_POSITIONS}) reached, skipping {symbol}")
            return None

        # Validate symbol has a defined minimum order size
        if symbol not in self.cfg.MIN_ORDER_USDT:
            logger.error(
                f"Symbol {symbol} not found in MIN_ORDER_USDT config. "
                f"Valid symbols: {list(self.cfg.MIN_ORDER_USDT.keys())}"
            )
            return None

        tradeable = max(0, balance - self.cfg.MIN_RESERVE_USDT)
        size_pct  = self.cfg.POSITION_SIZE_PCT / 100
        if getattr(self.cfg, "SCALE_SIZE_WITH_CONFIDENCE", False):
            size_pct = min(size_pct * self.cfg.AGGRESSION * max(0.3, confidence), 0.25)

        usdt_to_use = tradeable * size_pct
        min_notional = self.cfg.MIN_ORDER_USDT[symbol]
        if usdt_to_use < min_notional:
            logger.debug(f"{symbol}: order too small ({usdt_to_use:.2f} USDT < min {min_notional})")
            return None

        return round(usdt_to_use / price, 6)

    def record_entry(self, symbol: str, price: float, qty: float, synced: bool = False):
        """
        Record a fresh position entry (resets add-on counter).
        synced=True  — pre-existing position, price is current market price
        synced=False — bot placed this order, price is the real buy price
        """
        known = not synced
        self._entries[symbol] = {
            "price":      price,
            "qty":        qty,
            "time":       datetime.now(timezone.utc).isoformat(),
            "synced":     synced,
            "known":      known,
            "addons":     0,
            "addon_qty":  qty,
            "peak_price": price,   # highest price seen since entry — for trailing stop
        }
        if known:
            self._save_positions()
            logger.debug(f"Entry saved: {symbol} @ {price:.4f} x {qty}")
        else:
            logger.debug(f"Entry synced (unknown buy price): {symbol} @ {price:.4f} x {qty}")

    def update_peak(self, symbol: str, current_price: float):
        """
        Update the highest price seen since entry for trailing stop calculation.
        Call every cycle for open positions.
        """
        entry = self._entries.get(symbol)
        if entry and current_price > entry.get("peak_price", 0):
            entry["peak_price"] = current_price
            # Persist so peak survives restarts — only save when peak actually moves
            if entry.get("known", False):
                self._save_positions()

    def get_trailing_stop(self, symbol: str) -> float | None:
        """
        Return the trailing stop price for a position, or None if not yet active.

        The trailing stop activates only after price gains TRAILING_STOP_ACTIVATION_PCT
        above the entry price (default +2%). Once active, it sits STOP_LOSS_PCT% below
        the peak price seen since entry.

        Returns None if:
          - No entry recorded
          - Entry price unknown (synced position)
          - Price hasn't gained enough to activate the trailing stop yet
        """
        entry = self._entries.get(symbol)
        if not entry or not entry.get("known", False):
            return None

        entry_price  = entry["price"]
        peak_price   = entry.get("peak_price", entry_price)
        activation   = getattr(self.cfg, "TRAILING_STOP_ACTIVATION_PCT", 2.0) / 100
        trail_pct    = self.cfg.STOP_LOSS_PCT / 100

        # Only activate after sufficient gain from entry
        if peak_price < entry_price * (1 + activation):
            return None

        return round(peak_price * (1 - trail_pct), 8)

    def can_add_to_position(self, symbol: str) -> bool:
        """
        Return True if an add-on buy is allowed for this symbol.
        Requires:
          - An open known position exists
          - Add-on count is below the configured maximum
          - Position was not synced at startup (we need a real entry price)
        """
        entry = self._entries.get(symbol)
        if not entry:
            return False
        if not entry.get("known", False):
            return False
        max_addons = getattr(self.cfg, "PYRAMID_MAX_ADDONS", 2)
        return entry.get("addons", 0) < max_addons

    def calculate_addon_quantity(
        self,
        balance: float,
        price: float,
        symbol: str,
    ) -> float | None:
        """
        Calculate the quantity for an add-on buy.
        Add-on size = PYRAMID_ADDON_SIZE_PCT (25%) of the original entry value.
        """
        entry = self._entries.get(symbol)
        if not entry or price <= 0:
            return None

        # Validate symbol has a defined minimum order size
        if symbol not in self.cfg.MIN_ORDER_USDT:
            logger.error(f"Symbol {symbol} not found in MIN_ORDER_USDT config")
            return None

        original_qty   = entry.get("addon_qty", entry["qty"])
        addon_size_pct = getattr(self.cfg, "PYRAMID_ADDON_SIZE_PCT", 0.25)
        addon_usdt     = original_qty * entry["price"] * addon_size_pct

        min_notional = self.cfg.MIN_ORDER_USDT[symbol]
        tradeable    = max(0, balance - self.cfg.MIN_RESERVE_USDT)

        if addon_usdt < min_notional:
            logger.debug(f"{symbol} addon too small ({addon_usdt:.2f} USDT < min {min_notional})")
            return None
        if addon_usdt > tradeable:
            logger.debug(f"{symbol} addon exceeds available balance")
            return None

        return round(addon_usdt / price, 6)

    def record_addon(self, symbol: str, price: float, qty: float):
        """
        Record an add-on buy. Updates the average entry price and total quantity.
        Average price = (existing_value + addon_value) / total_qty
        """
        entry = self._entries.get(symbol)
        if not entry:
            return

        old_qty   = entry["qty"]
        old_price = entry["price"]

        # Weighted average entry price
        total_qty   = old_qty + qty
        avg_price   = (old_price * old_qty + price * qty) / total_qty

        entry["price"]   = round(avg_price, 8)
        entry["qty"]     = round(total_qty, 8)
        entry["addons"]  = entry.get("addons", 0) + 1
        entry["time"]    = datetime.now(timezone.utc).isoformat()

        self._save_positions()
        logger.info(
            f"  Add-on #{entry['addons']} recorded: {symbol} "
            f"+{qty} @ {price:.4f} | avg entry now {avg_price:.4f} | "
            f"total qty {total_qty:.6f}"
        )

    def is_synced(self, symbol: str) -> bool:
        return self._entries.get(symbol, {}).get("synced", False)

    def clear_synced_flag(self, symbol: str):
        if symbol in self._entries:
            self._entries[symbol]["synced"] = False

    def get_entry_price(self, symbol: str) -> float:
        """Return entry price, or 0.0 if unknown."""
        entry = self._entries.get(symbol)
        return entry["price"] if entry else 0.0

    def get_entry_known(self, symbol: str) -> bool:
        """Return True if the entry price is a real buy price (not a synced estimate)."""
        return self._entries.get(symbol, {}).get("known", False)

    def get_addon_count(self, symbol: str) -> int:
        """Return the number of add-ons placed for this position."""
        return self._entries.get(symbol, {}).get("addons", 0)

    def is_open(self, symbol: str) -> bool:
        return symbol in self._entries

    def record_exit(self, symbol: str, exit_price: float = None):
        entry = self._entries.pop(symbol, None)
        if not entry:
            return
        self._save_positions()
        if exit_price is not None and entry.get("known", False):
            # Use the average entry price and total qty for accurate P&L
            pnl = (exit_price - entry["price"]) * entry["qty"]
            self._total_pnl += pnl
            if pnl >= 0:
                self._wins += 1
            else:
                self._losses += 1
            addons = entry.get("addons", 0)
            self._trade_log.append({
                "symbol":      symbol,
                "entry_price": entry["price"],
                "exit_price":  exit_price,
                "qty":         entry["qty"],
                "pnl":         pnl,
                "addons":      addons,
                "time":        datetime.now(timezone.utc).isoformat()
            })

    def print_summary(self):
        total    = self._wins + self._losses
        win_rate = (self._wins / total * 100) if total > 0 else 0
        logger.info("=" * 50)
        logger.info("SESSION SUMMARY")
        logger.info(f"  Total trades : {total}")
        logger.info(f"  Wins         : {self._wins}")
        logger.info(f"  Losses       : {self._losses}")
        logger.info(f"  Win rate     : {win_rate:.1f}%")
        logger.info(f"  Total P&L    : {self._total_pnl:+.2f} USDT")
        logger.info("=" * 50)
        if self._trade_log:
            logger.info("Individual trades:")
            for t in self._trade_log:
                addons_str = f" (+{t['addons']} add-ons)" if t.get("addons") else ""
                logger.info(
                    f"  {t['symbol']} | avg_entry={t['entry_price']:.4f} "
                    f"exit={t['exit_price']:.4f} | P&L={t['pnl']:+.2f} USDT{addons_str}"
                )
