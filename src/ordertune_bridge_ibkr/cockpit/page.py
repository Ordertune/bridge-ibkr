"""T1-101 — die Flaeche des Cockpits.

## Woher die Gestaltung kommt

Aus dem **Ordertune-Design-System**: beiges Papier (`#F4EFE6`), Tinte statt
reinem Schwarz (`#2A2A2A`), ein einziger Akzent (`#C8F23E`), Inter selbst
gehostet, kaum Rahmen. Die erste Fassung nahm die t1-Tokens (weiss/kuehlgrau)
mit der Begruendung, der Nutzer komme aus dem Einrichtungs-Assistenten auf t1.
Der Owner hat entschieden: eine Sprache mit ordertune.com.

## Was das konkret geaendert hat

Der erste Entwurf verstiess gegen drei Regeln des Systems, jede davon
ausdruecklich aufgeschrieben:

  * **Ampelfarben.** `#dc2626` ist Trader-Rot, und das ist verboten — „red is
    for losses we want to talk *with*, not panic about". Fehlertext ist
    `--data-neg-2` (weiches Ocker). Wo es wirklich laut werden muss, benutzt
    die Marke ihr eigenes Mittel: den **schwarzen Statement-Block**.
  * **Karte mit farbigem linken Rand.** Steht woertlich auf der Verbotsliste.
  * **Vier bunte Laempchen.** Das System kennt genau einen Statuspunkt, in
    genau zwei Zustaenden: Lime (live) oder `--fg-2` (idle). Die Bedeutung
    traegt das Wort daneben, nicht die Farbe — was fuer eine Betriebsflaeche
    ohnehin die bessere Bauform ist.

Dazu: **ein Lime-Knopf je Ansicht**, keine Icons, keine Emojis, keine
Unicode-Piktogramme, Ziffern immer `tabular-nums`, Unterzeilen nie fett.

## Die Regeln, die aus dem Entwurf bleiben

  * **Das Alter rechnet die Seite selbst**, aus einem Zeitpunkt des Servers,
    und zaehlt weiter, auch wenn der Strom schweigt.
  * **„Keine Auskunft" ist ein eigener Zustand.** `null` heisst nicht „nichts
    da" — bei Positionen (T1-99) wie bei Auftraegen.
  * **Nichts aus dem Netz.** Schrift und Icon liegen als Base64 daneben.
  * **Es wird nichts freigegeben.** Kein Knopf sendet, storniert oder gibt
    frei. Das Pull-Pattern ist das §32-KWG-Schutzschild; das Cockpit liest.

Nutzertexte englisch.
"""
from __future__ import annotations

from .assets import ICON_PNG, INTER_400, INTER_500, INTER_600, INTER_700


def _schrift(gewicht: int, daten: str) -> str:
    return (
        f"@font-face{{font-family:Inter;font-style:normal;font-weight:{gewicht};"
        f"font-display:swap;src:url(data:font/woff2;base64,{daten}) "
        "format('woff2')}"
    )


FONT_FACES = "".join(
    _schrift(g, d)
    for g, d in (
        (400, INTER_400), (500, INTER_500), (600, INTER_600), (700, INTER_700)
    )
)

PAGE_HTML = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Ordertune Bridge</title>
<link rel="icon" href="data:image/png;base64,""" + ICON_PNG + """">
<style>
""" + FONT_FACES + """
:root {
  /* Kopie der Ordertune-Tokens. Gegenstueck: das Design-System-Verzeichnis. */
  --beige: #F4EFE6; --beige-soft: #ECE6DA; --beige-deep: #E4DDCC;
  --black: #0E0E0E; --ink: #2A2A2A;
  --fg-1: #1F1F1F; --fg-2: #5A5A55; --fg-3: #8A867D;
  --inv-1: #F4EFE6; --inv-2: #B5B0A6; --inv-3: #6F6B62;
  --lime: #C8F23E; --lime-deep: #B6DF2B; --lime-ink: #0E0E0E;
  --pos: #5E9C2E; --neg: #C99A82;
  --hair: rgba(31,31,31,0.08); --soft: rgba(31,31,31,0.14);
  --hair-dark: rgba(255,255,255,0.10);
  --r-xs: 4px; --r-sm: 6px; --r-md: 10px; --r-pill: 999px;
  --sans: Inter, system-ui, -apple-system, "Segoe UI", Roboto, sans-serif;
  --mono: ui-monospace, "SF Mono", Menlo, Consolas, monospace;
}
* { box-sizing: border-box; }
html { -webkit-font-smoothing: antialiased; }
body { margin: 0; background: var(--beige); color: var(--ink);
       font-family: var(--sans); font-size: 15px; line-height: 1.55;
       font-weight: 400; }
.shell { max-width: 62rem; margin: 0 auto; padding: 40px 24px 96px; }

/* ── Kopf ──────────────────────────────────────────────────────────── */
header { display: flex; align-items: center; gap: 12px; margin-bottom: 48px; }
header img { width: 28px; height: 28px; border-radius: var(--r-xs); display: block; }
.eyebrow { text-transform: uppercase; letter-spacing: .12em; font-size: 12px;
           color: var(--fg-2); font-weight: 500; }
header .ver { margin-left: auto; font-size: 12px; color: var(--fg-3);
              font-variant-numeric: tabular-nums; }

/* ── Urteil ────────────────────────────────────────────────────────── */
.verdict { font-size: 30px; line-height: 1.2; letter-spacing: -0.02em;
           font-weight: 700; color: var(--fg-1); margin: 0 0 20px;
           max-width: 34ch; }

/* Der schwarze Statement-Block ist das Mittel der Marke, wenn es laut werden
   muss. Kein Rot, kein farbiger Randstreifen — beides steht auf der
   Verbotsliste des Systems. */
.statement { background: var(--black); color: var(--inv-1);
             border-radius: var(--r-md); padding: 28px 32px; margin: 0 0 32px; }
.statement h2 { margin: 0 0 14px; font-size: 22px; line-height: 1.25;
                letter-spacing: -0.01em; font-weight: 700; max-width: 40ch; }
.statement pre { font-family: var(--mono); font-size: 12.5px; line-height: 1.6;
                 white-space: pre-wrap; color: var(--inv-2); margin: 0; }
.statement pre + pre { margin-top: 14px; padding-top: 14px;
                       border-top: 1px solid var(--hair-dark); }

/* ── Statuspunkte: Lime oder idle. Die Bedeutung traegt das Wort. ──── */
.chips { display: flex; gap: 8px; flex-wrap: wrap; margin-bottom: 44px; }
.chip { display: inline-flex; align-items: center; gap: 8px;
        padding: 6px 14px 6px 12px; background: var(--beige-soft);
        border: 1px solid var(--hair); border-radius: var(--r-pill);
        font-size: 13px; color: var(--fg-2); }
.dot { width: 7px; height: 7px; border-radius: 50%; background: var(--fg-3);
       flex: none; }
.dot.live { background: var(--lime-deep); }

/* ── Reiter ────────────────────────────────────────────────────────── */
nav { display: flex; gap: 4px; border-bottom: 1px solid var(--hair);
      margin-bottom: 36px; }
nav button { background: none; border: 0; border-bottom: 2px solid transparent;
             padding: 10px 16px; font: inherit; font-size: 14px;
             color: var(--fg-2); cursor: pointer; margin-bottom: -1px; }
nav button[aria-selected="true"] { color: var(--fg-1); font-weight: 600;
                                   border-bottom-color: var(--lime); }

/* ── Abschnitte ────────────────────────────────────────────────────── */
section { margin-bottom: 44px; }
section h2 { text-transform: uppercase; letter-spacing: .12em; font-size: 12px;
             color: var(--fg-2); font-weight: 500; margin: 0 0 16px; }
dl { display: grid; grid-template-columns: minmax(9rem, 15rem) 1fr;
     gap: 10px 24px; margin: 0; }
dt { color: var(--fg-2); font-size: 14px; }
dd { margin: 0; font-variant-numeric: tabular-nums; color: var(--fg-1); }
.mono { font-family: var(--mono); font-size: 12.5px; word-break: break-all;
        color: var(--fg-2); }
.muted { color: var(--fg-3); }
.warn { color: var(--neg); }

/* ── Tabellen: schlichte Zellen, keine Sortierpfeile, keine Badges ──── */
.scroll { overflow-x: auto; }
table { border-collapse: collapse; width: 100%; font-size: 14px;
        font-variant-numeric: tabular-nums; }
th { text-align: left; font-weight: 500; color: var(--fg-2); font-size: 11px;
     text-transform: uppercase; letter-spacing: .1em; padding-bottom: 10px;
     border-bottom: 1px solid var(--soft); white-space: nowrap; }
td { padding: 11px 20px 11px 0; border-bottom: 1px solid var(--hair);
     white-space: nowrap; color: var(--fg-1); }
th { padding-right: 20px; }
td.state { color: var(--fg-2); }
td.state.done { color: var(--pos); }
td.state.gone { color: var(--neg); }
td.reason { white-space: normal; color: var(--neg); font-size: 13px;
            max-width: 34rem; }

/* ── Knoepfe: genau EINER in Lime je Ansicht ───────────────────────── */
button.action { font: inherit; font-size: 14px; font-weight: 600;
                cursor: pointer; background: transparent; color: var(--fg-1);
                border: 1px solid var(--soft); border-radius: var(--r-sm);
                padding: 9px 18px; }
button.action:hover { background: var(--beige-soft); }
button.action.primary { background: var(--lime); color: var(--lime-ink);
                        border-color: var(--lime); }
button.action.primary:hover { background: var(--lime-deep);
                              border-color: var(--lime-deep); }
button.action:disabled { color: var(--fg-3); border-color: var(--hair);
                         background: transparent; cursor: default; }

input, select, textarea { font: inherit; font-size: 14px;
  background: var(--beige-soft); color: var(--fg-1);
  border: 1px solid var(--soft); border-radius: var(--r-sm); padding: 8px 10px; }
input:focus, select:focus, textarea:focus { outline: 2px solid var(--lime);
  outline-offset: 1px; }
textarea { width: 100%; font-family: var(--mono); font-size: 12.5px;
           line-height: 1.6; }
.note { font-size: 13px; margin-left: 12px; color: var(--fg-2); }
.note.ok { color: var(--pos); } .note.bad { color: var(--neg); }

/* ── Assistent ─────────────────────────────────────────────────────── */
.steps { list-style: none; padding: 0; margin: 0; }
.steps li { padding: 0 0 40px 0; }
.steps li + li { border-top: 1px solid var(--hair); padding-top: 32px; }
.steps h3 { font-size: 17px; font-weight: 600; margin: 0 0 6px;
            letter-spacing: -0.01em; }
.steps p { margin: 6px 0 14px; font-size: 14px; color: var(--fg-2);
           max-width: 62ch; font-weight: 400; }

.banner { background: var(--beige-deep); border: 1px solid var(--hair);
          border-radius: var(--r-sm); padding: 12px 16px; margin-bottom: 32px;
          font-size: 14px; color: var(--fg-1); }

#loglines { font-family: var(--mono); font-size: 12px; line-height: 1.65;
            white-space: pre-wrap; background: var(--beige-soft);
            border: 1px solid var(--hair); border-radius: var(--r-sm);
            padding: 16px; max-height: 32rem; overflow: auto; margin: 0;
            color: var(--fg-2); }
</style>
</head>
<body>
<div class="shell">
  <header>
    <img src="data:image/png;base64,""" + ICON_PNG + """" alt="">
    <span class="eyebrow">Bridge</span>
    <span class="ver" id="ver"></span>
  </header>

  <div class="banner" id="restart" hidden>
    A setting was changed. It takes effect the next time the Bridge starts.
  </div>

  <p class="verdict" id="verdict">Connecting...</p>
  <div class="chips">
    <span class="chip"><span class="dot" id="d-tws"></span><span id="l-tws">TWS</span></span>
    <span class="chip"><span class="dot" id="d-ot"></span><span id="l-ot">Ordertune</span></span>
    <span class="chip"><span class="dot" id="d-acct"></span><span id="l-acct">Account</span></span>
    <span class="chip"><span class="dot" id="d-write"></span><span id="l-write">Order access</span></span>
  </div>

  <div class="statement" id="card" hidden>
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
        <p><button class="action primary" id="s1">Save bridge.env</button>
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
    </section>
    <section>
      <h2>Positions</h2>
      <div id="positions" class="scroll muted">No position data yet.</div>
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
        <button class="action primary" id="f-save">Save</button>
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
// Das System kennt genau einen Statuspunkt in zwei Zustaenden: Lime oder
// idle. Die Bedeutung traegt das Wort daneben — was fuer eine Betriebsflaeche
// ohnehin besser ist als Farbe allein.
function chip(dotId, labelId, live, wort) {
  q(dotId).className = "dot" + (live ? " live" : "");
  q(labelId).textContent = wort;
}
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
    box.className = "scroll muted"; box.textContent = "No order data yet."; return;
  }
  if (s.orders.length === 0) {
    box.className = "scroll"; box.textContent = "No orders of ours at IBKR right now."; return;
  }
  box.className = "scroll";
  box.innerHTML = "<table><tr><th>Symbol</th><th>Side</th><th>Qty</th><th>Status</th>"
    + "<th>Reason</th></tr>" + s.orders.map(o =>
      "<tr><td>" + esc(o.symbol) + "</td><td>" + esc(o.action) + "</td><td>"
      + esc(o.qty ?? "-") + "</td><td class='state "
      + (o.status === "Filled" ? "done" : o.status === "Rejected" ? "gone" : "")
      + "'>" + esc(o.status) + "</td><td class='reason'>"
      + esc(o.reason ?? "") + "</td></tr>").join("") + "</table>";
}

function renderPositions(s) {
  const box = q("positions");
  if (s.positions === null || s.positions === undefined) {
    // T1-99: NICHT dasselbe wie eine leere Tabelle.
    box.className = "scroll muted"; box.textContent = "No position data yet."; return;
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

  q("verdict").textContent = verdict(s)[0];

  chip("d-tws", "l-tws", s.tws_connected,
       s.tws_connected ? "TWS connected" : "TWS not reachable");
  const meldet = s.ordertune_ok && !heartbeatStale(s);
  chip("d-ot", "l-ot", meldet,
       meldet ? "Reporting to Ordertune" : "Not reporting");
  chip("d-acct", "l-acct", s.account_known,
       s.account_known ? "Account data in" : "No account data yet");
  const schreibt = s.write_access === "writable";
  chip("d-write", "l-write", schreibt,
       schreibt ? "Orders allowed"
       : s.write_access === "unknown" ? "Order access unknown"
       : "Orders would be rejected");

  q("hb").textContent = s.last_heartbeat_at
    ? age(s.last_heartbeat_at) + (heartbeatStale(s) ? " - overdue" : "")
    : "waiting for the first one";
  q("hb").style.color = heartbeatStale(s) ? "var(--neg)" : "";
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
