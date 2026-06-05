"""
Web Dashboard — serves a live HTML trading dashboard at http://localhost:5000
Auto-refreshes every 30 seconds. No extra dependencies needed.
"""
import json
import csv
import os
from http.server import HTTPServer, BaseHTTPRequestHandler
from datetime import datetime

RISK_FILE  = "risk_state.json"
TRADES_FILE = "trades.csv"
PORT = 5000


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/":
            self._serve(get_html().encode(), "text/html")
        elif self.path == "/data":
            self._serve(get_data().encode(), "application/json")
        else:
            self.send_response(404); self.end_headers()

    def _serve(self, body, content_type):
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Content-Length", len(body))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *a):
        pass  # silence request logs


def get_data():
    state  = {}
    trades = []
    if os.path.exists(RISK_FILE):
        with open(RISK_FILE) as f:
            state = json.load(f)
    if os.path.exists(TRADES_FILE):
        with open(TRADES_FILE) as f:
            trades = list(csv.DictReader(f))
    return json.dumps({
        "state":  state,
        "trades": trades,
        "budget": float(os.getenv("WEEKLY_BUDGET", "500")),
        "ts":     datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
    })


def get_html():
    return r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8"/>
<meta name="viewport" content="width=device-width,initial-scale=1"/>
<title>Crypto Trading Agent</title>
<style>
  :root {
    --bg:      #0d1117;
    --surface: #161b22;
    --border:  #30363d;
    --text:    #e6edf3;
    --muted:   #7d8590;
    --green:   #3fb950;
    --red:     #f85149;
    --yellow:  #d29922;
    --blue:    #58a6ff;
    --purple:  #bc8cff;
  }
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { background: var(--bg); color: var(--text); font-family: 'Segoe UI', system-ui, sans-serif; font-size: 14px; }

  header {
    display: flex; align-items: center; justify-content: space-between;
    padding: 14px 24px; background: var(--surface); border-bottom: 1px solid var(--border);
    position: sticky; top: 0; z-index: 10;
  }
  header .logo { font-size: 18px; font-weight: 700; color: var(--blue); letter-spacing: .5px; }
  header .logo span { color: var(--muted); font-weight: 400; font-size: 13px; margin-left: 10px; }
  header .right { display: flex; align-items: center; gap: 20px; color: var(--muted); font-size: 12px; }
  .pill { background: #1a2a1a; color: var(--green); border: 1px solid #2ea04326;
          padding: 3px 10px; border-radius: 20px; font-size: 11px; font-weight: 600; }
  #countdown { color: var(--muted); font-size: 12px; }
  #utc { color: var(--muted); }

  main { max-width: 1400px; margin: 0 auto; padding: 24px; display: flex; flex-direction: column; gap: 20px; }

  /* ── KPI cards ── */
  .kpi-grid { display: grid; grid-template-columns: repeat(4, 1fr); gap: 14px; }
  .kpi { background: var(--surface); border: 1px solid var(--border); border-radius: 10px;
         padding: 18px 22px; display: flex; flex-direction: column; gap: 6px; }
  .kpi .label { font-size: 11px; text-transform: uppercase; letter-spacing: .8px; color: var(--muted); }
  .kpi .value { font-size: 26px; font-weight: 700; }
  .kpi .sub   { font-size: 11px; color: var(--muted); }
  .green { color: var(--green); }
  .red   { color: var(--red); }
  .blue  { color: var(--blue); }
  .yellow{ color: var(--yellow); }

  /* ── Panels ── */
  .panel { background: var(--surface); border: 1px solid var(--border); border-radius: 10px; overflow: hidden; }
  .panel-header { padding: 14px 20px; border-bottom: 1px solid var(--border);
                  font-size: 13px; font-weight: 600; color: var(--text); display: flex; justify-content: space-between; align-items: center; }
  .panel-body { padding: 0; overflow-x: auto; }

  /* ── Two-column layout ── */
  .two-col { display: grid; grid-template-columns: 1fr 320px; gap: 20px; }

  /* ── Tables ── */
  table { width: 100%; border-collapse: collapse; }
  th { padding: 10px 16px; text-align: left; font-size: 11px; text-transform: uppercase;
       letter-spacing: .6px; color: var(--muted); border-bottom: 1px solid var(--border); font-weight: 600; }
  td { padding: 12px 16px; border-bottom: 1px solid #21262d; font-size: 13px; }
  tr:last-child td { border-bottom: none; }
  tr:hover td { background: #1c2128; }
  .mono { font-family: 'Consolas', 'SF Mono', monospace; }

  /* ── Position bar ── */
  .bar-wrap { display: flex; align-items: center; gap: 8px; }
  .bar-track { flex: 1; height: 6px; background: #21262d; border-radius: 3px; overflow: hidden; min-width: 80px; }
  .bar-fill  { height: 100%; border-radius: 3px; transition: width .4s; }
  .bar-label { font-size: 11px; color: var(--muted); white-space: nowrap; }

  /* ── Badge ── */
  .badge { display: inline-block; padding: 2px 8px; border-radius: 4px; font-size: 11px; font-weight: 600; }
  .badge-green  { background: #1a2e1a; color: var(--green); }
  .badge-red    { background: #2e1a1a; color: var(--red); }
  .badge-yellow { background: #2e271a; color: var(--yellow); }
  .badge-buy    { background: #1a2e1a; color: var(--green); }
  .badge-sell   { background: #2e1a1a; color: var(--red); }

  /* ── Sentiment ── */
  .sentiment-body { padding: 20px; display: flex; flex-direction: column; gap: 16px; }
  .fng-score { font-size: 48px; font-weight: 800; text-align: center; }
  .fng-label { text-align: center; font-size: 13px; color: var(--muted); margin-top: -8px; }
  .fng-bar-wrap { position: relative; height: 8px; background: linear-gradient(to right, #3fb950, #d29922, #f85149);
                  border-radius: 4px; margin: 4px 0; }
  .fng-marker { position: absolute; top: -4px; width: 16px; height: 16px; border-radius: 50%;
                background: white; border: 3px solid var(--bg); transform: translateX(-50%); transition: left .5s; }
  .fng-ends { display: flex; justify-content: space-between; font-size: 10px; color: var(--muted); margin-top: 4px; }

  .stat-row { display: flex; justify-content: space-between; padding: 8px 0;
              border-bottom: 1px solid #21262d; font-size: 13px; }
  .stat-row:last-child { border-bottom: none; }

  /* ── Spinner ── */
  .spinner { display: inline-block; width: 10px; height: 10px; border: 2px solid var(--border);
             border-top-color: var(--blue); border-radius: 50%; animation: spin .8s linear infinite; }
  @keyframes spin { to { transform: rotate(360deg); } }

  /* ── Empty state ── */
  .empty { padding: 32px; text-align: center; color: var(--muted); font-size: 13px; }

  /* ── P&L flash ── */
  @keyframes flashGreen { from { background: #1a2e1a; } to { background: transparent; } }
  @keyframes flashRed   { from { background: #2e1a1a; } to { background: transparent; } }
  .flash-g td { animation: flashGreen .8s ease; }
  .flash-r td { animation: flashRed .8s ease; }

  @media (max-width: 900px) {
    .kpi-grid { grid-template-columns: repeat(2, 1fr); }
    .two-col  { grid-template-columns: 1fr; }
  }
</style>
</head>
<body>

<header>
  <div class="logo">🤖 Crypto Trading Agent <span>PAPER TRADING</span></div>
  <div class="right">
    <span id="utc">—</span>
    <span id="countdown">Refresh in 30s</span>
    <span id="status-dot" class="pill">● LIVE</span>
  </div>
</header>

<main>
  <!-- KPI Row -->
  <div class="kpi-grid">
    <div class="kpi">
      <div class="label">Total P&amp;L</div>
      <div class="value mono" id="kpi-total">—</div>
      <div class="sub" id="kpi-roi">—</div>
    </div>
    <div class="kpi">
      <div class="label">Realised (Banked)</div>
      <div class="value mono" id="kpi-realised">—</div>
      <div class="sub">Closed trades</div>
    </div>
    <div class="kpi">
      <div class="label">Unrealised (Open)</div>
      <div class="value mono" id="kpi-unreal">—</div>
      <div class="sub">Live positions</div>
    </div>
    <div class="kpi">
      <div class="label">Budget Remaining</div>
      <div class="value mono" id="kpi-budget">—</div>
      <div class="sub" id="kpi-week">Week of —</div>
    </div>
  </div>

  <!-- Positions + Sentiment -->
  <div class="two-col">
    <div class="panel">
      <div class="panel-header">
        Open Positions
        <span id="pos-count" class="badge badge-green">—</span>
      </div>
      <div class="panel-body">
        <table id="pos-table">
          <thead><tr>
            <th>Coin</th><th>Entry</th><th>Now</th><th>Change</th><th>P&amp;L</th>
            <th>SL → Position → TP</th><th>Status</th>
          </tr></thead>
          <tbody id="pos-body"><tr><td colspan="7" class="empty"><span class="spinner"></span> Loading…</td></tr></tbody>
        </table>
      </div>
    </div>

    <div class="panel">
      <div class="panel-header">Market Sentiment</div>
      <div class="sentiment-body">
        <div>
          <div class="fng-score" id="fng-score">—</div>
          <div class="fng-label" id="fng-label">Fear &amp; Greed</div>
          <div style="margin-top:12px">
            <div class="fng-bar-wrap"><div class="fng-marker" id="fng-marker" style="left:50%"></div></div>
            <div class="fng-ends"><span>Fear</span><span>Greed</span></div>
          </div>
        </div>
        <div>
          <div class="stat-row"><span style="color:var(--muted)">Week start</span><span id="s-week">—</span></div>
          <div class="stat-row"><span style="color:var(--muted)">Budget</span><span id="s-budget">—</span></div>
          <div class="stat-row"><span style="color:var(--muted)">Spent</span><span id="s-spent">—</span></div>
          <div class="stat-row"><span style="color:var(--muted)">Win rate</span><span id="s-winrate">—</span></div>
          <div class="stat-row"><span style="color:var(--muted)">Open positions</span><span id="s-open">—</span></div>
        </div>
      </div>
    </div>
  </div>

  <!-- Trade History -->
  <div class="panel">
    <div class="panel-header">
      Trade History
      <span style="font-size:11px;color:var(--muted);font-weight:400">Most recent first</span>
    </div>
    <div class="panel-body">
      <table>
        <thead><tr>
          <th>Time</th><th>Coin</th><th>Action</th><th>Price</th>
          <th>Value</th><th>P&amp;L</th><th>Confidence</th><th>Reason</th>
        </tr></thead>
        <tbody id="hist-body"><tr><td colspan="8" class="empty"><span class="spinner"></span> Loading…</td></tr></tbody>
      </table>
    </div>
  </div>
</main>

<script>
const BINANCE = "https://api.binance.com/api/v3/ticker/price";
const FNG_API = "https://api.alternative.me/fng/?limit=1";
let prevPrices = {};
let countdown  = 30;

function fmt(n, sign=true) {
  const s = sign && n >= 0 ? "+" : "";
  return s + n.toFixed(4);
}
function fmtUsd(n, sign=true) {
  const s = sign && n >= 0 ? "+" : "";
  return s + "$" + Math.abs(n).toFixed(2);
}
function colorClass(n) { return n >= 0 ? "green" : "red"; }

// ── Fetch portfolio data from local server ──
async function fetchPortfolio() {
  const r = await fetch("/data");
  return r.json();
}

// ── Fetch live prices for a list of symbols ──
async function fetchPrices(symbols) {
  const results = {};
  await Promise.all(symbols.map(async sym => {
    try {
      const r = await fetch(`${BINANCE}?symbol=${sym}`);
      const d = await r.json();
      results[sym] = parseFloat(d.price);
    } catch(e) {}
  }));
  return results;
}

// ── Fetch Fear & Greed ──
async function fetchFNG() {
  try {
    const r = await fetch(FNG_API);
    const d = await r.json();
    return { value: parseInt(d.data[0].value), label: d.data[0].value_classification };
  } catch(e) { return { value: 50, label: "Neutral" }; }
}

// ── Calc realised P&L from trade history ──
function calcRealised(trades) {
  const book = {};
  let pnl = 0;
  let wins = 0, losses = 0;
  for (const t of trades) {
    const price = parseFloat(t.price), qty = parseFloat(t.quantity);
    if (t.action === "BUY") {
      book[t.symbol] = { price, qty };
    } else if (t.action === "SELL" && book[t.symbol]) {
      const p = (price - book[t.symbol].price) * qty;
      pnl += p;
      p >= 0 ? wins++ : losses++;
      delete book[t.symbol];
    }
  }
  return { pnl: Math.round(pnl * 10000) / 10000, wins, losses };
}

// ── Render positions ──
function renderPositions(positions, prices) {
  const tbody = document.getElementById("pos-body");
  const keys = Object.keys(positions);
  document.getElementById("pos-count").textContent = keys.length + " open";

  if (keys.length === 0) {
    tbody.innerHTML = `<tr><td colspan="7" class="empty">No open positions</td></tr>`;
    return 0;
  }

  let totalUnreal = 0;
  tbody.innerHTML = keys.map(sym => {
    const pos = positions[sym];
    const cur = prices[sym];
    if (!cur) return `<tr><td colspan="7" class="empty">${sym} — price unavailable</td></tr>`;

    const entry = pos.entry_price, sl = pos.stop_loss, tp = pos.take_profit, qty = pos.quantity;
    const pnl = (cur - entry) * qty;
    const pct = (cur - entry) / entry * 100;
    totalUnreal += pnl;

    // Progress bar
    const range  = tp - sl || 1;
    const prog   = Math.max(0, Math.min(1, (cur - sl) / range));
    const fillPct = (prog * 100).toFixed(1);
    const barCol = pnl >= 0 ? "var(--green)" : "var(--red)";

    // Status
    let status, statusClass;
    if (cur <= sl * 1.008)       { status = "⚠ Near SL";  statusClass = "badge-red"; }
    else if (cur >= tp * 0.992)  { status = "🎯 Near TP";  statusClass = "badge-green"; }
    else                         { status = "● Holding";   statusClass = "badge-yellow"; }

    // Flash if price changed
    const prev = prevPrices[sym];
    const flashClass = prev ? (cur > prev ? "flash-g" : cur < prev ? "flash-r" : "") : "";

    const coin = sym.replace("USDT","");
    return `<tr class="${flashClass}">
      <td><strong>${coin}</strong></td>
      <td class="mono">$${entry.toFixed(4)}</td>
      <td class="mono"><strong>$${cur.toFixed(4)}</strong></td>
      <td class="mono ${colorClass(pct)}">${pct >= 0 ? "+" : ""}${pct.toFixed(2)}%</td>
      <td class="mono ${colorClass(pnl)}">${pnl >= 0 ? "+" : ""}$${Math.abs(pnl).toFixed(4)}</td>
      <td>
        <div class="bar-wrap">
          <span class="bar-label" style="color:var(--red)">$${sl.toFixed(3)}</span>
          <div class="bar-track"><div class="bar-fill" style="width:${fillPct}%;background:${barCol}"></div></div>
          <span class="bar-label" style="color:var(--green)">$${tp.toFixed(3)}</span>
        </div>
      </td>
      <td><span class="badge ${statusClass}">${status}</span></td>
    </tr>`;
  }).join("");

  return totalUnreal;
}

// ── Render trade history ──
function renderHistory(trades) {
  const book = {};
  const rows = [];
  for (const t of trades) {
    const price = parseFloat(t.price), qty = parseFloat(t.quantity), val = parseFloat(t.value_usd);
    if (t.action === "BUY") {
      book[t.symbol] = price;
      rows.push({ ...t, price, qty, val, pnl: null });
    } else {
      const ep  = book[t.symbol] || price;
      const pnl = (price - ep) * qty;
      rows.push({ ...t, price, qty, val, pnl });
      delete book[t.symbol];
    }
  }

  const tbody = document.getElementById("hist-body");
  const recent = rows.slice().reverse().slice(0, 12);
  if (recent.length === 0) {
    tbody.innerHTML = `<tr><td colspan="8" class="empty">No trades yet</td></tr>`;
    return;
  }

  tbody.innerHTML = recent.map(t => {
    const isBuy  = t.action === "BUY";
    const coin   = t.symbol.replace("USDT", "");
    const pnlStr = t.pnl !== null
      ? `<span class="${colorClass(t.pnl)}">${t.pnl >= 0 ? "+" : ""}$${Math.abs(t.pnl).toFixed(4)}</span>`
      : `<span style="color:var(--muted)">—</span>`;
    const conf = t.confidence ? `${t.confidence}/10` : "—";
    const reason = (t.reason || "").slice(0, 55) + ((t.reason || "").length > 55 ? "…" : "");
    return `<tr>
      <td style="color:var(--muted)">${t.timestamp.slice(0,16)}</td>
      <td><strong>${coin}</strong></td>
      <td><span class="badge ${isBuy ? "badge-buy" : "badge-sell"}">${isBuy ? "🟢 BUY" : "🔴 SELL"}</span></td>
      <td class="mono">$${parseFloat(t.price).toFixed(4)}</td>
      <td class="mono">$${parseFloat(t.value_usd).toFixed(2)}</td>
      <td class="mono">${pnlStr}</td>
      <td style="text-align:center">${conf}</td>
      <td style="color:var(--muted);font-size:12px">${reason}</td>
    </tr>`;
  }).join("");
}

// ── Render sentiment ──
function renderFNG(fng) {
  const val = fng.value;
  let color, emoji;
  if      (val <= 25) { color = "var(--green)";  emoji = "😱 Extreme Fear"; }
  else if (val <= 45) { color = "var(--yellow)";  emoji = "😨 Fear"; }
  else if (val <= 55) { color = "white";           emoji = "😐 Neutral"; }
  else if (val <= 75) { color = "var(--yellow)";  emoji = "😏 Greed"; }
  else                { color = "var(--red)";      emoji = "🤑 Extreme Greed"; }

  document.getElementById("fng-score").textContent = val;
  document.getElementById("fng-score").style.color = color;
  document.getElementById("fng-label").textContent = emoji;
  document.getElementById("fng-marker").style.left = val + "%";
}

// ── Main update loop ──
async function update() {
  document.getElementById("utc").textContent = new Date().toUTCString().slice(5, 25) + " UTC";
  try {
    const [portfolio, fng] = await Promise.all([fetchPortfolio(), fetchFNG()]);
    const { state, trades, budget } = portfolio;
    const positions = state.open_positions || {};
    const spent     = state.spent_this_week || 0;
    const symbols   = Object.keys(positions);

    // Fetch live prices
    const prices = symbols.length > 0 ? await fetchPrices(symbols) : {};

    // Calc P&L
    const { pnl: realised, wins, losses } = calcRealised(trades);
    const unrealised = renderPositions(positions, prices);
    const total      = realised + unrealised;
    const remaining  = budget - spent;

    // KPIs
    document.getElementById("kpi-total").textContent    = (total >= 0 ? "+" : "") + "$" + Math.abs(total).toFixed(4);
    document.getElementById("kpi-total").className      = "value mono " + colorClass(total);
    document.getElementById("kpi-roi").textContent      = "ROI: " + (total >= 0 ? "+" : "") + (total / budget * 100).toFixed(2) + "% on $" + budget;
    document.getElementById("kpi-realised").textContent = (realised >= 0 ? "+" : "") + "$" + Math.abs(realised).toFixed(4);
    document.getElementById("kpi-realised").className   = "value mono " + colorClass(realised);
    document.getElementById("kpi-unreal").textContent   = (unrealised >= 0 ? "+" : "") + "$" + Math.abs(unrealised).toFixed(4);
    document.getElementById("kpi-unreal").className     = "value mono " + colorClass(unrealised);
    document.getElementById("kpi-budget").textContent   = "$" + remaining.toFixed(2);
    document.getElementById("kpi-budget").className     = "value mono " + (remaining > 50 ? "green" : "red");
    document.getElementById("kpi-week").textContent     = "Week of " + (state.week_start || "—");

    // Stats
    document.getElementById("s-week").textContent    = state.week_start || "—";
    document.getElementById("s-budget").textContent  = "$" + budget.toFixed(2);
    document.getElementById("s-spent").textContent   = "$" + spent.toFixed(2);
    const total_closed = wins + losses;
    document.getElementById("s-winrate").textContent = total_closed > 0 ? `${wins}/${total_closed} (${(wins/total_closed*100).toFixed(0)}%)` : "—";
    document.getElementById("s-open").textContent    = symbols.length;

    // History + sentiment
    renderHistory(trades);
    renderFNG(fng);
    prevPrices = { ...prices };

  } catch(e) {
    console.error("Update error:", e);
  }
}

// ── Countdown timer ──
function tick() {
  countdown--;
  document.getElementById("countdown").textContent = `Refresh in ${countdown}s`;
  if (countdown <= 0) {
    countdown = 30;
    update();
  }
}

// Boot
update();
setInterval(tick, 1000);
</script>
</body>
</html>"""


if __name__ == "__main__":
    os.chdir(os.path.dirname(os.path.abspath(__file__)))
    print(f"\n  🤖 Trading Dashboard")
    print(f"  ───────────────────────────────")
    print(f"  Open in browser → http://localhost:{PORT}")
    print(f"  Auto-refreshes every 30 seconds")
    print(f"  Press Ctrl+C to stop\n")
    server = HTTPServer(("localhost", PORT), Handler)
    server.serve_forever()
