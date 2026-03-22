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

def load_backtest_results(bt_path: str) -> list:
    """Load backtest run history. Returns list of runs, each run is a list of pair results."""
    try:
        with open(bt_path, "r") as f:
            data = json.load(f)
        if not data:
            return []
        # Handle old flat format
        if isinstance(data[0], dict):
            return [data]
        return data
    except (FileNotFoundError, json.JSONDecodeError):
        return []


def generate_html(data: dict, bt_runs: list = None) -> str:
    s       = data["summary"]
    trades  = data["trades"]
    port    = data["portfolio"]
    reason  = data["by_reason"]
    pairs   = data["by_pair"]
    bt_runs = bt_runs or []

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

    # ── Backtest tab content ──────────────────────────────────────────
    bt_run_rows = ""
    bt_chart_datasets = []
    bt_chart_labels   = []
    colors = ["#6366f1","#22c55e","#f59e0b","#ec4899","#06b6d4",
              "#8b5cf6","#10b981","#f97316","#e11d48","#0ea5e9"]

    for run_idx, run in enumerate(reversed(bt_runs[-10:])):  # last 10 runs newest first
        if not run:
            continue
        cfg_snap = run[0].get("config", {})
        label    = (f"{cfg_snap.get('strategy','?')} | {cfg_snap.get('timeframe','?')} | "
                    f"aggr={cfg_snap.get('aggression','?')} | {cfg_snap.get('days','?')}d | "
                    f"{cfg_snap.get('run_at','')[:16]}")

        for r in run:
            pnl_c   = "#22c55e" if r.get("total_pnl", 0) >= 0 else "#ef4444"
            bnh_c   = "#22c55e" if r.get("bnh_return_pct", 0) >= 0 else "#ef4444"
            dd_c    = "#ef4444" if r.get("max_drawdown", 0) > 10 else "#f59e0b" if r.get("max_drawdown", 0) > 5 else "#22c55e"
            pnl_str = f"+${r['total_pnl']:,.2f}" if r.get('total_pnl',0) >= 0 else f"-${abs(r.get('total_pnl',0)):,.2f}"
            bnh_str = f"{r.get('bnh_return_pct',0):+.2f}%"
            note    = r.get("config", {}).get("note", "")
            note_html = f'<br><span style="color:#f59e0b;font-size:0.72rem">⚠ {note}</span>' if note else ""
            row_style = 'background:#1a1200;' if '⚠' in note else ''
            bt_run_rows += f"""
            <tr style="{row_style}">
                <td style="color:#94a3b8;font-size:0.8rem">{cfg_snap.get('run_at','')[:16]}</td>
                <td><span class="badge">{cfg_snap.get('strategy','?')}</span></td>
                <td><span class="badge">{cfg_snap.get('timeframe','?')}</span></td>
                <td>{cfg_snap.get('aggression','?')}</td>
                <td>{cfg_snap.get('days','?')}d</td>
                <td><b>{r.get('symbol','?')}</b>{note_html}</td>
                <td style="color:{pnl_c};font-weight:bold">{pnl_str}</td>
                <td>{r.get('win_rate',0):.1f}%</td>
                <td style="color:{dd_c}">{r.get('max_drawdown',0):.1f}%</td>
                <td>{r.get('total_trades',0)}</td>
                <td style="color:{bnh_c}">{bnh_str}</td>
                <td>{r.get('sharpe',0):.2f}</td>
            </tr>"""

        # Equity curve for this run (first pair only)
        if run[0].get("equity_curve"):
            color = colors[run_idx % len(colors)]
            bt_chart_datasets.append({
                "label":       label,
                "data":        run[0]["equity_curve"],
                "borderColor": color,
                "borderWidth": 2,
                "pointRadius": 0,
                "fill":        False,
                "tension":     0.3,
            })
            if not bt_chart_labels:
                bt_chart_labels = list(range(len(run[0]["equity_curve"])))

    bt_chart_json    = json.dumps(bt_chart_datasets)
    bt_labels_json   = json.dumps(bt_chart_labels)
    bt_table_content = (
        f"""<table>
          <thead><tr>
            <th>Run time</th><th>Strategy</th><th>TF</th><th>Aggr</th><th>Period</th>
            <th>Pair</th><th>P&L</th><th>Win%</th><th>Max DD</th>
            <th>Trades</th><th>vs B&H</th><th>Sharpe</th>
          </tr></thead>
          <tbody>{bt_run_rows}</tbody>
        </table>"""
        if bt_run_rows else '<div class="empty">No backtest results yet.<br>Run: <code>python3 backtest.py --strategy ema --days 30</code></div>'
    )

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
  .header {{ background: #1e293b; border-bottom: 1px solid #334155;
             padding: 16px 32px; display: flex; justify-content: space-between; align-items: center; }}
  .header h1 {{ font-size: 1.3rem; font-weight: 700; color: #f8fafc; }}
  .header .sub {{ color: #64748b; font-size: 0.8rem; margin-top: 3px; }}
  .tabs {{ display: flex; gap: 2px; background: #1e293b;
           border-bottom: 1px solid #334155; padding: 0 32px; }}
  .tab {{ padding: 12px 20px; cursor: pointer; color: #64748b; font-size: 0.875rem;
          font-weight: 500; border-bottom: 2px solid transparent; transition: all 0.2s; }}
  .tab:hover {{ color: #e2e8f0; }}
  .tab.active {{ color: #6366f1; border-bottom-color: #6366f1; }}
  .tab-content {{ display: none; padding: 24px 32px; }}
  .tab-content.active {{ display: block; }}
  .grid-4 {{ display: grid; grid-template-columns: repeat(4, 1fr); gap: 16px; margin-bottom: 24px; }}
  .grid-2 {{ display: grid; grid-template-columns: 1fr 1fr; gap: 20px; margin-bottom: 24px; }}
  .card {{ background: #1e293b; border: 1px solid #334155; border-radius: 10px; padding: 18px; }}
  .card h3 {{ color: #64748b; font-size: 0.7rem; font-weight: 600;
              text-transform: uppercase; letter-spacing: 0.05em; margin-bottom: 8px; }}
  .card .value {{ font-size: 1.7rem; font-weight: 700; color: #f8fafc; }}
  .card .sub {{ font-size: 0.78rem; color: #475569; margin-top: 4px; }}
  .chart-card {{ background: #1e293b; border: 1px solid #334155; border-radius: 10px;
                 padding: 20px; margin-bottom: 24px; }}
  .chart-card h3 {{ color: #e2e8f0; font-size: 0.95rem; font-weight: 600; margin-bottom: 16px; }}
  .table-card {{ background: #1e293b; border: 1px solid #334155; border-radius: 10px;
                 padding: 20px; margin-bottom: 24px; overflow-x: auto; }}
  .table-card h3 {{ color: #e2e8f0; font-size: 0.95rem; font-weight: 600; margin-bottom: 16px; }}
  table {{ width: 100%; border-collapse: collapse; font-size: 0.84rem; }}
  th {{ text-align: left; padding: 9px 12px; color: #475569; font-weight: 600;
        font-size: 0.72rem; text-transform: uppercase; border-bottom: 1px solid #334155; white-space: nowrap; }}
  td {{ padding: 9px 12px; border-bottom: 1px solid #1a2744; color: #cbd5e1; white-space: nowrap; }}
  tr:last-child td {{ border-bottom: none; }}
  tr:hover td {{ background: #263354; }}
  .badge {{ background: #334155; color: #94a3b8; padding: 2px 7px; border-radius: 4px;
            font-size: 0.72rem; font-weight: 500; }}
  .highlight-card {{ background: #1e293b; border: 1px solid #334155; border-radius: 10px;
                     padding: 16px 20px; margin-bottom: 24px;
                     display: grid; grid-template-columns: 1fr 1fr; gap: 16px; }}
  .highlight-item h4 {{ color: #475569; font-size: 0.72rem; text-transform: uppercase;
                        letter-spacing: 0.05em; margin-bottom: 6px; }}
  .empty {{ color: #334155; text-align: center; padding: 48px 24px;
            font-size: 0.9rem; line-height: 1.8; }}
  .empty code {{ background: #1e293b; padding: 2px 8px; border-radius: 4px;
                 color: #6366f1; font-size: 0.85rem; }}
  @media (max-width: 768px) {{
    .grid-4 {{ grid-template-columns: repeat(2, 1fr); }}
    .grid-2 {{ grid-template-columns: 1fr; }}
    .tab-content {{ padding: 16px; }}
    .tabs {{ padding: 0 16px; }}
  }}
</style>
</head>
<body>

<div class="header">
  <div>
    <h1>⚡ CryptoBot Dashboard</h1>
    <div class="sub">Generated {datetime.now().strftime("%Y-%m-%d %H:%M")}</div>
  </div>
</div>

<div class="tabs">
  <div class="tab active" onclick="switchTab('live', this)">📈 Live Trading</div>
  <div class="tab" onclick="switchTab('backtest', this)">🧪 Backtests ({len(bt_runs)} runs)</div>
</div>

<!-- ═══════════════════ LIVE TAB ═══════════════════ -->
<div id="tab-live" class="tab-content active">

  <div class="grid-4">
    <div class="card">
      <h3>Total P&L</h3>
      <div class="value" style="color:{pnl_color}">{"+" if s["total_pnl"]>=0 else ""}${s["total_pnl"]:,.2f}</div>
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

  <div class="highlight-card">
    <div class="highlight-item">
      <h4>🏆 Best Trade</h4>
      <div style="color:#22c55e;font-size:0.9rem">{best_str}</div>
    </div>
    <div class="highlight-item">
      <h4>📉 Worst Trade</h4>
      <div style="color:#ef4444;font-size:0.9rem">{worst_str}</div>
    </div>
  </div>

  <div class="chart-card">
    <h3>Portfolio Value Over Time</h3>
    <canvas id="portfolioChart" height="70"></canvas>
  </div>

  <div class="grid-2">
    <div class="card">
      <h3 style="font-size:0.95rem;color:#e2e8f0;margin-bottom:14px">Exit Reason Breakdown</h3>
      {"<table><thead><tr><th>Reason</th><th>Count</th><th>Win%</th><th>P&L</th></tr></thead><tbody>" + reason_rows + "</tbody></table>" if reason_rows else '<div class="empty">No trades yet</div>'}
    </div>
    <div class="card">
      <h3 style="font-size:0.95rem;color:#e2e8f0;margin-bottom:14px">Performance by Pair</h3>
      {"<table><thead><tr><th>Pair</th><th>Trades</th><th>Win%</th><th>P&L</th></tr></thead><tbody>" + pair_rows + "</tbody></table>" if pair_rows else '<div class="empty">No trades yet</div>'}
    </div>
  </div>

  <div class="table-card">
    <h3>Recent Trade History</h3>
    {"<table><thead><tr><th>Time</th><th>Pair</th><th>Entry</th><th>Exit</th><th>P&L</th><th>Reason</th></tr></thead><tbody>" + trade_rows + "</tbody></table>" if trade_rows else '<div class="empty">No trades found in log file.<br>Start the bot and completed trades will appear here.</div>'}
  </div>

</div>

<!-- ═══════════════════ BACKTEST TAB ═══════════════════ -->
<div id="tab-backtest" class="tab-content">

  <div class="chart-card">
    <h3>Equity Curves — All Runs (first pair per run)</h3>
    <canvas id="btChart" height="80"></canvas>
  </div>

  <div class="table-card">
    <h3>All Backtest Runs — Comparison</h3>
    <p style="color:#475569;font-size:0.8rem;margin-bottom:12px">Newest runs at top. Each row is one pair from one run.</p>
    {bt_table_content}
  </div>

</div>

<script>
// ── Tab switcher ────────────────────────────────────────
function switchTab(name, el) {{
  document.querySelectorAll('.tab-content').forEach(t => t.classList.remove('active'));
  document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
  document.getElementById('tab-' + name).classList.add('active');
  el.classList.add('active');
}}

// ── Live portfolio chart ─────────────────────────────────
const liveCtx = document.getElementById('portfolioChart').getContext('2d');
new Chart(liveCtx, {{
  type: 'line',
  data: {{
    labels: {port_labels},
    datasets: [{{
      label: 'Portfolio (USDT)',
      data: {port_values},
      borderColor: '#6366f1',
      backgroundColor: 'rgba(99,102,241,0.08)',
      borderWidth: 2, pointRadius: 0, fill: true, tension: 0.3,
    }}]
  }},
  options: {{
    responsive: true,
    plugins: {{ legend: {{ labels: {{ color: '#64748b' }} }},
      tooltip: {{ callbacks: {{ label: c => '$' + c.parsed.y.toLocaleString('en-US', {{minimumFractionDigits:2}}) }} }} }},
    scales: {{
      x: {{ ticks: {{ color:'#334155', maxTicksLimit:10 }}, grid: {{ color:'#1a2744' }} }},
      y: {{ ticks: {{ color:'#475569', callback: v => '$'+v.toLocaleString() }}, grid: {{ color:'#334155' }} }}
    }}
  }}
}});

// ── Backtest equity chart ────────────────────────────────
const btCtx = document.getElementById('btChart').getContext('2d');
new Chart(btCtx, {{
  type: 'line',
  data: {{
    labels: {bt_labels_json},
    datasets: {bt_chart_json}
  }},
  options: {{
    responsive: true,
    interaction: {{ mode: 'index', intersect: false }},
    plugins: {{
      legend: {{ labels: {{ color: '#64748b', font: {{ size: 11 }} }} }},
      tooltip: {{ callbacks: {{ label: c => c.dataset.label.split('|')[0].trim() + ': $' + c.parsed.y.toLocaleString('en-US', {{minimumFractionDigits:2}}) }} }}
    }},
    scales: {{
      x: {{ display: false }},
      y: {{ ticks: {{ color:'#475569', callback: v => '$'+v.toLocaleString() }}, grid: {{ color:'#334155' }} }}
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
    p.add_argument("--log",      default="logs/bot.log",          help="Path to bot.log")
    p.add_argument("--backtest", default="backtest_results.json",  help="Path to backtest results")
    p.add_argument("--output",   default="dashboard.html",         help="Output HTML file")
    p.add_argument("--no-open",  action="store_true",              help="Don't open browser automatically")
    args = p.parse_args()

    print(f"CryptoBot Dashboard Generator")
    print(f"Reading log:      {args.log}")
    print(f"Reading backtests: {args.backtest}")

    data    = parse_log(args.log)
    bt_runs = load_backtest_results(args.backtest)
    s       = data["summary"]

    print(f"Live trades: {s['total_trades']} | Win rate: {s['win_rate']}% | P&L: ${s['total_pnl']:+,.2f}")
    print(f"Backtest runs: {len(bt_runs)}")

    html = generate_html(data, bt_runs)

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
