"""T1-101 B-2..B-6 — die Flaeche.

## Woher die Gestaltung kommt

Aus den t1-Tokens (`t1.ordertune.com/src/app/globals.css`), **nicht** aus dem
Quiet-Luxury-Papier von ordertune.com: weisser Grund, kuehlgraue Flaechen,
Inter, ein Akzent `#c8f23e`, Radius 6 px, Ampelfarben `#16a34a` / `#d97706` /
`#dc2626`. Der Nutzer kommt aus dem Einrichtungs-Assistenten auf t1 — das
Cockpit muss aussehen wie die Flaeche, von der er kommt.

Die Tokens sind eine **Kopie**, keine Verknuepfung. Ein Einbinden zur Bauzeit
koppelte zwei Repos mit verschiedenen Veroeffentlichungstakten; ein Nachladen
zur Laufzeit braeche ausgerechnet auf der Maschine mit dem Netzproblem — also
dann, wenn das Cockpit gebraucht wird.

## Die Regeln, die hier sichtbar eingehalten werden

  * **Urteil zuerst, Protokoll zuletzt.** Ein Satz oben, drei Laempchen, dann
    der Beleg. Die Rohzeilen liegen im Reiter „Details".
  * **Das Alter rechnet die Seite selbst**, aus einem Zeitpunkt des Servers,
    und zaehlt weiter, auch wenn der Strom schweigt. Genau dann ist es die
    wichtigste Angabe.
  * **„Keine Auskunft" ist ein eigener Zustand.** `null` heisst nicht „nichts
    da" — bei Positionen (T1-99) wie bei Auftraegen.
  * **Nichts aus dem Netz.** Kein CDN, keine Schrift von aussen.
  * **Es wird nichts freigegeben.** Kein Knopf sendet, storniert oder gibt
    frei. Das Pull-Pattern ist das §32-KWG-Schutzschild; das Cockpit liest.

Nutzertexte englisch, keine Emojis.
"""
from __future__ import annotations

PAGE_HTML = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Ordertune Bridge</title>
<style>
:root {
  /* Kopie der t1-Tokens. Gegenstueck: t1.ordertune.com/src/app/globals.css */
  --bg: #ffffff; --surface: #f5f7fa; --surface-2: #eef1f5; --surface-3: #e6eaf0;
  --fg-1: #18181b; --fg-2: #52525b; --fg-3: #a1a1aa;
  --border: #d4d8df; --border-strong: #b9bec7;
  --lime: #c8f23e; --lime-ink: #0a0a0a;
  --ok: #16a34a; --warn: #d97706; --bad: #dc2626;
  --radius: 6px;
  --sans: "Inter", system-ui, -apple-system, "Segoe UI", Roboto, sans-serif;
  --mono: ui-monospace, "SF Mono", Menlo, Consolas, monospace;
}
* { box-sizing: border-box; }
body { margin: 0; background: var(--bg); color: var(--fg-1); font-family: var(--sans);
       font-size: 14px; line-height: 1.5; }
.shell { max-width: 60rem; margin: 0 auto; padding: 2rem 1.5rem 4rem; }
header { display: flex; align-items: baseline; gap: .75rem; margin-bottom: 1.5rem; }
header h1 { font-size: .8rem; letter-spacing: .08em; text-transform: uppercase;
            color: var(--fg-2); margin: 0; font-weight: 600; }
header .ver { font-family: var(--mono); font-size: .75rem; color: var(--fg-3); }

.verdict { font-size: 1.5rem; font-weight: 600; letter-spacing: -.01em; margin: 0 0 1rem; }
.verdict.bad { color: var(--bad); }
.verdict.warn { color: var(--warn); }

.lights { display: flex; gap: .5rem; flex-wrap: wrap; margin-bottom: 2rem; }
.light { display: inline-flex; align-items: center; gap: .5rem; padding: .35rem .7rem;
         background: var(--surface); border: 1px solid var(--border);
         border-radius: var(--radius); font-size: .8rem; }
.dot { width: .5rem; height: .5rem; border-radius: 50%; background: var(--fg-3); }
.dot.ok { background: var(--ok); } .dot.warn { background: var(--warn); }
.dot.bad { background: var(--bad); }

.card { border: 1px solid var(--border); border-left: 3px solid var(--bad);
        background: var(--surface); border-radius: var(--radius);
        padding: 1rem 1.25rem; margin-bottom: 2rem; }
.card h2 { margin: 0 0 .5rem; font-size: .95rem; }
.card pre { font-family: var(--mono); font-size: .78rem; white-space: pre-wrap;
            color: var(--fg-2); margin: .5rem 0 0; }
.card a { color: var(--fg-1); }

nav { display: flex; gap: .25rem; border-bottom: 1px solid var(--border); margin-bottom: 1.5rem; }
nav button { background: none; border: 0; border-bottom: 2px solid transparent;
             padding: .5rem .9rem; font: inherit; color: var(--fg-2); cursor: pointer; }
nav button[aria-selected="true"] { color: var(--fg-1); border-bottom-color: var(--lime); font-weight: 600; }

section h2 { font-size: .75rem; letter-spacing: .08em; text-transform: uppercase;
             color: var(--fg-2); margin: 2rem 0 .6rem; font-weight: 600; }
section:first-of-type h2 { margin-top: 0; }
dl { display: grid; grid-template-columns: minmax(9rem, 14rem) 1fr; gap: .3rem 1rem; margin: 0; }
dt { color: var(--fg-2); }
dd { margin: 0; font-variant-numeric: tabular-nums; }
.mono { font-family: var(--mono); font-size: .8rem; word-break: break-all; }
.muted { color: var(--fg-3); }

.scroll { overflow-x: auto; }
table { border-collapse: collapse; width: 100%; font-size: .85rem; }
th { text-align: left; font-weight: 600; color: var(--fg-2); font-size: .72rem;
     text-transform: uppercase; letter-spacing: .06em; }
th, td { padding: .45rem .75rem .45rem 0; border-bottom: 1px solid var(--surface-3);
         white-space: nowrap; }
td.reason { white-space: normal; color: var(--bad); font-size: .8rem; }
.pill { display: inline-block; padding: .1rem .5rem; border-radius: 999px;
        background: var(--surface-2); border: 1px solid var(--border);
        font-size: .75rem; }
.pill.bad { background: #fee2e2; border-color: #fecaca; color: #991b1b; }
.pill.ok { background: #dcfce7; border-color: #bbf7d0; color: #14532d; }

#loglines { font-family: var(--mono); font-size: .74rem; white-space: pre-wrap;
            background: var(--surface); border: 1px solid var(--border);
            border-radius: var(--radius); padding: .75rem; max-height: 30rem;
            overflow: auto; margin: 0; }
button.action { font: inherit; cursor: pointer; background: var(--lime);
                color: var(--lime-ink); border: 0; border-radius: var(--radius);
                padding: .45rem .9rem; font-weight: 600; }
button.action:disabled { background: var(--surface-3); color: var(--fg-3); cursor: default; }
input, select, textarea { font: inherit; background: var(--bg); color: var(--fg-1);
  border: 1px solid var(--border); border-radius: var(--radius); padding: .3rem .5rem; }
textarea { width: 100%; font-family: var(--mono); font-size: .78rem; }
.note { font-size: .8rem; margin-left: .5rem; }
.note.ok { color: var(--ok); } .note.bad { color: var(--bad); }
.steps { list-style: none; padding: 0; counter-reset: s; }
.steps li { border-left: 2px solid var(--surface-3); padding: 0 0 1.5rem 1.25rem; }
.steps h3 { font-size: .9rem; margin: 0 0 .35rem; }
.steps p { margin: .35rem 0; }
.banner { background: var(--surface-2); border: 1px solid var(--border);
  border-left: 3px solid var(--warn); border-radius: var(--radius);
  padding: .6rem .9rem; margin-bottom: 1.5rem; font-size: .85rem; }
@media (prefers-color-scheme: dark) {
  :root { --bg: #0a0a0a; --surface: #111111; --surface-2: #171717; --surface-3: #1f1f1f;
          --fg-1: #fafafa; --fg-2: #a3a3a3; --fg-3: #6b6b6b;
          --border: #262626; --border-strong: #3a3a3a; }
  .pill.bad { background: #2a1112; border-color: #4a1d1f; color: #fca5a5; }
  .pill.ok { background: #0f2417; border-color: #1c3d28; color: #86efac; }
}
</style>
</head>
<body>
<div class="shell">
  <header><h1>Ordertune Bridge</h1><span class="ver" id="ver"></span></header>

  <div class="banner" id="restart" hidden>
    A setting was changed. It takes effect the next time the Bridge starts.
  </div>

  <p class="verdict" id="verdict">Connecting...</p>
  <div class="lights">
    <span class="light"><span class="dot" id="d-tws"></span> TWS</span>
    <span class="light"><span class="dot" id="d-ot"></span> Ordertune</span>
    <span class="light"><span class="dot" id="d-acct"></span> Account</span>
    <span class="light"><span class="dot" id="d-write"></span> Order access</span>
  </div>

  <div class="card" id="card" hidden>
    <h2 id="card-title"></h2>
    <pre id="card-detail"></pre>
    <pre id="card-action"></pre>
  </div>

  <div id="setup" hidden>
    <ol class="steps">
      <li>
        <h3>1 &middot; Put your bridge.env here</h3>
        <p class="muted">Download it from Ordertune (Settings -&gt; Broker) and paste the
        whole block. You never have to type a token by hand.</p>
        <textarea id="envbox" rows="7" spellcheck="false"
          placeholder="ORDERTUNE_API_BASE=https://t1.ordertune.com&#10;ORDERTUNE_BRIDGE_TOKEN=...&#10;ORDERTUNE_BRIDGE_CONNECTION_ID=..."></textarea>
        <p><button class="action" id="s1">Save bridge.env</button>
           <span class="note" id="s1msg"></span></p>
      </li>
      <li>
        <h3>2 &middot; Find TWS</h3>
        <p class="muted">The socket port is a setting in TWS - it does not follow from
        the account type. This checks the four IBKR defaults.</p>
        <p><button class="action" id="s2">Search for TWS</button>
           <span class="note" id="s2msg"></span></p>
        <div id="s2ports"></div>
      </li>
      <li>
        <h3>3 &middot; Check the port</h3>
        <p><button class="action" id="s3">Check</button>
           <span class="note" id="s3msg"></span></p>
      </li>
      <li>
        <h3>4 &middot; Check the credentials</h3>
        <p><button class="action" id="s4">Check with Ordertune</button>
           <span class="note" id="s4msg"></span></p>
      </li>
    </ol>
    <p class="muted">The Bridge starts on its own as soon as bridge.env is readable.
    This window then turns into the cockpit.</p>
  </div>

  <nav id="tabs">
    <button id="tab-status" aria-selected="true" onclick="showTab('status')">Status</button>
    <button id="tab-settings" aria-selected="false" onclick="showTab('settings')">Settings</button>
    <button id="tab-details" aria-selected="false" onclick="showTab('details')">Details</button>
  </nav>

  <div id="pane-status">
    <section>
      <h2>Connection</h2>
      <dl>
        <dt>Last heartbeat</dt><dd id="hb">-</dd>
        <dt>Last order poll</dt><dd id="poll">-</dd>
        <dt>Connected since</dt><dd id="since">-</dd>
      </dl>
    </section>
    <section>
      <h2>Orders</h2>
      <div id="orders" class="scroll muted">no order data yet</div>
    </section>
    <section>
      <h2>Account</h2>
      <dl>
        <dt>Currency</dt><dd id="ccy">-</dd>
        <dt>Cash</dt><dd id="cash">-</dd>
        <dt>Equity</dt><dd id="equity">-</dd>
      </dl>
      <div id="positions" class="scroll muted" style="margin-top:.75rem">no position data yet</div>
    </section>
  </div>

  <div id="pane-settings" hidden>
    <section>
      <h2>Connection to TWS</h2>
      <dl>
        <dt><label for="f-port">Socket port</label></dt>
        <dd><select id="f-portsel"></select>
            <input id="f-port" type="number" min="1" max="65535" style="width:7rem">
            <button class="action" id="f-probe" type="button">Search</button>
            <span class="note" id="f-probemsg"></span></dd>
        <dt><label for="f-cid">Client id</label></dt>
        <dd><input id="f-cid" type="number" min="0" max="999" style="width:7rem">
            <span class="muted">unique per API connection to one TWS</span></dd>
      </dl>
    </section>
    <section>
      <h2>Behaviour</h2>
      <dl>
        <dt><label for="f-log">Log level</label></dt>
        <dd><select id="f-log">
          <option>DEBUG</option><option>INFO</option>
          <option>WARNING</option><option>ERROR</option></select></dd>
        <dt><label for="f-upd">Check for updates</label></dt>
        <dd><input id="f-upd" type="checkbox"></dd>
      </dl>
      <p style="margin-top:1rem">
        <button class="action" id="f-save">Save</button>
        <span class="note" id="f-savemsg"></span></p>
    </section>
    <section>
      <h2>Credentials</h2>
      <dl>
        <dt>Ordertune server</dt><dd class="mono" id="f-base">-</dd>
        <dt>Connection id</dt><dd class="mono" id="f-conn">-</dd>
        <dt>Access token</dt><dd class="mono" id="f-token">-</dd>
      </dl>
      <p class="muted" style="margin-top:.75rem">These are never typed here. To replace
      them, download a fresh bridge.env from Ordertune and paste the whole block:</p>
      <textarea id="f-env" rows="6" spellcheck="false"></textarea>
      <p><button class="action" id="f-replace">Replace bridge.env</button>
         <span class="note" id="f-replacemsg"></span></p>
    </section>
  </div>

  <div id="pane-details" hidden>
    <section>
      <h2>This bridge</h2>
      <dl>
        <dt>Version</dt><dd id="d-ver">-</dd>
        <dt>TWS endpoint</dt><dd id="endpoint">-</dd>
        <dt>Client id</dt><dd id="cid">-</dd>
        <dt>Hardware fingerprint</dt><dd class="mono" id="fp">-</dd>
        <dt>Ordertune server</dt><dd class="mono" id="api">-</dd>
        <dt>Log file</dt><dd class="mono" id="log">-</dd>
      </dl>
      <p style="margin-top:1rem"><button class="action" id="copy">Copy diagnostics</button>
      <span id="copied" class="muted"></span></p>
    </section>
    <section>
      <h2>Log</h2>
      <pre id="loglines" class="muted">Loading...</pre>
    </section>
  </div>
</div>

<script>
const token = new URLSearchParams(location.search).get("t") || "";
const q = (id) => document.getElementById(id);
const withToken = (p) => p + "?t=" + encodeURIComponent(token);
let state = null;

// Das Alter wird HIER gerechnet, aus einem Zeitpunkt des Servers. Eine
// stehende Zeitangabe, die aussieht wie eine laufende, ist eine dauerhaft
// falsche Aussage.
function age(iso) {
  if (!iso) return "-";
  const s = Math.max(0, Math.round((Date.now() - Date.parse(iso)) / 1000));
  if (s < 90) return s + " s ago";
  const m = Math.round(s / 60);
  return m < 90 ? m + " min ago" : Math.round(m / 60) + " h ago";
}
function money(v, ccy) {
  if (v === null || v === undefined) return "-";
  return v.toLocaleString("en-US", {minimumFractionDigits: 2, maximumFractionDigits: 2})
       + (ccy ? " " + ccy : "");
}
function dot(el, level) { el.className = "dot" + (level ? " " + level : ""); }
function esc(s) {
  return String(s ?? "").replace(/[&<>"]/g, c =>
    ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]));
}

// Der Heartbeat geht alle 60 s raus. Bleibt er 90 s aus, stimmt etwas nicht --
// und diese Angabe ist dann die wichtigste auf der Seite. Dieselbe Frist, aus
// der auf der Plattform der Offline-Erkenner arbeitet.
const HEARTBEAT_STALE_S = 90;
function secondsSince(iso) {
  return iso ? (Date.now() - Date.parse(iso)) / 1000 : Infinity;
}
function heartbeatStale(s) {
  // Noch kein Herzschlag heisst NICHT ueberfaellig: unmittelbar nach dem
  // Verbinden ist der erste noch unterwegs. Ein falsches Rot in den ersten
  // Augenblicken jedes Starts waere genau die Sorte Aussage, gegen die dieser
  // Vorgang gebaut wurde.
  if (!s.last_heartbeat_at) return false;
  return s.tws_connected && secondsSince(s.last_heartbeat_at) > HEARTBEAT_STALE_S;
}

function verdict(s) {
  if (s.failure_headline) return [s.failure_headline, "bad"];
  if (!s.tws_connected) return ["Not connected to TWS", "bad"];
  if (heartbeatStale(s))
    return ["No heartbeat for over " + HEARTBEAT_STALE_S + " s", "warn"];
  if (s.write_access === "read_only_confirmed")
    return ["TWS is running with Read-Only API. Orders will be rejected.", "bad"];
  if (s.write_access === "read_only_suspected")
    return ["TWS did not answer the open-orders request. Orders may be rejected.", "warn"];
  if (!s.ordertune_ok) return ["Not reporting to Ordertune", "warn"];
  return ["Connected - waiting for releases", ""];
}

function renderOrders(s) {
  const box = q("orders");
  if (s.orders === null || s.orders === undefined) {
    box.className = "scroll muted"; box.textContent = "no order data yet"; return;
  }
  if (s.orders.length === 0) {
    box.className = "scroll"; box.textContent = "No orders of ours at IBKR right now."; return;
  }
  box.className = "scroll";
  box.innerHTML = "<table><tr><th>Symbol</th><th>Side</th><th>Qty</th><th>Status</th>"
    + "<th>Reason</th></tr>" + s.orders.map(o =>
      "<tr><td>" + esc(o.symbol) + "</td><td>" + esc(o.action) + "</td><td>"
      + esc(o.qty ?? "-") + "</td><td><span class='pill "
      + (o.status === "Rejected" ? "bad" : o.status === "Filled" ? "ok" : "")
      + "'>" + esc(o.status) + "</span></td><td class='reason'>"
      + esc(o.reason ?? "") + "</td></tr>").join("") + "</table>";
}

function renderPositions(s) {
  const box = q("positions");
  if (s.positions === null || s.positions === undefined) {
    // T1-99: NICHT dasselbe wie eine leere Tabelle.
    box.className = "scroll muted"; box.textContent = "no position data yet"; return;
  }
  if (s.positions.length === 0) {
    box.className = "scroll"; box.textContent = "The account holds no positions."; return;
  }
  box.className = "scroll";
  box.innerHTML = "<table><tr><th>Symbol</th><th>Qty</th><th>Avg cost</th></tr>"
    + s.positions.map(p => "<tr><td>" + esc(p.symbol) + "</td><td>"
      + esc(p.qty ?? p.position ?? "-") + "</td><td>"
      + esc(p.avgCost ?? p.avg_cost ?? "-") + "</td></tr>").join("") + "</table>";
}

function renderCard(s) {
  const card = q("card");
  const readOnly = s.write_access === "read_only_confirmed";
  if (!s.failure_headline && !readOnly) { card.hidden = true; return; }
  card.hidden = false;
  if (s.failure_headline) {
    q("card-title").textContent = s.failure_headline;
    q("card-detail").textContent = (s.failure_detail || []).join("\\n");
    q("card-action").textContent = (s.failure_action || []).join("\\n");
  } else {
    q("card-title").textContent = "Read-Only API is switched on in TWS";
    q("card-detail").textContent = s.write_access_detail || "";
    q("card-action").textContent =
      "Everything else looks healthy - positions arrive, heartbeats go out - but\\n"
      + "every order will be rejected.\\n\\n"
      + "In TWS: File -> Global Configuration -> API -> Settings.\\n"
      + "Turn OFF 'Read-Only API', then restart TWS.\\n"
      + "TWS may also be showing a dialog box that nobody sees on a VPS.";
  }
}

function render() {
  if (!state) return;
  const s = state;

  // Im Assistenten gibt es noch nichts zu berichten — dann steht er allein da.
  const setup = !!s.setup_mode;
  q("setup").hidden = !setup;
  q("tabs").hidden = setup;
  // Im Assistenten alles zu; sonst NICHT anfassen, sonst hebt der naechste
  // Takt jeden Reiterwechsel wieder auf. `hidden = setup || undefined` hat
  // genau das getan: ausserhalb des Assistenten wurde daraus `false`, und
  // alle drei Reiter standen gleichzeitig offen.
  if (setup) {
    for (const n of ["status", "settings", "details"]) q("pane-" + n).hidden = true;
  }
  if (setup) {
    q("verdict").textContent = "Set up the Bridge";
    q("verdict").className = "verdict";
    q("card").hidden = !s.failure_headline;
    if (s.failure_headline) {
      q("card-title").textContent = s.failure_headline;
      q("card-detail").textContent = (s.failure_detail || []).join("\\n");
      q("card-action").textContent = (s.failure_action || []).join("\\n");
    }
    return;
  }
  if (q("pane-status").hidden && q("pane-settings").hidden && q("pane-details").hidden) {
    showTab("status");  // Uebergang Assistent -> Cockpit
  }
  q("restart").hidden = !s.pending_restart;

  const [text, level] = verdict(s);
  q("verdict").textContent = text;
  q("verdict").className = "verdict" + (level ? " " + level : "");

  dot(q("d-tws"), s.tws_connected ? "ok" : "bad");
  dot(q("d-ot"), !s.ordertune_ok || heartbeatStale(s) ? "warn" : "ok");
  dot(q("d-acct"), s.account_known ? "ok" : "warn");
  dot(q("d-write"), s.write_access === "writable" ? "ok"
      : s.write_access === "unknown" ? "" : "bad");

  q("hb").textContent = s.last_heartbeat_at
    ? age(s.last_heartbeat_at) + (heartbeatStale(s) ? " - overdue" : "")
    : "waiting for the first one";
  q("hb").style.color = heartbeatStale(s) ? "var(--warn)" : "";
  q("poll").textContent = age(s.last_pending_poll_at);
  q("since").textContent = age(s.session_connected_at);
  q("ccy").textContent = s.currency || "-";
  q("cash").textContent = money(s.cash, s.currency);
  q("equity").textContent = money(s.equity, s.currency);

  q("ver").textContent = s.bridge_version ? "v" + s.bridge_version : "";
  q("d-ver").textContent = s.bridge_version || "-";
  q("endpoint").textContent = s.gateway_host ? s.gateway_host + ":" + s.gateway_port : "-";
  q("cid").textContent = s.client_id ?? "-";
  q("fp").textContent = s.fingerprint_prefix || "-";
  q("api").textContent = s.api_base || "-";
  q("log").textContent = s.log_path || "-";

  renderCard(s); renderOrders(s); renderPositions(s);
}

function showTab(name) {
  for (const n of ["status", "settings", "details"]) {
    q("pane-" + n).hidden = n !== name;
    q("tab-" + n).setAttribute("aria-selected", String(n === name));
  }
  if (name === "details") loadLog();
  if (name === "settings") loadConfig();
}

// ── T1-101 C: Assistent und Einstellungen ───────────────────────────────────
//
// Die Flaeche schickt einen Wunsch, der Server schreibt bridge.env. Angewandt
// wird nichts: die IBKR-Verbindung gehoert dem Hauptthread des Kerns.

let baseline = "";
const post = (pfad, body) =>
  fetch(withToken(pfad), {method: "POST", body: JSON.stringify(body || {})})
    .then(r => r.json());

function note(id, res) {
  const el = q(id);
  el.textContent = res.message || (res.ok ? "OK" : "Failed");
  el.className = "note " + (res.ok ? "ok" : "bad");
  return res;
}

function loadConfig() {
  fetch(withToken("/config")).then(r => r.json()).then(c => {
    baseline = c.fingerprint || "";
    const v = c.values || {};
    const sel = q("f-portsel");
    sel.innerHTML = "<option value=''>custom</option>" + (c.ports || []).map(p =>
      "<option value='" + p.port + "'>" + p.port + " - " + esc(p.label) + "</option>").join("");
    q("f-port").value = v.IBKR_GATEWAY_PORT || "7497";
    sel.value = (c.ports || []).some(p => String(p.port) === q("f-port").value)
      ? q("f-port").value : "";
    q("f-cid").value = v.IBKR_CLIENT_ID || "17";
    q("f-log").value = v.LOG_LEVEL || "INFO";
    q("f-upd").checked = String(v.UPDATE_CHECK_ENABLED || "true").toLowerCase() !== "false";
    q("f-base").textContent = v.ORDERTUNE_API_BASE || "-";
    q("f-conn").textContent = v.ORDERTUNE_BRIDGE_CONNECTION_ID || "-";
    // D9: nur die Endung. Genug, um zwei Dateien zu unterscheiden, zu wenig,
    // um damit etwas anzufangen.
    q("f-token").textContent = v.ORDERTUNE_BRIDGE_TOKEN || "-";
  });
}

q("f-portsel").addEventListener("change", (e) => {
  if (e.target.value) q("f-port").value = e.target.value;
});
q("f-probe").addEventListener("click", () => {
  post("/probe", {}).then(r => {
    const gefunden = r.answering || [];
    note("f-probemsg", {ok: gefunden.length > 0, message: gefunden.length
      ? "Answering: " + gefunden.map(a => a.port + " (" + a.label + ")").join(", ")
      : "Nothing answers on any of the four IBKR default ports."});
    if (gefunden.length === 1) q("f-port").value = gefunden[0].port;
  });
});
q("f-save").addEventListener("click", () => {
  post("/settings", {baseline: baseline, changes: {
    IBKR_GATEWAY_PORT: q("f-port").value,
    IBKR_CLIENT_ID: q("f-cid").value,
    LOG_LEVEL: q("f-log").value,
    UPDATE_CHECK_ENABLED: q("f-upd").checked ? "true" : "false",
  }}).then(r => { note("f-savemsg", r); if (r.fingerprint) baseline = r.fingerprint; });
});
q("f-replace").addEventListener("click", () => {
  post("/credentials", {content: q("f-env").value}).then(r => {
    note("f-replacemsg", r);
    if (r.ok) { q("f-env").value = ""; loadConfig(); }
  });
});

q("s1").addEventListener("click", () => {
  post("/credentials", {content: q("envbox").value}).then(r => note("s1msg", r));
});
q("s2").addEventListener("click", () => {
  post("/probe", {}).then(r => {
    const gefunden = r.answering || [];
    note("s2msg", {ok: gefunden.length > 0, message: gefunden.length
      ? "Found " + gefunden.length + " answering port(s)."
      : "Nothing answers. Start TWS or IB Gateway and log in."});
    q("s2ports").innerHTML = gefunden.map(a =>
      "<p>" + a.port + " - " + esc(a.label)
      + " <button class='action' onclick=\\"takePort(" + a.port + ")\\">Use this</button></p>"
    ).join("");
  });
});
function takePort(port) {
  post("/settings", {baseline: "", changes: {IBKR_GATEWAY_PORT: String(port)}})
    .then(r => note("s2msg", r));
}
q("s3").addEventListener("click", () => {
  fetch(withToken("/config")).then(r => r.json()).then(c =>
    post("/probe", {port: (c.values || {}).IBKR_GATEWAY_PORT || 7497})
  ).then(r => note("s3msg", r));
});
q("s4").addEventListener("click", () => {
  post("/verify", {}).then(r => note("s4msg", r));
});

function loadLog() {
  fetch(withToken("/log")).then(r => r.json()).then(d => {
    const box = q("loglines");
    box.className = "";
    box.textContent = (d.lines || []).join("\\n") || "(nothing logged yet)";
    box.scrollTop = box.scrollHeight;
  }).catch(() => { q("loglines").textContent = "(log unavailable)"; });
}

q("copy").addEventListener("click", () => {
  fetch(withToken("/diagnostics")).then(r => r.json()).then(d => {
    const text = JSON.stringify(d, null, 2);
    const done = () => { q("copied").textContent = " copied"; };
    if (navigator.clipboard) navigator.clipboard.writeText(text).then(done, done);
    else done();
  });
});

new EventSource(withToken("/events")).onmessage = (e) => {
  state = JSON.parse(e.data).state; render();
};
fetch(withToken("/state")).then(r => r.json()).then(d => { state = d.state; render(); });
// Die Uhr laeuft unabhaengig vom Strom weiter, damit das Alter auch dann
// waechst, wenn nichts mehr kommt — genau dann ist es die wichtigste Angabe.
setInterval(render, 1000);
</script>
</body>
</html>
"""
