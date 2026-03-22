"""
dashboard.py — Generate a performance dashboard from bot.log.

Parses the log file and produces a self-contained HTML dashboard showing:
  - Portfolio value over time
  - Win rate and P&L summary
  - Individual trade history with P&L
  - Best and worst trades
  - Signal accuracy (which sources triggered winning vs losing trades)
  - Exit reason breakdown

Usage:
    python3 dashboard.py                    # reads logs/bot.log, opens dashboard.html
    python3 dashboard.py --log logs/bot.log --output dashboard.html
"""

import re
import json
import argparse
import webbrowser
from datetime import datetime
from pathlib import Path


# ------------------------------------------------------------------ #
#  Log parser                                                          #
# ------------------------------------------------------------------ #

def parse_log(log_path: str) -> dict:
    """Extract trades, buys, and portfolio snapshots from bot.log."""
    trades    = []
    buys      = {}    # pair -> {price, qty, time}
    portfolio = []    # [{time, value}]
    signals   = []    # all signal debug lines

    buy_re   = re.compile(r"\[(.+?)\] INFO\s+BUY\s+(\w+)\s*\|\s*qty=([\d.]+)\s*@\s*([\d.]+)")
    sell_re  = re.compile(r"\[(.+?)\] INFO\s+SELL\s+(\w+)\s*\|\s*qty=([\d.]+)\s*@\s*([\d.]+)\s*\|\s*P&L=([+-][\d.,]+)\s*USDT\s*\|\s*reason=(\w[\w ]*)")
    total_re = re.compile(r"\[(.+?)\] INFO\s+\|\s*TOTAL PORTFOLIO\s*\|.*?\|\s*([\d,]+\.\d+)")
    addon_re = re.compile(r"\[(.+?)\] INFO\s+ADD-ON #(\d+)\s+(\w+)\s*\|\s*qty=([\d.]+)\s*@\s*([\d.]+)")
    sig_re   = re.compile(r"\[(.+?)\] DEBUG\s+(\w+USDT)\s*\|.*?signal=(\w+|None).*?conf=([\d.]+).*?tech=([+-][\d.]+).*?news=([+-][\d.]+)")

    try:
        with open(log_path, "r", errors="replace") as f:
            for line in f:
                # BUY
                m = buy_re.search(line)
                if m:
                    ts, pair, qty, price = m.group(1), m.group(2), float(m.group(3)), float(m.group(4))
                    buys[pair] = {"price": price, "qty": qty, "time": ts}
                    continue

                # SELL
                m = sell_re.search(line)
                if m:
                    ts, pair, qty, price = m.group(1), m.group(2), float(m.group(3)), float(m.group(4))
                    pnl_str = m.group(5).replace(",", "")
                    pnl     = float(pnl_str)
                    reason  = m.group(6).strip()
                    entry   = buys.pop(pair, {})
                    trades.append({
                        "time":        ts,
                        "pair":        pair,
                        "entry_price": entry.get("price", 0),
                        "exit_price":  price,
                        "qty":         qty,
                        "pnl":         pnl,
                        "reason":      reason,
                        "win":         pnl > 0,
                    })
                    continue

                # TOTAL PORTFOLIO
                m = total_re.search(line)
                if m:
                    ts  = m.group(1)
                    val = float(m.group(2).replace(",", ""))
                    portfolio.append({"time": ts, "value": val})
                    continue

    except FileNotFoundError:
        pass

    wins   = [t for t in trades if t["win"]]
    losses = [t for t in trades if not t["win"]]
    total_pnl = sum(t["pnl"] for t in trades)

    # Exit reason breakdown
    by_reason = {}
    for t in trades:
        r = t["reason"]
        by_reason.setdefault(r, {"count": 0, "pnl": 0, "wins": 0})
        by_reason[r]["count"] += 1
        by_reason[r]["pnl"]   += t["pnl"]
        if t["win"]:
            by_reason[r]["wins"] += 1

    # Per-pair stats
    by_pair = {}
    for t in trades:
        p = t["pair"]
        by_pair.setdefault(p, {"count": 0, "pnl": 0, "wins": 0})
        by_pair[p]["count"] += 1
        by_pair[p]["pnl"]   += t["pnl"]
        if t["win"]:
            by_pair[p]["wins"] += 1

    return {
        "trades":    trades,
        "portfolio": portfolio,
        "by_reason": by_reason,
        "by_pair":   by_pair,
        "summary": {
            "total_trades": len(trades),
            "wins":         len(wins),
            "losses":       len(losses),
            "win_rate":     round(len(wins) / len(trades) * 100, 1) if trades else 0,
            "total_pnl":    round(total_pnl, 2),
            "avg_win":      round(sum(t["pnl"] for t in wins) / len(wins), 2) if wins else 0,
            "avg_loss":     round(sum(t["pnl"] for t in losses) / len(losses), 2) if losses else 0,
            "best_trade":   max(trades, key=lambda t: t["pnl"]) if trades else None,
            "worst_trade":  min(trades, key=lambda t: t["pnl"]) if trades else None,
        }
    }


# ------------------------------------------------------------------ #
#  HTML generator                                                      #
# ------------------------------------------------------------------ #

def generate_html(data: dict) -> str:
    s       = data["summary"]
    trades  = data["trades"]
    port    = data["portfolio"]
    reason  = data["by_reason"]
    pairs   = data["by_pair"]

    port_labels = json.dumps([p["time"][-8:] for p in port[-200:]])
    port_values = json.dumps([p["value"] for p in port[-200:]])

    trade_rows = ""
    for t in sorted(trades, key=lambda x: x["time"], reverse=True)[:100]:
        color   = "#22c55e" if t["win"] else "#ef4444"
        pnl_str = f"+${t['pnl']:,.2f}" if t["pnl"] >= 0 else f"-${abs(t['pnl']):,.2f}"
        trade_rows += f"""
        <tr>
            <td>{t['time'][:16]}</td>
            <td><b>{t['pair']}</b></td>
            <td>${t['entry_price']:,.4f}</td>
            <td>${t['exit_price']:,.4f}</td>
            <td style="color:{color};font-weight:bold">{pnl_str}</td>
            <td><span class="badge">{t['reason']}</span></td>
        </tr>"""

    reason_rows = ""
    for r, d in sorted(reason.items(), key=lambda x: x[1]["pnl"], reverse=True):
        wr      = round(d["wins"] / d["count"] * 100, 1) if d["count"] else 0
        color   = "#22c55e" if d["pnl"] >= 0 else "#ef4444"
        pnl_str = f"+${d['pnl']:,.2f}" if d["pnl"] >= 0 else f"-${abs(d['pnl']):,.2f}"
        reason_rows += f"""
        <tr>
            <td><span class="badge">{r}</span></td>
            <td>{d['count']}</td>
            <td>{wr}%</td>
            <td style="color:{color};font-weight:bold">{pnl_str}</td>
        </tr>"""

    pair_rows = ""
    for p, d in sorted(pairs.items(), key=lambda x: x[1]["pnl"], reverse=True):
        wr      = round(d["wins"] / d["count"] * 100, 1) if d["count"] else 0
        color   = "#22c55e" if d["pnl"] >= 0 else "#ef4444"
        pnl_str = f"+${d['pnl']:,.2f}" if d["pnl"] >= 0 else f"-${abs(d['pnl']):,.2f}"
        pair_rows += f"""
        <tr>
            <td><b>{p}</b></td>
            <td>{d['count']}</td>
            <td>{wr}%</td>
            <td style="color:{color};font-weight:bold">{pnl_str}</td>
        </tr>"""

    best  = s.get("best_trade")
    worst = s.get("worst_trade")
    best_str  = f"<b>{best['pair']}</b> +${best['pnl']:,.2f} ({best['reason']})" if best else "—"
    worst_str = f"<b>{worst['pair']}</b> -${abs(worst['pnl']):,.2f} ({worst['reason']})" if worst else "—"

    pnl_color = "#22c55e" if s["total_pnl"] >= 0 else "#ef4444"
    wr_color  = "#22c55e" if s["win_rate"] >= 50 else "#ef4444"

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>CryptoBot — Performance Dashboard</title>
<script src="https://cdnjs.cloudflare.com/ajax/libs/Chart.js/4.4.1/chart.umd.min.js"></script>
<style>
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
          background: #0f172a; color: #e2e8f0; min-height: 100vh; }}
  .header {{ background: linear-gradient(135deg, #1e293b, #0f172a);
             border-bottom: 1px solid #334155; padding: 20px 32px;
             display: flex; justify-content: space-between; align-items: center; }}
  .header h1 {{ font-size: 1.4rem; font-weight: 700; color: #f8fafc; }}
  .header .sub {{ color: #94a3b8; font-size: 0.85rem; margin-top: 4px; }}
  .container {{ max-width: 1400px; margin: 0 auto; padding: 24px 32px; }}
  .grid-4 {{ display: grid; grid-template-columns: repeat(4, 1fr); gap: 16px; margin-bottom: 24px; }}
  .grid-2 {{ display: grid; grid-template-columns: 1fr 1fr; gap: 20px; margin-bottom: 24px; }}
  .card {{ background: #1e293b; border: 1px solid #334155; border-radius: 12px; padding: 20px; }}
  .card h3 {{ color: #94a3b8; font-size: 0.75rem; font-weight: 600; text-transform: uppercase;
              letter-spacing: 0.05em; margin-bottom: 8px; }}
  .card .value {{ font-size: 1.8rem; font-weight: 700; color: #f8fafc; }}
  .card .sub {{ font-size: 0.8rem; color: #64748b; margin-top: 4px; }}
  .chart-card {{ background: #1e293b; border: 1px solid #334155; border-radius: 12px;
                 padding: 20px; margin-bottom: 24px; }}
  .chart-card h3 {{ color: #e2e8f0; font-size: 1rem; font-weight: 600; margin-bottom: 16px; }}
  table {{ width: 100%; border-collapse: collapse; font-size: 0.875rem; }}
  th {{ text-align: left; padding: 10px 12px; color: #64748b; font-weight: 600;
        font-size: 0.75rem; text-transform: uppercase; border-bottom: 1px solid #334155; }}
  td {{ padding: 10px 12px; border-bottom: 1px solid #1e293b; color: #cbd5e1; }}
  tr:hover td {{ background: #1e293b; }}
  .badge {{ background: #334155; color: #94a3b8; padding: 2px 8px; border-radius: 4px;
            font-size: 0.75rem; font-weight: 500; }}
  .highlight-card {{ background: #1e293b; border: 1px solid #334155; border-radius: 12px;
                     padding: 16px 20px; margin-bottom: 24px;
                     display: grid; grid-template-columns: 1fr 1fr; gap: 16px; }}
  .highlight-item h4 {{ color: #64748b; font-size: 0.75rem; text-transform: uppercase;
                        letter-spacing: 0.05em; margin-bottom: 6px; }}
  .empty {{ color: #475569; text-align: center; padding: 40px; font-style: italic; }}
  @media (max-width: 768px) {{
    .grid-4 {{ grid-template-columns: repeat(2, 1fr); }}
    .grid-2 {{ grid-template-columns: 1fr; }}
    .container {{ padding: 16px; }}
  }}
</style>
</head>
<body>
<div class="header">
  <div>
    <h1>⚡ CryptoBot Performance Dashboard</h1>
    <div class="sub">Generated {datetime.now().strftime("%Y-%m-%d %H:%M")} · Last 100 trades shown</div>
  </div>
</div>

<div class="container">

  <!-- Summary cards -->
  <div class="grid-4">
    <div class="card">
      <h3>Total P&L</h3>
      <div class="value" style="color:{pnl_color}">
        {"+" if s["total_pnl"] >= 0 else ""}${s["total_pnl"]:,.2f}
      </div>
      <div class="sub">{s["total_trades"]} completed trades</div>
    </div>
    <div class="card">
      <h3>Win Rate</h3>
      <div class="value" style="color:{wr_color}">{s["win_rate"]}%</div>
      <div class="sub">{s["wins"]}W / {s["losses"]}L</div>
    </div>
    <div class="card">
      <h3>Avg Win</h3>
      <div class="value" style="color:#22c55e">+${s["avg_win"]:,.2f}</div>
      <div class="sub">per winning trade</div>
    </div>
    <div class="card">
      <h3>Avg Loss</h3>
      <div class="value" style="color:#ef4444">${s["avg_loss"]:,.2f}</div>
      <div class="sub">per losing trade</div>
    </div>
  </div>

  <!-- Best / worst -->
  <div class="highlight-card">
    <div class="highlight-item">
      <h4>🏆 Best Trade</h4>
      <div style="color:#22c55e;font-size:0.95rem">{best_str}</div>
    </div>
    <div class="highlight-item">
      <h4>📉 Worst Trade</h4>
      <div style="color:#ef4444;font-size:0.95rem">{worst_str}</div>
    </div>
  </div>

  <!-- Portfolio chart -->
  <div class="chart-card">
    <h3>Portfolio Value Over Time</h3>
    <canvas id="portfolioChart" height="80"></canvas>
  </div>

  <!-- Tables -->
  <div class="grid-2">
    <div class="card">
      <h3 style="font-size:1rem;color:#e2e8f0;margin-bottom:16px">Exit Reason Breakdown</h3>
      {"<table><thead><tr><th>Reason</th><th>Count</th><th>Win%</th><th>P&L</th></tr></thead><tbody>" + reason_rows + "</tbody></table>" if reason_rows else '<div class="empty">No trades yet</div>'}
    </div>
    <div class="card">
      <h3 style="font-size:1rem;color:#e2e8f0;margin-bottom:16px">Performance by Pair</h3>
      {"<table><thead><tr><th>Pair</th><th>Trades</th><th>Win%</th><th>P&L</th></tr></thead><tbody>" + pair_rows + "</tbody></table>" if pair_rows else '<div class="empty">No trades yet</div>'}
    </div>
  </div>

  <!-- Trade history -->
  <div class="chart-card">
    <h3>Recent Trade History</h3>
    {"<table><thead><tr><th>Time</th><th>Pair</th><th>Entry</th><th>Exit</th><th>P&L</th><th>Reason</th></tr></thead><tbody>" + trade_rows + "</tbody></table>" if trade_rows else '<div class="empty">No trades found in log file. Start the bot and trades will appear here.</div>'}
  </div>

</div>

<script>
const ctx = document.getElementById('portfolioChart').getContext('2d');
const labels = {port_labels};
const values = {port_values};

new Chart(ctx, {{
  type: 'line',
  data: {{
    labels: labels,
    datasets: [{{
      label: 'Portfolio Value (USDT)',
      data: values,
      borderColor: '#6366f1',
      backgroundColor: 'rgba(99,102,241,0.08)',
      borderWidth: 2,
      pointRadius: 0,
      fill: true,
      tension: 0.3,
    }}]
  }},
  options: {{
    responsive: true,
    plugins: {{
      legend: {{ labels: {{ color: '#94a3b8' }} }},
      tooltip: {{
        callbacks: {{
          label: ctx => '$' + ctx.parsed.y.toLocaleString('en-US', {{minimumFractionDigits: 2}})
        }}
      }}
    }},
    scales: {{
      x: {{ ticks: {{ color: '#475569', maxTicksLimit: 12 }}, grid: {{ color: '#1e293b' }} }},
      y: {{ ticks: {{ color: '#475569', callback: v => '$' + v.toLocaleString() }}, grid: {{ color: '#334155' }} }}
    }}
  }}
}});
</script>
</body>
</html>"""


# ------------------------------------------------------------------ #
#  CLI                                                                 #
# ------------------------------------------------------------------ #

def main():
    p = argparse.ArgumentParser(description="CryptoBot Performance Dashboard Generator")
    p.add_argument("--log",    default="logs/bot.log",    help="Path to bot.log")
    p.add_argument("--output", default="dashboard.html",  help="Output HTML file")
    p.add_argument("--no-open", action="store_true",      help="Don't open browser automatically")
    args = p.parse_args()

    print(f"CryptoBot Dashboard Generator")
    print(f"Reading: {args.log}")

    data = parse_log(args.log)
    s    = data["summary"]

    print(f"Found {s['total_trades']} trades | Win rate: {s['win_rate']}% | P&L: ${s['total_pnl']:+,.2f}")
    print(f"Portfolio snapshots: {len(data['portfolio'])}")

    html = generate_html(data)

    with open(args.output, "w", encoding="utf-8") as f:
        f.write(html)

    print(f"Dashboard saved to: {args.output}")

    if not args.no_open:
        try:
            webbrowser.open(f"file://{Path(args.output).resolve()}")
            print("Opening in browser...")
        except Exception:
            pass


if __name__ == "__main__":
    main()
