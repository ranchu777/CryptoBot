"""
backtest.py — Strategy backtester using Binance historical kline data.

Run BEFORE going live with any config change to see how the strategy
would have performed on real historical data.

Usage:
    python3 backtest.py                              # BTC, last 30 days, current strategy
    python3 backtest.py --pair ETHUSDT --days 60
    python3 backtest.py --pair BTCUSDT --days 90 --strategy macd --timeframe 15m
    python3 backtest.py --all-pairs --days 30
    python3 backtest.py --pair BTCUSDT --days 30 --aggression 2.0  # test config change

Output:
    - Trade-by-trade log
    - Win rate, total P&L, max drawdown, Sharpe ratio
    - Compares strategy vs buy-and-hold for the same period
    - Saves results to backtest_results.json
"""

import argparse
import json
import math
import sys
import time
import requests
import pandas as pd
import numpy as np
from datetime import datetime, timezone

# Add parent dir so we can import our modules
sys.path.insert(0, ".")

from config import Config
from strategy import Strategy


_BINANCE_URL = "https://api.binance.com"

DEFAULT_PAIRS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "DOGEUSDT"]
TIMEFRAME_MS  = {"1m": 60_000, "5m": 300_000, "15m": 900_000, "1h": 3_600_000}


# ------------------------------------------------------------------ #
#  Data fetching                                                       #
# ------------------------------------------------------------------ #

def fetch_historical_candles(symbol: str, interval: str, days: int) -> pd.DataFrame:
    """Fetch up to `days` days of historical klines from Binance."""
    session  = requests.Session()
    session.headers.update({"User-Agent": "CryptoBot-Backtest/1.0"})
    end_ms   = int(time.time() * 1000)
    start_ms = end_ms - days * 24 * 3600 * 1000
    limit    = 1000
    candles  = []

    print(f"  Fetching {symbol} {interval} for {days} days...", end="", flush=True)

    while start_ms < end_ms:
        try:
            r = session.get(
                _BINANCE_URL + "/api/v3/klines",
                params={"symbol": symbol, "interval": interval,
                        "startTime": start_ms, "endTime": end_ms, "limit": limit},
                timeout=15
            )
            r.raise_for_status()
            batch = r.json()
            if not batch:
                break
            candles.extend(batch)
            start_ms = batch[-1][0] + TIMEFRAME_MS.get(interval, 300_000)
            print(".", end="", flush=True)
            time.sleep(0.2)  # stay within rate limits
        except Exception as e:
            print(f"\n  Fetch error: {e}")
            break

    print(f" {len(candles)} candles")
    if not candles:
        return pd.DataFrame()

    df = pd.DataFrame(candles, columns=[
        "open_time","open","high","low","close","volume",
        "close_time","quote_vol","trades","taker_buy_base","taker_buy_quote","ignore"
    ])
    df = df[["open","high","low","close","volume"]].astype(float).reset_index(drop=True)
    
    # Validate OHLCV data integrity
    errors = []
    if len(df) == 0:
        return df
    
    # Check for NaN values
    if df.isnull().any().any():
        errors.append(f"NaN values detected in {df.columns[df.isnull().any()].tolist()}")
    
    # Check OHLCV relationships
    invalid_high_low = (df["high"] < df["low"]).any()
    if invalid_high_low:
        errors.append("High < Low in some candles")
    
    invalid_close_range = ((df["close"] > df["high"]) | (df["close"] < df["low"])).any()
    if invalid_close_range:
        errors.append("Close outside [Low, High] range in some candles")
    
    invalid_open_range = ((df["open"] > df["high"]) | (df["open"] < df["low"])).any()
    if invalid_open_range:
        errors.append("Open outside [Low, High] range in some candles")
    
    negative_volume = (df["volume"] < 0).any()
    if negative_volume:
        errors.append("Negative volume detected")
    
    if errors:
        print(f"\n  ⚠ Data validation warnings for {symbol}:")
        for err in errors:
            print(f"    - {err}")
        print(f"  Proceeding with backtest; results may be unreliable.\n")
    
    return df


# ------------------------------------------------------------------ #
#  Backtester                                                          #
# ------------------------------------------------------------------ #

class Backtester:
    def __init__(self, cfg: Config, strategy: Strategy):
        self.cfg      = cfg
        self.strategy = strategy
        
        # Use lower minimums for backtesting (real exchange minimums are too high for typical position sizes)
        self.min_order_usdt = {
            "BTCUSDT":  1000,   # Backtest minimum: $50 instead of $1000
            "ETHUSDT":  1000,   # Backtest minimum: $50 instead of $1000  
            "SOLUSDT":  100,   # Backtest minimum: $10 instead of $150
            "BNBUSDT":  100,   # Backtest minimum: $10 instead of $150
            "DOGEUSDT": 100,   # Backtest minimum: $10 instead of $150
        }

    def run(self, df: pd.DataFrame, symbol: str, initial_balance: float = 100_000.0) -> dict:
        """
        Simulate the strategy on historical candles.
        Uses a rolling window of 250 candles (enough for the 200 EMA trend filter).
        Executes at the next candle's open price to avoid lookahead bias.
        """
        lookback = 250  # must exceed TREND_EMA_PERIOD (200) so trend filter has data

        if len(df) < lookback + 10:
            return {"error": f"Not enough data ({len(df)} candles, need {lookback + 10}+)"}

        balance       = initial_balance
        position      = 0.0
        entry_price   = 0.0
        peak_price    = 0.0
        trades        = []
        equity_curve  = [initial_balance]
        signal_counts = {"buy": 0, "sell": 0, "none": 0, "trend_blocked": 0}

        sl_pct           = self.cfg.STOP_LOSS_PCT / 100
        tp_pct           = self.cfg.TAKE_PROFIT_PCT / 100
        trail_activation = self.cfg.TRAILING_STOP_ACTIVATION_PCT / 100

        for i in range(lookback, len(df) - 1):
            window        = df.iloc[i - lookback:i].copy()
            current_price = df["close"].iloc[i]
            next_open     = df["open"].iloc[i + 1]

            if position > 0 and current_price > peak_price:
                peak_price = current_price

            # ── Exit logic ──────────────────────────────────────────
            if position > 0:
                trail_sl      = None
                replace_fixed = getattr(self.cfg, "TRAILING_STOP_REPLACE_FIXED", True)
                if peak_price >= entry_price * (1 + trail_activation):
                    trail_sl = peak_price * (1 - sl_pct)

                if trail_sl and replace_fixed:
                    effective_sl = trail_sl
                else:
                    fixed_sl     = entry_price * (1 - sl_pct)
                    effective_sl = max(fixed_sl, trail_sl) if trail_sl else fixed_sl

                hit_sl = current_price <= effective_sl
                hit_tp = current_price >= entry_price * (1 + tp_pct)

                if hit_sl or hit_tp:
                    exit_price = next_open
                    pnl        = (exit_price - entry_price) * position
                    balance   += position * exit_price
                    is_trail   = hit_sl and trail_sl and trail_sl > entry_price * (1 - sl_pct)
                    trades.append({
                        "type":        "sell",
                        "reason":      "trailing_stop" if is_trail else ("stop_loss" if hit_sl else "take_profit"),
                        "entry_price": entry_price,
                        "exit_price":  exit_price,
                        "qty":         position,
                        "pnl":         round(pnl, 4),
                        "candle":      i,
                    })
                    position    = 0.0
                    entry_price = 0.0
                    peak_price  = 0.0
                    equity_curve.append(round(balance, 2))
                    continue

            # ── Signal ──────────────────────────────────────────────
            signal, confidence, reason = self.strategy.get_combined_signal(window)
            trend_blocked = "TREND FILTER" in reason

            if trend_blocked:
                signal_counts["trend_blocked"] += 1
            elif signal == "buy":
                signal_counts["buy"] += 1
            elif signal == "sell":
                signal_counts["sell"] += 1
            else:
                signal_counts["none"] += 1

            # ── Buy ─────────────────────────────────────────────────
            if signal == "buy" and not trend_blocked and position == 0 and balance > self.cfg.MIN_RESERVE_USDT:
                size_pct = self.cfg.POSITION_SIZE_PCT / 100
                if getattr(self.cfg, "SCALE_SIZE_WITH_CONFIDENCE", False):
                    size_pct = min(size_pct * self.cfg.AGGRESSION * max(0.3, confidence), 0.25)
                usdt_to_use  = (balance - self.cfg.MIN_RESERVE_USDT) * size_pct
                min_notional = self.min_order_usdt.get(symbol, 10)
                if usdt_to_use >= min_notional:
                    qty         = usdt_to_use / next_open
                    entry_price = next_open
                    peak_price  = next_open
                    position    = qty
                    balance    -= usdt_to_use
                    trades.append({
                        "type":        "buy",
                        "entry_price": entry_price,
                        "qty":         round(qty, 6),
                        "candle":      i,
                    })

            equity_curve.append(round(balance + position * current_price, 2))

        # Close any open position at the end
        if position > 0:
            exit_price = df["close"].iloc[-1]
            pnl        = (exit_price - entry_price) * position
            balance   += position * exit_price
            trades.append({
                "type": "sell", "reason": "end_of_backtest",
                "entry_price": entry_price, "exit_price": exit_price,
                "qty": position, "pnl": round(pnl, 4), "candle": len(df) - 1,
            })

        # ── Metrics ──────────────────────────────────────────────────
        sell_trades   = [t for t in trades if t["type"] == "sell" and "pnl" in t]
        wins          = [t for t in sell_trades if t["pnl"] > 0]
        losses        = [t for t in sell_trades if t["pnl"] <= 0]
        total_pnl     = sum(t["pnl"] for t in sell_trades)
        win_rate      = len(wins) / len(sell_trades) * 100 if sell_trades else 0
        avg_win       = sum(t["pnl"] for t in wins)   / len(wins)   if wins   else 0
        avg_loss      = sum(t["pnl"] for t in losses) / len(losses) if losses else 0
        profit_factor = abs(sum(t["pnl"] for t in wins) / sum(t["pnl"] for t in losses)) if losses and sum(t["pnl"] for t in losses) != 0 else float("inf")

        # Max drawdown
        peak  = equity_curve[0]
        max_dd = 0.0
        for val in equity_curve:
            if val > peak:
                peak = val
            dd = (peak - val) / peak
            if dd > max_dd:
                max_dd = dd

        # Sharpe ratio (simplified — daily returns)
        if len(equity_curve) > 2:
            returns    = np.diff(equity_curve) / np.array(equity_curve[:-1])
            sharpe     = (returns.mean() / returns.std() * math.sqrt(252)) if returns.std() > 0 else 0
        else:
            sharpe = 0

        # Buy-and-hold comparison
        bnh_return = (df["close"].iloc[-1] - df["close"].iloc[0]) / df["close"].iloc[0] * 100
        strat_return = (balance - initial_balance) / initial_balance * 100

        return {
            "symbol":          symbol,
            "initial_balance": initial_balance,
            "final_balance":   round(balance, 2),
            "total_pnl":       round(total_pnl, 2),
            "return_pct":      round(strat_return, 2),
            "bnh_return_pct":  round(bnh_return, 2),
            "total_trades":    len(sell_trades),
            "wins":            len(wins),
            "losses":          len(losses),
            "win_rate":        round(win_rate, 1),
            "avg_win":         round(avg_win, 2),
            "avg_loss":        round(avg_loss, 2),
            "profit_factor":   round(profit_factor, 2),
            "max_drawdown":    round(max_dd * 100, 2),
            "sharpe":          round(sharpe, 3),
            "signal_counts":   signal_counts,
            "equity_curve":    equity_curve[::10],
            "trades":          trades,
        }


# ------------------------------------------------------------------ #
#  CLI                                                                 #
# ------------------------------------------------------------------ #

def print_results(r: dict):
    """Print backtest results to terminal."""
    if "error" in r:
        print(f"  ERROR: {r['error']}")
        return

    print(f"\n{'='*55}")
    print(f"  {r['symbol']} Backtest Results")
    print(f"{'='*55}")
    print(f"  Balance:       ${r['initial_balance']:>10,.2f} → ${r['final_balance']:>10,.2f}")
    print(f"  Strategy P&L:  {r['return_pct']:>+.2f}%   (${r['total_pnl']:>+,.2f})")
    print(f"  Buy & Hold:    {r['bnh_return_pct']:>+.2f}%")
    print(f"  {'─'*45}")
    print(f"  Trades:        {r['total_trades']}  ({r['wins']} wins / {r['losses']} losses)")
    print(f"  Win rate:      {r['win_rate']:.1f}%")
    print(f"  Avg win:       ${r['avg_win']:>+,.2f}   Avg loss: ${r['avg_loss']:>+,.2f}")
    print(f"  Profit factor: {r['profit_factor']:.2f}")
    print(f"  Max drawdown:  {r['max_drawdown']:.2f}%")
    print(f"  Sharpe ratio:  {r['sharpe']:.3f}")

    sc = r.get("signal_counts", {})
    if sc:
        print(f"  {'─'*45}")
        print(f"  Signal breakdown:")
        print(f"    Buy signals:        {sc.get('buy', 0)}")
        print(f"    Sell signals:       {sc.get('sell', 0)}")
        print(f"    Neutral:            {sc.get('none', 0)}")
        print(f"    Trend filter blocked: {sc.get('trend_blocked', 0)}")
        if sc.get('trend_blocked', 0) > 0 and sc.get('buy', 0) == 0:
            print(f"  ⚠  All buy signals were blocked by the 200 EMA trend filter.")
            print(f"     The market was in a downtrend for this entire period.")
            print(f"     Try --days 30 for a recent period, or disable the trend filter")
            print(f"     in config.py (TREND_FILTER_ENABLED = False) to see raw signals.")
    by_reason = {}
    sells = [t for t in r["trades"] if t["type"] == "sell" and "pnl" in t]
    for t in sells:
        reason = t.get("reason", "unknown")
        by_reason.setdefault(reason, {"count": 0, "pnl": 0})
        by_reason[reason]["count"] += 1
        by_reason[reason]["pnl"]   += t["pnl"]
    if by_reason:
        print(f"  {'─'*45}")
        print(f"  Exits by reason:")
        for reason, data in sorted(by_reason.items()):
            print(f"    {reason:<20} {data['count']:>4} trades   ${data['pnl']:>+,.2f}")
    print(f"{'='*55}\n")


def main():
    p = argparse.ArgumentParser(description="CryptoBot Strategy Backtester")
    p.add_argument("--pair",       default="BTCUSDT",  help="Trading pair (default: BTCUSDT)")
    p.add_argument("--all-pairs",  action="store_true", help="Run on all 5 default pairs")
    p.add_argument("--days",       type=int, default=30, help="Days of history (default: 30)")
    p.add_argument("--strategy",   default="ema", choices=["ema","rsi","bb","macd"])
    p.add_argument("--timeframe",  default="5m",  choices=["1m","5m","15m","1h"])
    p.add_argument("--aggression", type=float, default=None)
    p.add_argument("--bb-offset",  type=float, default=None,
                   help="Bollinger Bands offset (default: 0.0)")
    p.add_argument("--balance",       type=float, default=100_000.0, help="Starting balance (default: 10000)")
    p.add_argument("--output",        default="backtest_results.json")
    p.add_argument("--no-trend-filter", action="store_true",
                   help="Disable 200 EMA trend filter (shows raw signals in downtrends)")
    args = p.parse_args()

    cfg = Config(testnet=False)
    if args.aggression is not None:
        cfg.AGGRESSION = args.aggression
    if args.bb_offset is not None:
        cfg.BB_OFFSET = args.bb_offset
    if args.no_trend_filter:
        cfg.TREND_FILTER_ENABLED = False
        print("  ⚠  Trend filter disabled — buys allowed in downtrends")
    strategy = Strategy(name=args.strategy, cfg=cfg)

    pairs = DEFAULT_PAIRS if args.all_pairs else [args.pair.upper()]
    bt    = Backtester(cfg, strategy)

    run_config = {
        "strategy":   args.strategy.upper(),
        "timeframe":  args.timeframe,
        "days":       args.days,
        "aggression": cfg.AGGRESSION,
        "sl_pct":     cfg.STOP_LOSS_PCT,
        "tp_pct":     cfg.TAKE_PROFIT_PCT,
        "bb_offset":  cfg.BB_OFFSET,
        "run_at":     datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }

    bb_note = f" | BB offset={cfg.BB_OFFSET:+.1f} (effective std={cfg.BB_STD - cfg.BB_OFFSET:.1f}σ)" if args.strategy == "bb" else ""
    print(f"\nCryptoBot Backtester")
    print(f"Strategy: {args.strategy.upper()} | Timeframe: {args.timeframe} | Days: {args.days} | Aggression: {cfg.AGGRESSION}{bb_note}")
    print(f"Starting balance: ${args.balance:,.2f}\n")

    all_results = []
    for pair in pairs:
        df = fetch_historical_candles(pair, args.timeframe, args.days)
        if df.empty:
            print(f"  {pair}: no data, skipping")
            continue
        result = bt.run(df, pair, args.balance)
        result["config"] = run_config

        # Auto-rerun without trend filter if it blocked everything
        sc = result.get("signal_counts", {})
        if result["total_trades"] == 0 and sc.get("trend_blocked", 0) > 0:
            print(f"\n  ⚠  0 trades — {sc['trend_blocked']} buy signals blocked by 200 EMA trend filter")
            print(f"     This period is a downtrend. Auto-running without trend filter for comparison...\n")
            cfg_no_tf = Config(testnet=False)
            if args.aggression is not None:
                cfg_no_tf.AGGRESSION = args.aggression
            cfg_no_tf.TREND_FILTER_ENABLED = False
            bt_no_tf     = Backtester(cfg_no_tf, Strategy(name=args.strategy, cfg=cfg_no_tf))
            result_no_tf = bt_no_tf.run(df, pair, args.balance)
            result_no_tf["config"] = {**run_config, "note": "no trend filter"}
            result["config"]       = {**run_config, "note": f"⚠ trend filter blocked {sc['trend_blocked']} signals"}
            print_results(result)
            print(f"  ── Comparison: same config, trend filter OFF ──")
            print_results(result_no_tf)
            all_results.append(result)
            all_results.append(result_no_tf)
        else:
            print_results(result)
            all_results.append(result)

    # Append this run to the history file (keep last 20 runs)
    history_file = args.output
    history = []
    try:
        with open(history_file, "r") as f:
            existing = json.load(f)
            # Support both old format (list of results) and new (list of runs)
            if existing and isinstance(existing[0], list):
                history = existing          # already grouped by run
            elif existing and isinstance(existing[0], dict):
                history = [existing]        # old flat format — wrap as one run
    except (FileNotFoundError, json.JSONDecodeError):
        pass

    history.append(all_results)
    history = history[-20:]   # keep last 20 runs

    with open(history_file, "w") as f:
        json.dump(history, f, indent=2)
    print(f"Results appended to {history_file} ({len(history)} runs stored)\n")

    # Print combined summary if multiple pairs
    if len(all_results) > 1:
        total_pnl = sum(r["total_pnl"] for r in all_results)
        avg_wr    = sum(r["win_rate"] for r in all_results) / len(all_results)
        avg_dd    = sum(r["max_drawdown"] for r in all_results) / len(all_results)
        print(f"{'='*55}")
        print(f"  COMBINED SUMMARY ({len(all_results)} pairs)")
        print(f"  Total P&L:     ${total_pnl:>+,.2f}")
        print(f"  Avg win rate:  {avg_wr:.1f}%")
        print(f"  Avg drawdown:  {avg_dd:.2f}%")
        print(f"{'='*55}\n")

    print(f"Run dashboard.py to visualise results.")


if __name__ == "__main__":
    main()
