"""
CryptoBot — Binance Algo Trader
================================
Supports: BTC/USDT, ETH/USDT, SOL/USDT, BNB/USDT, DOGE/USDT
Strategies: EMA Crossover, RSI Reversal, Bollinger Bands, MACD
News: CryptoPanic sentiment blended with technical signals
Run in TESTNET mode first (default). Set --live only when ready.

Usage:
    python bot.py                         # testnet, EMA strategy
    python bot.py --strategy rsi          # RSI strategy
    python bot.py --aggression 1.8        # bolder trading
    python bot.py --live                  # REAL MONEY — be careful
"""

import time
import argparse
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from config import Config
from exchange import BinanceClient
from strategy import Strategy
from risk import RiskManager
from news import NewsSentiment
from smart_money import SmartMoneyTracker
from calendar_events import EconomicCalendar
from market_filters import MarketFilters
from multi_timeframe import MultiTimeframe
from logger import setup_logger

def parse_args():
    p = argparse.ArgumentParser(description="Binance Crypto Algo Bot")
    p.add_argument("--strategy", default="ema",
                   choices=["ema", "rsi", "bb", "macd"],
                   help="Trading strategy (default: ema)")
    p.add_argument("--pairs", nargs="+",
                   default=["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "DOGEUSDT"],
                   help="Trading pairs (default: all 5)")
    p.add_argument("--timeframe", default="5m",
                   choices=["1m", "5m", "15m", "1h"],
                   help="Candle timeframe (default: 5m)")
    p.add_argument("--aggression", type=float, default=None,
                   help="Override aggression level from config (e.g. 1.5 = bold, 2.0 = aggressive)")
    p.add_argument("--bb-offset", type=float, default=None,
                   help="Bollinger Bands offset — shifts bands inward (+) or outward (-). Default: 0.0")
    p.add_argument("--no-news", action="store_true",
                   help="Disable news sentiment (use technical signals only)")
    p.add_argument("--live", action="store_true",
                   help="Use LIVE account (default: testnet)")
    p.add_argument("--sell", nargs="+", metavar="PAIR",
                   help="Immediately sell specific pairs and exit (e.g. --sell BTCUSDT ETHUSDT)")
    p.add_argument("--sell-all", action="store_true",
                   help="Immediately sell all open positions and exit")
    return p.parse_args()


def execute_manual_sell(pairs_to_sell: list, client, risk, logger):
    """
    Immediately sell the given pairs at market price and exit.
    Shows a summary table of each sale before quitting.
    """
    logger.info("=" * 50)
    logger.info(f"MANUAL SELL — {len(pairs_to_sell)} pair(s): {pairs_to_sell}")
    logger.info("=" * 50)

    all_balances = client.get_all_balances()
    results = []

    for pair in pairs_to_sell:
        base = pair.replace("USDT", "")
        qty  = all_balances.get(base, 0.0)

        if qty <= 0:
            logger.warning(f"  {pair}: no balance found — skipping")
            results.append((pair, 0, 0, 0, "no balance"))
            continue

        current_price = client.get_current_price(pair)
        if current_price <= 0:
            logger.warning(f"  {pair}: could not fetch price — skipping")
            results.append((pair, qty, 0, 0, "price error"))
            continue

        entry_price = risk.get_entry_price(pair)
        entry_known = risk.get_entry_known(pair)

        order = client.place_order(pair, "SELL", qty)
        if order:
            if entry_known and entry_price > 0:
                gain     = (current_price - entry_price) * qty
                gain_pct = (current_price - entry_price) / entry_price * 100
                pnl_str  = f"{gain:+,.2f} USDT ({gain_pct:+.2f}%)"
            else:
                gain    = 0.0
                pnl_str = "— (buy price unknown)"

            risk.record_exit(pair, exit_price=current_price if entry_known else None)
            logger.info(f"  SOLD {pair} | qty={qty} @ {current_price:.4f} | P&L={pnl_str}")
            results.append((pair, qty, entry_price if entry_known else 0, current_price, pnl_str))
        else:
            logger.error(f"  {pair}: order failed")
            results.append((pair, qty, 0, current_price, "ORDER FAILED"))

    # Summary table
    logger.info("")
    logger.info("SELL SUMMARY")
    logger.info(f"  {'Pair':<10} {'Qty':<14} {'Bought At':>12} {'Sold At':>12} {'P&L'}")
    logger.info(f"  {'-'*10} {'-'*14} {'-'*12} {'-'*12} {'-'*24}")
    for pair, qty, entry, sold, pnl in results:
        entry_s = f"{entry:,.4f}" if entry > 0 else "—"
        sold_s  = f"{sold:,.4f}"  if sold  > 0 else "—"
        logger.info(f"  {pair:<10} {qty:<14.5f} {entry_s:>12} {sold_s:>12} {pnl}")
    logger.info("=" * 50)


def main():
    args = parse_args()

    logger = setup_logger("cryptobot", "logs/bot.log")
    logger.info("=" * 50)
    logger.info(f"CryptoBot starting — mode: {'LIVE' if args.live else 'TESTNET'}")
    logger.info(f"Strategy: {args.strategy.upper()} | Pairs: {args.pairs}")
    logger.info(f"Timeframe: {args.timeframe}")
    logger.info("=" * 50)

    cfg = Config(testnet=not args.live)

    # Validate trading pairs
    valid_pairs = set(cfg.DEFAULT_PAIRS)
    invalid_pairs = [p for p in args.pairs if p not in valid_pairs]
    if invalid_pairs:
        logger.error(
            f"Invalid trading pairs: {invalid_pairs}. "
            f"Valid pairs are: {list(valid_pairs)}"
        )
        return
    
    # Validate pair has min order size defined
    for pair in args.pairs:
        if pair not in cfg.MIN_ORDER_USDT:
            logger.error(f"Pair {pair} missing from MIN_ORDER_USDT config")
            return

    # CLI aggression override
    if args.aggression is not None:
        cfg.AGGRESSION = args.aggression
        logger.info(f"Aggression overridden to {cfg.AGGRESSION}")

    if args.bb_offset is not None:
        cfg.BB_OFFSET = args.bb_offset
        logger.info(f"BB offset overridden to {cfg.BB_OFFSET} (effective std={cfg.BB_STD - cfg.BB_OFFSET:.1f}σ)")

    client      = BinanceClient(cfg)
    strategy    = Strategy(name=args.strategy, cfg=cfg)
    risk        = RiskManager(cfg)
    news        = NewsSentiment(cfg) if not args.no_news else None
    smart_money = SmartMoneyTracker(cfg) if cfg.SMART_MONEY_ENABLED else None
    calendar    = EconomicCalendar(cfg) if cfg.CALENDAR_ENABLED else None
    mkt_filters = MarketFilters(cfg)
    mtf         = MultiTimeframe(cfg, client, strategy)

    logger.info(
        f"Mode: aggression={cfg.AGGRESSION} | "
        f"weights: tech={cfg.TECHNICAL_WEIGHT} news={cfg.NEWS_WEIGHT} "
        f"sm={cfg.SMART_MONEY_WEIGHT} cal={cfg.CALENDAR_WEIGHT} "
        f"fng={cfg.FNG_WEIGHT} fund={cfg.FUNDING_WEIGHT}"
    )

    # Single call covers balance display AND position sync
    startup_balances = client.get_all_balances()
    balance = startup_balances.get("USDT", 0.0)
    logger.info(f"Connected. USDT balance: {balance:.2f}")

    # Sync any pre-existing positions from the exchange so SL/TP works on them.
    # Skip pairs already loaded from positions.json — those have the real buy price.
    existing = client.sync_positions(args.pairs)
    if existing:
        logger.info(f"Found existing positions: {existing}")
        for pair, qty in existing.items():
            if risk.get_entry_known(pair):
                # Real buy price already loaded from positions.json — don't overwrite it
                logger.info(f"  {pair}: buy price restored from disk @ {risk.get_entry_price(pair):.4f}")
            else:
                # No saved price — seed with current market price for SL/TP tracking
                seed_price = client.get_current_price(pair)
                if seed_price > 0:
                    risk.record_entry(pair, seed_price, qty, synced=True)
                    logger.info(f"  {pair}: seeded entry @ {seed_price:.4f} (buy price unknown)")
    else:
        logger.info("No pre-existing positions found.")

    if args.live:
        logger.warning("LIVE MODE ACTIVE — real funds in use!")
        input("Press ENTER to confirm you want to trade with real money... ")

    # ── Manual sell commands — execute and exit immediately ───────────
    if args.sell_all or args.sell:
        if args.sell_all:
            # Sell everything found on the exchange
            all_balances = client.get_all_balances()
            pairs_to_sell = [
                p for p in args.pairs
                if all_balances.get(p.replace("USDT", ""), 0.0) > 0
            ]
            if not pairs_to_sell:
                logger.info("--sell-all: no open positions found.")
                return
        else:
            # Normalise input — accept both "BTC" and "BTCUSDT"
            pairs_to_sell = [
                p if p.endswith("USDT") else p + "USDT"
                for p in args.sell
            ]

        if args.live:
            confirm = input(f"Confirm LIVE sell of {pairs_to_sell}? (yes/no): ")
            if confirm.strip().lower() != "yes":
                logger.info("Sell cancelled.")
                return

        execute_manual_sell(pairs_to_sell, client, risk, logger)
        return   # exit after selling — don't start the trading loop
    # ──────────────────────────────────────────────────────────────────

    logger.info("Bot running. Press Ctrl+C to stop.\n")

    sleep_map = {"1m": 60, "5m": 300, "15m": 900, "1h": 3600}
    sleep_sec = sleep_map.get(args.timeframe, 300)

    def fetch_candles(pair):
        """Fetch candles for one pair — runs in a thread."""
        candles = client.get_candles(pair, args.timeframe, limit=100)
        return pair, candles

    def process_pair(pair, candles, balance, news_scores, sm_scores, cal_score=0.0,
                     fng_score=0.0, funding_scores=None, oi_scores=None, btc_candles=None):
        """Evaluate combined signal and execute orders for one pair."""
        if candles is None or len(candles) < 30:
            logger.warning(f"{pair}: not enough candle data, skipping")
            return

        base           = pair.replace("USDT", "")
        news_score     = news_scores.get(base, 0.0)    if news_scores    else 0.0
        sm_score       = sm_scores.get(base, 0.0)      if sm_scores      else 0.0
        funding_score  = funding_scores.get(base, 0.0) if funding_scores else 0.0

        signal, confidence, reason = strategy.get_combined_signal(
            candles, news_score, sm_score, cal_score, fng_score, funding_score
        )
        current_price = candles["close"].iloc[-1]
        position      = client.get_position(pair)

        logger.debug(f"{pair} | price={current_price:.4f} | signal={signal} | conf={confidence:.2f} | {reason}")

        # ---- News circuit breakers ----
        # If news is very bearish, block new buys regardless of technical signal
        if signal == "buy" and news_score < cfg.NEWS_BLOCK_BUY_BELOW:
            logger.info(
                f"{pair}: BUY blocked — news too bearish "
                f"(score={news_score:+.3f} < {cfg.NEWS_BLOCK_BUY_BELOW})"
            )
            return
        # If news is very bullish, don't force-sell into positive momentum
        if signal == "sell" and news_score > cfg.NEWS_BLOCK_SELL_ABOVE and position > 0:
            logger.info(
                f"{pair}: SELL suppressed — news strongly bullish "
                f"(score={news_score:+.3f} > {cfg.NEWS_BLOCK_SELL_ABOVE})"
            )
            return

        # ---- BUY logic ----
        if signal == "buy" and position == 0:
            if risk.check_drawdown(balance):
                logger.info(f"{pair}: BUY blocked — drawdown circuit breaker active")
                return

            # BTC correlation filter — block ALT buys if BTC is dropping sharply
            if not mkt_filters.check_btc_correlation(btc_candles, pair):
                return

            # Multi-timeframe confirmation
            mtf_ok, confidence = mtf.check_alignment(pair, signal, confidence)
            if not mtf_ok:
                return

            # Volatility filter — scale position size or skip entirely
            vol_mult = mkt_filters.get_volatility_multiplier(candles)
            if vol_mult == 0.0:
                logger.info(f"{pair}: BUY skipped — extreme volatility")
                return

            qty = risk.calculate_quantity(balance, current_price, pair, confidence)
            if qty and qty > 0:
                qty = round(qty * vol_mult, 6)   # reduce size in high volatility
                order = client.place_order(pair, "BUY", qty)
                if order:
                    risk.record_entry(pair, current_price, qty)
                    oi_note = f" oi={oi_scores.get(base, 0.0):+.2f}" if oi_scores else ""
                    logger.info(
                        f"BUY  {pair} | qty={qty} @ {current_price:.4f} | "
                        f"conf={confidence:.0%} | vol_mult={vol_mult:.1f}{oi_note}"
                    )

        # ---- ADD-ON logic (pyramiding into existing position) ----
        elif (signal == "buy" and position > 0
              and getattr(cfg, "PYRAMID_ENABLED", False)
              and risk.can_add_to_position(pair)):

            conf_ok = confidence >= cfg.PYRAMID_MIN_CONFIDENCE

            if conf_ok:
                if risk.check_drawdown(balance):
                    logger.info(f"{pair}: ADD-ON blocked — drawdown circuit breaker active")
                else:
                    addon_qty = risk.calculate_addon_quantity(balance, current_price, pair)
                    if addon_qty and addon_qty > 0:
                        order = client.place_order(pair, "BUY", addon_qty)
                        if order:
                            addon_num = risk.get_addon_count(pair) + 1
                            risk.record_addon(pair, current_price, addon_qty)
                            logger.info(
                                f"ADD-ON #{addon_num} {pair} | qty={addon_qty} @ {current_price:.4f} | "
                                f"conf={confidence:.0%} | news={news_score:+.3f}"
                            )
            else:
                logger.debug(
                    f"{pair}: add-on skipped — conf={confidence:.0%} < {cfg.PYRAMID_MIN_CONFIDENCE:.0%} required"
                )

        # ---- SELL / exit logic — SL/TP only ----
        elif position > 0:
            entry = risk.get_entry_price(pair)
            sl    = cfg.STOP_LOSS_PCT / 100
            tp    = cfg.TAKE_PROFIT_PCT / 100

            # Update peak price for trailing stop
            if entry > 0:
                risk.update_peak(pair, current_price)

            # Fixed stop loss (always active until trailing takes over)
            fixed_sl_price = entry * (1 - sl) if entry > 0 else 0.0

            # Trailing stop (activates after +1% gain, trails 3% below peak)
            trailing_sl_price = 0.0
            if entry > 0 and getattr(cfg, "TRAILING_STOP_ENABLED", True):
                trailing_sl_price = risk.get_trailing_stop(pair) or 0.0

            # Once trailing is active it fully replaces the fixed stop
            replace_fixed = getattr(cfg, "TRAILING_STOP_REPLACE_FIXED", True)
            if trailing_sl_price > 0 and replace_fixed:
                effective_sl  = trailing_sl_price
                is_trailing   = True
            else:
                effective_sl  = fixed_sl_price
                is_trailing   = False

            hit_sl = effective_sl > 0 and current_price <= effective_sl
            hit_tp = entry > 0 and current_price >= entry * (1 + tp)

            reason_exit = None
            if hit_sl:   reason_exit = "trailing stop" if is_trailing else "stop loss"
            elif hit_tp: reason_exit = "take profit"

            if reason_exit:
                order = client.place_order(pair, "SELL", position)
                if order:
                    gain = (current_price - entry) * position
                    risk.record_exit(pair, exit_price=current_price)
                    logger.info(
                        f"SELL {pair} | qty={position} @ {current_price:.4f} | "
                        f"P&L={gain:+.2f} USDT | reason={reason_exit} | "
                        f"conf={confidence:.0%} | news={news_score:+.3f}"
                    )
            else:
                peak = risk._entries.get(pair, {}).get("peak_price", entry)
                trail_str = f"{trailing_sl_price:.4f}" if trailing_sl_price else "inactive"
                logger.debug(
                    f"{pair} holding | entry={entry:.4f} | peak={peak:.4f} | "
                    f"fixed_sl={fixed_sl_price:.4f} | trail_sl={trail_str} | "
                    f"tp={entry*(1+tp):.4f} | current={current_price:.4f}"
                )

    def fetch_news():
        return news.get_scores() if news else {}

    def fetch_smart_money():
        return smart_money.get_scores() if smart_money else {}

    def fetch_calendar():
        if not calendar:
            return 0.0, []
        score, events = calendar.get_score()
        if events:
            calendar.log_active_events(events, score)
        return score, events

    def fetch_market_filters():
        fng      = mkt_filters.get_fear_greed_score()
        funding  = mkt_filters.get_funding_scores()
        return fng, funding

    try:
        while True:
            client.recycle_session()

            # Single account call covers both balance check and holdings table
            all_balances = client.get_all_balances()
            balance      = all_balances.get("USDT", 0.0)

            # Update drawdown circuit breaker with current balance
            buys_halted = risk.check_drawdown(balance)
            if buys_halted:
                logger.info("Drawdown limit active — monitoring positions, no new buys this cycle")

            # Fetch all signals in parallel
            candle_data  = {}
            news_scores  = {}
            sm_scores    = {}
            cal_score    = 0.0
            fng_score    = 0.0
            funding_scores = {}

            with ThreadPoolExecutor(max_workers=len(args.pairs) + 4) as executor:
                news_future  = executor.submit(fetch_news)
                sm_future    = executor.submit(fetch_smart_money)
                cal_future   = executor.submit(fetch_calendar)
                mkt_future   = executor.submit(fetch_market_filters)
                candle_futures = {executor.submit(fetch_candles, p): p for p in args.pairs}

                for future in as_completed(candle_futures):
                    try:
                        pair, candles = future.result()
                        candle_data[pair] = candles
                    except Exception as e:
                        logger.error(f"Candle fetch error: {e}")

                try:
                    news_scores = news_future.result(timeout=12)
                except Exception as e:
                    logger.warning(f"News fetch error: {e}")

                try:
                    sm_scores = sm_future.result(timeout=12)
                except Exception as e:
                    logger.warning(f"Smart money fetch error: {e}")

                try:
                    cal_score, _ = cal_future.result(timeout=12)
                except Exception as e:
                    logger.warning(f"Calendar fetch error: {e}")

                try:
                    fng_score, funding_scores = mkt_future.result(timeout=12)
                except Exception as e:
                    logger.warning(f"Market filters fetch error: {e}")

            # Compute OI scores using latest prices from candles
            current_prices = {
                p.replace("USDT", ""): candle_data[p]["close"].iloc[-1]
                for p in args.pairs if candle_data.get(p) is not None
            }
            oi_scores = mkt_filters.get_oi_scores(current_prices)

            # Get BTC candles for correlation filter
            btc_candles = candle_data.get("BTCUSDT")

            # Process signals sequentially (orders must not overlap)
            for pair in args.pairs:
                try:
                    process_pair(
                        pair, candle_data.get(pair), balance,
                        news_scores, sm_scores, cal_score,
                        fng_score, funding_scores, oi_scores, btc_candles
                    )
                except Exception as e:
                    logger.error(f"Error processing {pair}: {e}")
                    continue

            # Refresh balances AFTER orders so newly bought coins appear in this cycle's table
            all_balances = client.get_all_balances()

            # ── Holdings table ──────────────────────────────────────────
            usdt_bal  = all_balances.get("USDT", 0.0)
            total_usd = usdt_bal

            rows = []
            for pair in args.pairs:
                base = pair.replace("USDT", "")
                qty = all_balances.get(base, 0.0)
                if qty > 0:
                    price_df   = candle_data.get(pair)
                    entry_price = risk.get_entry_price(pair)
                    entry_known = risk.get_entry_known(pair)
                    if price_df is not None:
                        last_price = price_df["close"].iloc[-1]
                        value      = qty * last_price
                        total_usd += value
                        if entry_known and entry_price > 0:
                            unr_pnl   = (last_price - entry_price) * qty
                            unr_pct   = (last_price - entry_price) / entry_price * 100
                            unr_str   = f"{unr_pnl:+,.2f} ({unr_pct:+.1f}%)"
                            entry_str = f"{entry_price:,.4f}"
                            addons    = risk.get_addon_count(pair)
                            qty_str   = f"{qty:.5f}" + (f" +{addons}x" if addons > 0 else "")
                        else:
                            unr_str   = "—"
                            entry_str = "—"
                            qty_str   = f"{qty:.5f}"
                        rows.append((base, qty_str, entry_str, f"{last_price:,.4f}", f"{value:,.2f}", unr_str))
                    else:
                        rows.append((base, f"{qty:.5f}", "—", "—", "—", "—"))

            # USDT row — no entry price or P&L
            rows.append(("USDT", f"{usdt_bal:.5f}", "—", "1.0000", f"{usdt_bal:,.2f}", "—"))

            # Column widths
            col_asset = max(len("Asset"),        max((len(r[0]) for r in rows), default=5))
            col_qty   = max(len("Quantity"),     max((len(r[1]) for r in rows), default=8))
            col_entry = max(len("Bought At"),    max((len(r[2]) for r in rows), default=9))
            col_price = max(len("Price"),        max((len(r[3]) for r in rows), default=7))
            col_value = max(len("Value (USDT)"), max((len(r[4]) for r in rows), default=12))
            col_unr   = max(len("Unrealised P&L"), max((len(r[5]) for r in rows), default=14))

            div = (
                f"+{'-'*(col_asset+2)}+{'-'*(col_qty+2)}+{'-'*(col_entry+2)}"
                f"+{'-'*(col_price+2)}+{'-'*(col_value+2)}+{'-'*(col_unr+2)}+"
            )
            head = (
                f"| {'Asset':<{col_asset}} | {'Quantity':<{col_qty}} "
                f"| {'Bought At':>{col_entry}} | {'Price':>{col_price}} "
                f"| {'Value (USDT)':>{col_value}} | {'Unrealised P&L':>{col_unr}} |"
            )
            total_line = (
                f"| {'TOTAL PORTFOLIO':<{col_asset}} | {'':<{col_qty}} "
                f"| {'':{col_entry}} | {'':{col_price}} "
                f"| {f'{total_usd:,.2f}':>{col_value}} | {'':{col_unr}} |"
            )

            logger.info(div)
            logger.info(head)
            logger.info(div)
            for r in rows:
                logger.info(
                    f"| {r[0]:<{col_asset}} | {r[1]:<{col_qty}} "
                    f"| {r[2]:>{col_entry}} | {r[3]:>{col_price}} "
                    f"| {r[4]:>{col_value}} | {r[5]:>{col_unr}} |"
                )
            logger.info(div)
            logger.info(total_line)
            logger.info(div)
            # ──────────────────────────────────────────────────────────

            logger.info(f"Cycle complete. Sleeping {sleep_sec}s...\n")
            time.sleep(sleep_sec)

    except KeyboardInterrupt:
        logger.info("Bot stopped by user.")
        risk.print_summary()


if __name__ == "__main__":
    main()
