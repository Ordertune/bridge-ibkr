"""T1-101 — die Flaeche des Cockpits.

## Woher die Gestaltung kommt

Aus den **t1-Tokens** (`t1.ordertune.com/src/app/globals.css`), denen
`docs.ordertune.com` bereits folgt — dort stehen sie sogar namentlich als
Quelle in `styles/globals.css`. Weiss bzw. tiefes Schwarz als Flaeche,
kuehle Graustufen darueber, Inter selbst gehostet, ein einziger Akzent
(`#c8f23e`), der in allen drei Flaechen identisch ist.

## Die Entscheidung dahinter — und dass sie einmal anders war

T1-101 hat diese Seite zunaechst auf t1-Tokens gebaut, der Owner hat das
damals auf die Sprache von ordertune.com umgestellt (beiges Papier,
`#F4EFE6`). Owner-Entscheid 2026-09-14 dreht das zurueck.

Der Grund ist nicht Geschmack, sondern ein neuer Ablauf: mit der Kopplung aus
T1-178 steht der Nutzer innerhalb einer Minute abwechselnd vor dieser Seite und
vor der Broker-Karte auf t1 und tippt einen Code von der einen in die andere.
Dieses Nebeneinander gab es nicht, als die erste Entscheidung fiel. Zwei
Farbwelten in einem Vorgang sind dann kein Markenreichtum, sondern die Frage
„bin ich hier noch richtig".

`ordertune.com` behaelt sein beiges Papier. Die Trennlinie verlaeuft zwischen
**Aussenauftritt** (Marke) und **Produktflaechen** (t1, docs, Cockpit).

## Was aus dem Aufbau bleibt

Der Aufbau hat sich bewaehrt und wird nicht angefasst — nur neu eingefaerbt:

  * **Ein Akzent je Ansicht.** Genau ein Lime-Knopf, sonst nichts Lime ausser
    dem Statuspunkt und dem Reiter-Unterstrich.
  * **Ein Statuspunkt in zwei Zustaenden**, Lime (live) oder `--fg-3` (idle).
    Die Bedeutung traegt das Wort daneben, nicht die Farbe.
  * **Der Statement-Block** bleibt das laute Mittel. Er entstand als Ersatz
    fuer verbotenes Rot; er bleibt, weil er funktioniert. Neu ist, dass er im
    dunklen Modus nicht gegen die Flaeche verschwinden darf — dort traegt er
    einen Rahmen statt der Schwaerze.
  * **Keine Icons, keine Emojis, keine Unicode-Piktogramme**, Ziffern immer
    `tabular-nums`, Unterzeilen nie fett.

Neu dazu, weil t1 und docs es koennen und docs sogar dunkel startet:
**`prefers-color-scheme`**. Eine Bridge laeuft nachts auf einem Rechner, vor
dem jemand sitzt; eine weisse Flaeche um 23 Uhr ist eine Entscheidung, die wir
nicht fuer ihn treffen muessen.

Fehlertext ist ab jetzt `--danger` (`#dc2626`), wie in t1. Das Trader-Rot-Verbot
gilt fuer die Marke und fuer Kurse und Renditen — nicht fuer die Fehlerzeile
einer Betriebsflaeche, und t1 haelt es genauso.

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
  /* Kopie der t1-Tokens aus t1.ordertune.com/src/app/globals.css.
     Gegenstueck: docs.ordertune.com/styles/globals.css, das dieselben Werte
     mit denselben Quellenangaben fuehrt. Aendert sich dort etwas, gehoert es
     hierher nachgezogen — die drei Flaechen sind eine Sprache. */
  --bg: #ffffff;
  --surface: #f5f7fa; --surface-2: #eef1f5; --surface-3: #e6eaf0;
  --fg-1: #18181b; --fg-2: #52525b; --fg-3: #a1a1aa;
  --border: #d4d8df; --border-strong: #b9bec7;

  /* Der eine erlaubte Akzent. In t1, docs und hier identisch. */
  --lime: #c8f23e; --lime-deep: #b6df2b; --lime-ink: #0a0a0a;

  /* Status. t1 fuehrt dafuer EINEN Satz ohne Dunkel-Gegenstueck; das wird
     hier bewusst nicht "verbessert", sonst driften die Flaechen. */
  --success: #16a34a; --warn: #d97706; --danger: #dc2626;

  /* Der Statement-Block. Im hellen Modus die dunkle Flaeche von t1, im
     dunklen eine erhoehte mit Rahmen — schwarz auf schwarz waere kein
     Statement, sondern ein Loch. */
  --statement-bg: #0a0a0a; --statement-fg: #fafafa; --statement-fg-2: #a3a3a3;
  --statement-border: transparent;

  --r-xs: 4px; --r-sm: 6px; --r-md: 10px; --r-pill: 999px;
  --sans: Inter, system-ui, -apple-system, "Segoe UI", Roboto, sans-serif;
  --mono: ui-monospace, "SF Mono", Menlo, Consolas, monospace;
}

@media (prefers-color-scheme: dark) {
  :root {
    --bg: #0a0a0a;
    --surface: #111111; --surface-2: #171717; --surface-3: #1f1f1f;
    --fg-1: #fafafa; --fg-2: #a3a3a3; --fg-3: #6b6b6b;
    --border: #262626; --border-strong: #3a3a3a;
    --statement-bg: #171717; --statement-fg: #fafafa;
    --statement-fg-2: #a3a3a3; --statement-border: #3a3a3a;
  }
}
* { box-sizing: border-box; }
/* `[hidden]` ist nur `display: none` aus dem Vorgabestylesheet und verliert
   gegen JEDE eigene `display`-Regel. `nav { display: flex }` hat die
   Reiterleiste deshalb auch im Assistenten stehen lassen, obwohl das Skript
   sie ausdruecklich versteckt — sichtbar wurde das erst beim Abfotografieren
   der Seite. Diese Zeile gilt fuer alle, nicht nur fuer `nav`: derselbe
   Fehler wartet sonst bei jedem weiteren Element mit eigenem `display`. */
[hidden] { display: none !important; }
html { -webkit-font-smoothing: antialiased; color-scheme: light dark; }
body { margin: 0; background: var(--bg); color: var(--fg-1);
       font-family: var(--sans); font-size: 15px; line-height: 1.55;
       font-weight: 400; }
.shell { max-width: 62rem; margin: 0 auto; padding: 40px 24px 96px; }

/* ── Kopf ──────────────────────────────────────────────────────────── */
/* T1-179: das Fenster sagt jetzt, was es ist. Vorher stand neben dem Icon
   nur „Bridge" als Augenbraue — auf einem Rechner, auf dem gleichzeitig TWS,
   ein Browser und die Ordertune-Seite offen sind, ist das zu wenig, um den
   richtigen Tab wiederzufinden. */
header { display: flex; align-items: baseline; gap: 10px; margin-bottom: 44px;
         padding-bottom: 18px; border-bottom: 1px solid var(--border); }
header img { width: 24px; height: 24px; border-radius: var(--r-xs);
             display: block; align-self: center; }
header .name { font-size: 15px; font-weight: 600; letter-spacing: -0.01em;
               color: var(--fg-1); }
.eyebrow { text-transform: uppercase; letter-spacing: .12em; font-size: 12px;
           color: var(--fg-2); font-weight: 500; }
header .ver { margin-left: auto; font-size: 12px; color: var(--fg-3);
              font-variant-numeric: tabular-nums; }

/* ── Urteil ────────────────────────────────────────────────────────── */
.verdict { font-size: 30px; line-height: 1.2; letter-spacing: -0.02em;
           font-weight: 700; color: var(--fg-1); margin: 0 0 20px;
           max-width: 34ch; }

/* Der Statement-Block ist das laute Mittel dieser Flaeche. Er ersetzt den
   farbigen Randstreifen, den weder t1 noch die Marke kennen. Im dunklen Modus
   traegt er einen Rahmen, sonst waere er ein Loch statt einer Aussage. */
.statement { background: var(--statement-bg); color: var(--statement-fg);
             border: 1px solid var(--statement-border);
             border-radius: var(--r-md); padding: 28px 32px; margin: 0 0 32px; }
.statement h2 { margin: 0 0 14px; font-size: 22px; line-height: 1.25;
                letter-spacing: -0.01em; font-weight: 700; max-width: 40ch; }
.statement pre { font-family: var(--mono); font-size: 12.5px; line-height: 1.6;
                 white-space: pre-wrap; color: var(--statement-fg-2); margin: 0; }
/* Die Trennlinie sitzt IM dunklen Block, in beiden Modi — deshalb hier ein
   fester Weisswert und kein Token, das mit der Flaeche kippt. */
.statement pre + pre { margin-top: 14px; padding-top: 14px;
                       border-top: 1px solid rgba(255,255,255,0.12); }

/* ── Statuspunkte: Lime oder idle. Die Bedeutung traegt das Wort. ──── */
/* T1-223: Urteil, Pillen und der Knopf in einer Zeile. Der Abstand zwischen
   Pillen und Knopf ist die Aussage — er trennt das, was berichtet, von dem,
   was handelt. Auf schmalen Fenstern bricht der Knopf unter die Pillen, statt
   sie zu quetschen. */
.statusline { display: flex; align-items: flex-start; justify-content: space-between;
              gap: 24px; flex-wrap: wrap; margin-bottom: 44px; }
.statusline .chips { margin-bottom: 0; }
.stopbox { display: flex; align-items: center; gap: 10px; margin-left: auto; }
.chips { display: flex; gap: 8px; flex-wrap: wrap; margin-bottom: 44px; }
.chip { display: inline-flex; align-items: center; gap: 8px;
        padding: 6px 14px 6px 12px; background: var(--surface);
        border: 1px solid var(--border); border-radius: var(--r-pill);
        font-size: 13px; color: var(--fg-2); }
.dot { width: 7px; height: 7px; border-radius: 50%; background: var(--fg-3);
       flex: none; }
.dot.live { background: var(--lime-deep); }

/* ── Reiter ────────────────────────────────────────────────────────── */
nav { display: flex; gap: 4px; border-bottom: 1px solid var(--border);
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
.warn { color: var(--danger); }

/* ── Tabellen: schlichte Zellen, keine Sortierpfeile, keine Badges ──── */
.scroll { overflow-x: auto; }
table { border-collapse: collapse; width: 100%; font-size: 14px;
        font-variant-numeric: tabular-nums; }
th { text-align: left; font-weight: 500; color: var(--fg-2); font-size: 11px;
     text-transform: uppercase; letter-spacing: .1em; padding-bottom: 10px;
     border-bottom: 1px solid var(--border-strong); white-space: nowrap; }
td { padding: 11px 20px 11px 0; border-bottom: 1px solid var(--border);
     white-space: nowrap; color: var(--fg-1); }
th { padding-right: 20px; }
td.state { color: var(--fg-2); }
td.state.done { color: var(--success); }
td.state.gone { color: var(--danger); }
td.reason { white-space: normal; color: var(--danger); font-size: 13px;
            max-width: 34rem; }

/* ── Knoepfe: genau EINER in Lime je Ansicht ───────────────────────── */
button.action { font: inherit; font-size: 14px; font-weight: 600;
                cursor: pointer; background: transparent; color: var(--fg-1);
                border: 1px solid var(--border-strong);
                border-radius: var(--r-sm); padding: 9px 18px; }
button.action:hover { background: var(--surface-2); }
button.action.primary { background: var(--lime); color: var(--lime-ink);
                        border-color: var(--lime); }
button.action.primary:hover { background: var(--lime-deep);
                              border-color: var(--lime-deep); }
button.action:disabled { color: var(--fg-3); border-color: var(--border);
                         background: transparent; cursor: default; }

input, select, textarea { font: inherit; font-size: 14px;
  background: var(--surface); color: var(--fg-1);
  border: 1px solid var(--border-strong); border-radius: var(--r-sm);
  padding: 8px 10px; }
input:focus, select:focus, textarea:focus { outline: 2px solid var(--lime);
  outline-offset: 1px; }
textarea { width: 100%; font-family: var(--mono); font-size: 12.5px;
           line-height: 1.6; }
.note { font-size: 13px; margin-left: 12px; color: var(--fg-2); }
.note.ok { color: var(--success); } .note.bad { color: var(--danger); }

/* ── Assistent ─────────────────────────────────────────────────────── */
/* T1-179 — der Kopplungscode ist das, wofuer dieses Fenster beim ersten Start
   ueberhaupt aufgeht. Er bekommt deshalb eine eigene Flaeche und nicht eine
   Zeile zwischen zwei Absaetzen.

   Der Code wird ABGETIPPT, oft von einem Fenster ins andere und bei einem VPS
   sogar von einer Maschine auf die naechste — gross, weit gesperrt, in
   Ziffernbreite. Die Restzeit steht darunter und laeuft mit: eine Frist, die
   man nur als Zahl liest („10 Minuten"), sagt nach fuenf Minuten nichts mehr. */
/* Jede Regel hier ist unter `.pairbox` gehaengt, und das ist nicht Kosmetik:
   das Feld steht IN der Schrittliste, und `.steps p` weiter unten ist
   spezifischer als eine blosse Klasse. Ohne diese Schachtelung wurde die
   ganze Flaeche auf 14 px plattgedrueckt — der Code eingeschlossen, der als
   einziges Element dieser Seite gross sein MUSS. Gefunden hat das kein Test,
   sondern das erste Bildschirmfoto. */
.pairbox { border: 1px solid var(--border); border-radius: var(--r-md);
           background: var(--surface); padding: 24px; margin: 14px 0 0; }
.pairbox .pairlead { margin: 0; font-size: 13px; font-weight: 500;
            color: var(--fg-2); text-transform: uppercase; letter-spacing: .1em;
            max-width: none; }
.pairbox .code { font-family: var(--mono); font-size: 38px; font-weight: 600;
        letter-spacing: .24em; margin: 10px 0 2px; line-height: 1.1;
        font-variant-numeric: tabular-nums; color: var(--fg-1); max-width: none; }
.pairbox .pairttl { margin: 0 0 18px; font-size: 13px; color: var(--fg-3);
           font-variant-numeric: tabular-nums; }
.pairbox .pairttl.soon { color: var(--warn); }
.pairbox .pairwhere { margin: 0 0 18px; font-size: 14px; color: var(--fg-2); }
.pairbox .pairwhere a { color: var(--fg-1); text-decoration: underline;
               text-underline-offset: 3px; text-decoration-color: var(--lime-deep);
               text-decoration-thickness: 2px; }

/* Die Maschinenangaben sind kein Beiwerk: sie sind der einzige Riegel gegen
   eine erschlichene Kopplung. Deshalb abgesetzt, damit der Blick sie findet,
   und mit demselben Wortlaut wie die Flaeche auf t1. */
.pairmachine { border-top: 1px solid var(--border); padding-top: 16px;
               margin-bottom: 16px; }
.pairbox .pairmachine-lead { margin: 0 0 10px; font-size: 13px;
                    color: var(--fg-2); max-width: 52ch; }
.pairmachine dl { grid-template-columns: 6rem 1fr; gap: 6px 16px; }
.pairmachine dt { font-size: 13px; }
.pairmachine dd { font-size: 13px; }
details { margin-top: 18px; }
summary { cursor: pointer; font-size: 13px; color: var(--fg-2); }
summary:hover { color: var(--fg-1); }
/* T1-179: die Schrittnummer steht als Marke links, nicht als „1 · " im
   Titel. Eine Ziffer im Fliesstext liest sich als Teil der Ueberschrift; eine
   Marke daneben sagt „Schritt", ohne das Wort zu brauchen. */
.steps { list-style: none; padding: 0; margin: 0; counter-reset: schritt; }
.steps li { position: relative; padding: 0 0 36px 44px; counter-increment: schritt; }
.steps li::before { content: counter(schritt); position: absolute; left: 0; top: 0;
                    width: 26px; height: 26px; border-radius: 50%;
                    background: var(--surface-2); border: 1px solid var(--border);
                    color: var(--fg-2); font-size: 12px; font-weight: 600;
                    display: flex; align-items: center; justify-content: center;
                    font-variant-numeric: tabular-nums; }
.steps li + li { border-top: 1px solid var(--border); padding-top: 32px; }
.steps li + li::before { top: 32px; }
.steps h3 { font-size: 17px; font-weight: 600; margin: 0 0 6px;
            letter-spacing: -0.01em; }
.steps p { margin: 6px 0 14px; font-size: 14px; color: var(--fg-2);
           max-width: 62ch; font-weight: 400; }

.banner { background: var(--surface-2); border: 1px solid var(--border);
          border-radius: var(--r-sm); padding: 12px 16px; margin-bottom: 32px;
          font-size: 14px; color: var(--fg-1); }

#loglines { font-family: var(--mono); font-size: 12px; line-height: 1.65;
            white-space: pre-wrap; background: var(--surface);
            border: 1px solid var(--border); border-radius: var(--r-sm);
            padding: 16px; max-height: 32rem; overflow: auto; margin: 0;
            color: var(--fg-2); }
</style>
</head>
<body>
<div class="shell">
  <header>
    <img src="data:image/png;base64,""" + ICON_PNG + """" alt="">
    <span class="name">Ordertune Bridge</span>
    <span class="ver" id="ver"></span>
  </header>

  <div class="banner" id="restart" hidden>
    A setting was changed. It takes effect the next time the Bridge starts.
  </div>

  <p class="verdict" id="verdict">Connecting...</p>
  <!-- T1-223, Owner-Befund 2026-09-23 (dritte Fassung dieses Knopfes).
       Erst unter "Details" — versteckt. Dann unten auf der Startseite — immer
       noch zu suchen. Jetzt hier: auf Augenhoehe mit dem Urteil, rechts
       aussen, wo das Auge nach dem Lesen der Ueberschrift ohnehin ankommt.
       Er sitzt in derselben Zeile wie die Statuspillen, aber NICHT in ihrer
       Reihe: die Pillen berichten, der Knopf handelt, und wer das verwechselt,
       klickt aus Versehen. Deshalb eine eigene Gruppe mit Abstand, nicht die
       fuenfte Pille. -->
  <div class="statusline">
    <div class="chips">
      <span class="chip"><span class="dot" id="d-tws"></span><span id="l-tws">TWS</span></span>
      <span class="chip"><span class="dot" id="d-ot"></span><span id="l-ot">Ordertune</span></span>
      <span class="chip"><span class="dot" id="d-acct"></span><span id="l-acct">Account</span></span>
      <span class="chip"><span class="dot" id="d-write"></span><span id="l-write">Order access</span></span>
    </div>
    <div class="stopbox">
      <button class="action" id="stop">Stop the Bridge</button>
      <span id="stopmsg" class="note"></span>
    </div>
  </div>

  <div class="statement" id="card" hidden>
    <h2 id="card-title"></h2>
    <pre id="card-detail"></pre>
    <pre id="card-action"></pre>
  </div>

  <div id="setup" hidden>
    <ol class="steps">
      <li>
        <h3>Connect this machine to Ordertune</h3>
        <p class="muted">Get a code here, type it into Ordertune, done. Nothing to
        download, nothing to copy between windows.</p>
        <p><button class="action primary" id="p1">Get a pairing code</button>
           <span class="note" id="p1msg"></span></p>
        <div class="pairbox" id="paircode" hidden>
          <p class="pairlead">Enter this code in Ordertune</p>
          <p class="code">- - - - -</p>
          <p class="pairttl"><span id="pairttl">10:00</span> left</p>
          <p class="pairwhere">Open <a id="pairurl" href="#" target="_blank"
             rel="noopener">t1.ordertune.com/settings?tab=broker</a></p>
          <div class="pairmachine">
            <p class="pairmachine-lead">Ordertune asks you to confirm this
            machine. It must show exactly this:</p>
            <dl>
              <dt>Computer</dt><dd class="mono" id="pairhost">-</dd>
              <dt>Hardware</dt><dd class="mono" id="pairfp">-</dd>
            </dl>
          </div>
          <p class="note" id="pairstate">Waiting for you to confirm in Ordertune...</p>
        </div>
        <details>
          <summary>Or paste a bridge.env you downloaded</summary>
          <p class="muted">The older way, and it still works -- useful when this machine
          has no browser, or when you run the Bridge unattended.</p>
          <textarea id="envbox" rows="7" spellcheck="false"
            placeholder="ORDERTUNE_API_BASE=https://t1.ordertune.com&#10;ORDERTUNE_BRIDGE_TOKEN=...&#10;ORDERTUNE_BRIDGE_CONNECTION_ID=..."></textarea>
          <p><button class="action" id="s1">Save bridge.env</button>
             <span class="note" id="s1msg"></span></p>
        </details>
      </li>
      <li>
        <h3>Find TWS</h3>
        <p class="muted">The socket port is a setting in TWS - it does not follow from
        the account type. This checks the four IBKR defaults.</p>
        <p><button class="action" id="s2">Search for TWS</button>
           <span class="note" id="s2msg"></span></p>
        <div id="s2ports"></div>
      </li>
      <li>
        <h3>Check the port</h3>
        <p><button class="action" id="s3">Check</button>
           <span class="note" id="s3msg"></span></p>
      </li>
      <li>
        <h3>Check the credentials</h3>
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
        <dt>Account</dt><dd id="acct">-</dd>
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

function exportBroken(s) {
  // "unknown" heisst „noch nicht nachgesehen" und ist keine Stoerung.
  return s.trade_export && s.trade_export !== "ok" && s.trade_export !== "unknown";
}

// T1-214: die Bridge haengt an einem IB Gateway statt an der TWS. Kein
// Ausfall - der Handel laeuft. Es erklaert aber, WARUM die Berichte fehlen,
// und steht deshalb vor dem Export-Befund.
function gatewayInstead(s) {
  return !!s.gateway_instead_of_tws;
}

function verdict(s) {
  // T1-223 zuerst: waehrend des Beendens ist „Connected - waiting for releases"
  // eine Aussage ueber einen Zustand, der gerade endet.
  if (s.stopping) return ["Stopping - finishing the current tick", "warn"];
  if (s.failure_headline) return [s.failure_headline, "bad"];
  if (!s.tws_connected) return ["Not connected to TWS", "bad"];
  if (heartbeatStale(s))
    return ["No heartbeat for over " + HEARTBEAT_STALE_S + " s", "warn"];
  if (s.write_access === "read_only_confirmed")
    return ["TWS is running with Read-Only API. Orders will be rejected.", "bad"];
  if (s.write_access === "read_only_suspected")
    return ["TWS did not answer the open-orders request. Orders may be rejected.", "warn"];
  if (!s.ordertune_ok) return ["Not reporting to Ordertune", "warn"];
  // T1-214 vor T1-207: wer auf dem Gateway sitzt, bekommt die URSACHE genannt
  // und nicht ihre Folge. "Export nicht gefunden" schickt ihn sonst in eine
  // Einstellung, die es auf seinem Programm gar nicht gibt.
  if (gatewayInstead(s))
    return ["Running on IB Gateway - fills cannot be recovered", "warn"];
  // T1-207: zuletzt, damit es nie eine schwerere Stoerung verdeckt. Es ist
  // kein Ausfall - es heisst, dass eine Fuellung waehrend einer Auszeit der
  // Bridge nicht mehr nachgetragen werden kann.
  if (exportBroken(s))
    return ["TWS trade reports are not being read - fills may be lost", "warn"];
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
  const exportKaputt = exportBroken(s);
  const gateway = gatewayInstead(s);
  if (!s.failure_headline && !readOnly && !exportKaputt && !gateway) {
    card.hidden = true; return;
  }
  card.hidden = false;
  if (s.failure_headline) {
    q("card-title").textContent = s.failure_headline;
    q("card-detail").textContent = (s.failure_detail || []).join("\\n");
    q("card-action").textContent = (s.failure_action || []).join("\\n");
  } else if (readOnly) {
    q("card-title").textContent = "Read-Only API is switched on in TWS";
    q("card-detail").textContent = s.write_access_detail || "";
    q("card-action").textContent =
      "Everything else looks healthy - positions arrive, heartbeats go out - but\\n"
      + "every order will be rejected.\\n\\n"
      + "In TWS: File -> Global Configuration -> API -> Settings.\\n"
      + "Turn OFF 'Read-Only API', then restart TWS.\\n"
      + "TWS may also be showing a dialog box that nobody sees on a VPS.";
  } else if (gateway) {
    // T1-214. Vor dem Export-Befund, weil es dessen Ursache ist.
    q("card-title").textContent =
      "You are running IB Gateway. Ordertune Bridge needs TWS.";
    q("card-detail").textContent =
      "The Bridge reads the trade reports that TWS writes to disk. That file is\\n"
      + "what lets a fill be recovered when the Bridge was off at the moment it\\n"
      + "happened - the reason you no longer have to keep the Bridge open until\\n"
      + "the closing bell.\\n\\n"
      + "IB Gateway has no export function: its configuration tree ends before\\n"
      + "'Export Reports'. Everything else works, this one thing cannot.";
    q("card-action").textContent =
      "Install Trader Workstation, log in with the same account, and set\\n"
      + "Global Configuration -> Export Reports (leave 'Export filename' empty).\\n\\n"
      + "Until you do, the Bridge keeps trading - you are missing the recovery,\\n"
      + "not the execution.";
  } else if (s.trade_export === "no_file") {
    // T1-206 — der leere Ordner ist NICHT dasselbe wie ein abgeschalteter
    // Export, und diese Flaeche hat ihn genauso genannt.
    //
    // Owner-Befund 2026-09-24, erster Lauf auf einer frischen Maschine:
    // Schalter an, Intervall 1, Dateiname leer — und hier stand
    // "TWS is not writing trade reports" samt der Aufforderung,
    // einzuschalten, was eingeschaltet war.
    //
    // Direkt nach der Einrichtung ist das der erwartbare Zustand: die TWS
    // exportiert Handelsberichte, und ohne Handel gibt es nichts zu
    // exportieren. Deshalb eine Ueberschrift, die eine Beobachtung ist statt
    // einer Anschuldigung.
    q("card-title").textContent = "No trade report yet";
    q("card-detail").textContent = s.trade_export_detail || "";
    q("card-action").textContent =
      "Nothing to do if you have just set this up. TWS writes the first file\\n"
      + "once there is a trade to report, and the Bridge picks it up from\\n"
      + "there.\\n\\n"
      + "Come back to this after your first fill. If the folder is still empty\\n"
      + "then, TWS is writing somewhere else - compare the path above with\\n"
      + "Global Configuration -> Export Reports, character by character.";
  } else {
    // T1-207. Der Text kommt aus der Bridge, nicht von hier: er benennt, WELCHE
    // Bedingung fehlt, und diese Flaeche soll ihn nicht zu "something is wrong"
    // eindampfen.
    q("card-title").textContent = "TWS is not writing trade reports";
    q("card-detail").textContent = s.trade_export_detail || "";
    q("card-action").textContent =
      "Trading still works. What does not work is recovery: if an order fills\\n"
      + "while the Bridge is off, nobody can tell Ordertune about it afterwards.\\n\\n"
      + "In TWS: File -> Global Configuration -> Export Reports.\\n"
      + "Switch on 'Export trade reports periodically', set an interval of 1\\n"
      + "minute, pick a folder - and leave 'Export filename' EMPTY, so TWS\\n"
      + "writes one dated file per trading day instead of overwriting one.";
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
  q("hb").style.color = heartbeatStale(s) ? "var(--danger)" : "";
  q("poll").textContent = age(s.last_pending_poll_at);
  q("since").textContent = age(s.session_connected_at);
  q("acct").textContent = s.account_masked || "-";
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

// T1-223 — der Knopf fragt zurueck (AC-A2) und schickt dann einen Wunsch.
//
// Was danach geschieht, entscheidet der Kern: er fuehrt seinen laufenden
// Durchgang zu Ende und raeumt im `finally` auf. Diese Flaeche wartet nicht
// darauf und behauptet nichts ueber den Ausgang — sie sagt, dass sie gefragt
// hat.
q("stop").onclick = () => {
  if (!confirm("Stop the Bridge?\\n\\nOrders already at the broker stay there. "
      + "Ordertune will not be able to send new ones until you start it again."))
    return;
  q("stop").disabled = true;
  post("/stop", {}).then(res => note("stopmsg", res)).catch(() => {
    // Der Vorgang kann waehrend der Antwort schon beendet sein — dann bricht
    // die Verbindung ab, und genau das war der Zweck. Kein Fehler.
    note("stopmsg", {ok: true, message: "Stopping the Bridge."});
  });
};

function loadConfig() {
  fetch(withToken("/config")).then(r => r.json()).then(c => {
    baseline = c.fingerprint || "";
    const v = c.values || {};
    const sel = q("f-portsel");
    sel.innerHTML = "<option value=''>custom</option>" + (c.ports || []).map(p =>
      "<option value='" + p.port + "'>" + p.port + " - " + esc(p.label) + "</option>").join("");
    q("f-port").value = v.IBKR_TWS_PORT || v.IBKR_GATEWAY_PORT || "7497";
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
    IBKR_TWS_PORT: q("f-port").value,
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

/* T1-178 — die Kopplung.
   Ein Code holen, anzeigen, und dann fragen, ob der Nutzer bestaetigt hat.
   Das Geheimnis liegt ausschliesslich im Vorgang der Bridge; diese Seite
   bekommt es nie zu sehen und braucht es auch nicht. */
let pairTimer = null;
let pairLeft = 0;

q("p1").addEventListener("click", () => {
  note("p1msg", {ok: true, message: "Asking Ordertune..."});
  post("/pair/start", {}).then(r => {
    if (!r.ok) { note("p1msg", r); return; }
    note("p1msg", {ok: true, message: ""});
    q("paircode").hidden = false;
    q("paircode").querySelector(".code").textContent = r.code || "";
    q("pairhost").textContent = r.hostname || "-";
    q("pairfp").textContent = r.fingerprint_prefix || "-";
    const ziel = (r.api_base || "https://t1.ordertune.com")
      + "/settings?tab=broker";
    const link = q("pairurl");
    link.href = ziel;
    link.textContent = ziel.split("://").pop();
    pairLeft = Math.max(0, r.expires_in || 600);
    startTtl();
    startPairPolling();
  });
});

/* Die Restzeit laeuft mit. Eine Frist, die nur als Zahl dasteht, sagt nach
   fuenf Minuten nichts mehr — und wer abtippt, sieht nicht auf die Uhr. */
let ttlTimer = null;
function startTtl() {
  if (ttlTimer !== null) clearInterval(ttlTimer);
  const zeichne = () => {
    const m = Math.floor(pairLeft / 60);
    const sek = pairLeft % 60;
    q("pairttl").textContent = m + ":" + String(sek).padStart(2, "0");
    q("pairttl").parentElement.classList.toggle("soon", pairLeft <= 120);
    if (pairLeft <= 0) {
      clearInterval(ttlTimer); ttlTimer = null;
      q("pairttl").textContent = "0:00";
      q("pairstate").textContent = "This code has expired. Get a new one.";
      q("pairstate").className = "note bad";
      if (pairTimer !== null) { clearInterval(pairTimer); pairTimer = null; }
      return;
    }
    pairLeft -= 1;
  };
  zeichne();
  ttlTimer = setInterval(zeichne, 1000);
}

function startPairPolling() {
  if (pairTimer !== null) clearInterval(pairTimer);
  /* Alle drei Sekunden. Bei zehn Minuten Frist sind das gut zweihundert
     Abrufe — der Deckel auf der Plattform liegt darueber. */
  pairTimer = setInterval(pollPairing, 3000);
  pollPairing();
}

function pollPairing() {
  post("/pair/poll", {}).then(r => {
    if (r.status === "ready") {
      clearInterval(pairTimer); pairTimer = null;
      if (ttlTimer !== null) { clearInterval(ttlTimer); ttlTimer = null; }
      q("pairttl").parentElement.hidden = true;
      q("pairstate").textContent =
        "Paired. bridge.env written - the Bridge starts on its own.";
      q("pairstate").className = "note ok";
      return;
    }
    if (r.status === "pending") {
      q("pairstate").textContent = "Waiting for you to confirm in Ordertune...";
      q("pairstate").className = "note";
      return;
    }
    /* `unknown` heisst: abgelaufen, verbraucht oder von jemand anderem
       geholt. In allen drei Faellen hilft nur ein neuer Code. */
    clearInterval(pairTimer); pairTimer = null;
    q("pairstate").textContent = r.message
      || "That code is no longer valid. Get a new one.";
    q("pairstate").className = "note bad";
  });
}

q("s1").addEventListener("click", () => {
  post("/credentials", {content: q("envbox").value}).then(r => note("s1msg", r));
});
q("s2").addEventListener("click", () => {
  post("/probe", {}).then(r => {
    const gefunden = r.answering || [];
    note("s2msg", {ok: gefunden.length > 0, message: gefunden.length
      ? "Found " + gefunden.length + " answering port(s)."
      : "Nothing answers. Start TWS and log in."});
    q("s2ports").innerHTML = gefunden.map(a =>
      "<p>" + a.port + " - " + esc(a.label)
      + " <button class='action' onclick=\\"takePort(" + a.port + ")\\">Use this</button></p>"
    ).join("");
  });
});
function takePort(port) {
  post("/settings", {baseline: "", changes: {IBKR_TWS_PORT: String(port)}})
    .then(r => note("s2msg", r));
}
q("s3").addEventListener("click", () => {
  fetch(withToken("/config")).then(r => r.json()).then(c =>
    post("/probe", {port: (c.values || {}).IBKR_TWS_PORT || (c.values || {}).IBKR_GATEWAY_PORT || 7497})
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
