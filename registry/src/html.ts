// SPDX-License-Identifier: AGPL-3.0-or-later
import { bloomSvg } from "./bloom";
import { brandFrom, type Brand } from "./brand";
import type { PublicReceipt } from "./receipts";

/* The registry's pages, following the shiftbloom studio brand book v2: warm paper, ink, and red only
 * where something is to be done or read as a mark. The one gradient is inside the bloom.
 * Voices: Clash Display (headlines), General Sans (text), JetBrains Mono (labels, ids, fingerprints). */

export const esc = (s: unknown) =>
  String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]!);

/** "27 November 2026, 22:48 UTC", or the raw text when it is no date. */
export function moment(when: string): string {
  const date = new Date(when);
  if (Number.isNaN(date.getTime())) return esc(when);
  const day = date.toLocaleDateString("en-GB", { day: "numeric", month: "long", year: "numeric", timeZone: "UTC" });
  return `<time datetime="${date.toISOString()}">${day}, ${date.toISOString().slice(11, 16)} UTC</time>`;
}

/** "4.2 s" or "3 min 12 s". */
export function length(seconds: number): string {
  if (seconds < 60) return `${Number(seconds.toFixed(1))} s`;
  const whole = Math.round(seconds);
  return `${Math.floor(whole / 60)} min ${whole % 60} s`;
}

const css = `
:root{--bloom:#FF2E52;--root:#C81040;--petal:#FF8FAB;--blush:#FFE9EF;--ink:#1A1216;--ink60:rgba(26,18,22,.66);--line:#E4DADB;--paper:#F6F1EE;--panel:#EEE6E2;--surface:#FBF8F6;
--display:"Clash Display",ui-sans-serif,system-ui,sans-serif;--sans:"General Sans",ui-sans-serif,system-ui,-apple-system,"Segoe UI",sans-serif;--mono:"JetBrains Mono",ui-monospace,SFMono-Regular,Menlo,monospace;
--ease:cubic-bezier(.22,1.1,.36,1);--settle:cubic-bezier(.4,0,.2,1)}
*{box-sizing:border-box}[hidden]{display:none!important}html{-webkit-text-size-adjust:100%}
body{margin:0;background:var(--paper);color:var(--ink);font:16px/1.65 var(--sans);-webkit-font-smoothing:antialiased}
::selection{background:var(--blush)}
a{color:var(--root);text-decoration:none;background:linear-gradient(var(--root),var(--root)) 0 100%/0 1px no-repeat;transition:background-size .24s var(--ease)}
a:hover{background-size:100% 1px}
.wrap{max-width:1040px;margin:0 auto;padding:0 clamp(20px,5vw,48px)}
.label{font:500 11px/1.4 var(--mono);letter-spacing:.16em;text-transform:uppercase;color:var(--ink60)}
.label.red{color:var(--root)}
.top{display:flex;align-items:center;justify-content:space-between;gap:16px;padding:22px 0;border-bottom:1px solid var(--line)}
.brand{display:flex;align-items:center;gap:12px;color:var(--ink);background:none}
.brand .word{font:600 20px/1 var(--display);letter-spacing:-.02em}@media(min-width:640px){.brand .word{font-size:22.4px}}
.brand .word i{font-style:normal;color:var(--bloom)}
h1,h2{font-family:var(--display);font-weight:600;letter-spacing:-.025em;line-height:1.06;margin:0}
h1{font-size:clamp(32px,4.6vw,52px)}h1 em{font-style:normal;color:var(--bloom)}
h2{font-size:22px;line-height:1.15}
main{padding:clamp(28px,5vw,56px) 0 0}
.btn{appearance:none;border:0;border-radius:999px;background:var(--root);color:#fff;font:600 15px/1 var(--sans);padding:13px 20px;cursor:pointer;transition:background .24s var(--settle),transform .24s var(--ease);display:inline-flex;align-items:center;gap:8px;text-decoration:none;white-space:nowrap}
.btn:hover{background:var(--ink);background-size:auto}.btn:active{transform:scale(.97)}
.btn.ghost{background:transparent;color:var(--ink);box-shadow:inset 0 0 0 1px var(--ink)}
.btn.ghost:hover{background:var(--ink);color:#fff}
.btn.sm{padding:9px 14px;font-size:13px}
.btn:focus-visible,a:focus-visible,button:focus-visible{outline:2px solid var(--root);outline-offset:2px}
.sb{font:600 15px/1 var(--display);letter-spacing:-.02em;color:var(--ink);background:none;white-space:nowrap}.sb span{font-weight:400;color:var(--ink60);margin-left:.28em}.sb i{font-style:normal;color:var(--bloom)}
input{font:15px/1.5 var(--sans);color:var(--ink);background:var(--surface);border:1px solid var(--line);border-radius:12px;padding:11px 14px;width:100%;transition:border-color .24s var(--settle),box-shadow .24s var(--settle)}
input:focus{outline:0;border-color:var(--bloom);box-shadow:0 0 0 3px var(--blush)}
.foot{display:flex;justify-content:space-between;gap:12px 24px;flex-wrap:wrap;padding:22px 0 30px;margin-top:72px;border-top:1px solid var(--line)}.foot p{margin:0;font-size:14px;color:var(--ink60)}
.drop{background:var(--surface);border:1.5px dashed #cbbcc0;border-radius:20px;padding:clamp(28px,6vw,56px) 24px;text-align:center;transition:border-color .24s var(--settle),background .24s var(--settle)}
.drop.over{border-color:var(--bloom);background:var(--blush)}
.drop .big{font:600 22px/1.2 var(--display);letter-spacing:-.02em;margin:0 0 6px;color:var(--ink)}
.drop p{margin:0 0 18px;color:var(--ink60)}
.result{margin-top:20px;background:var(--panel);border-radius:20px;padding:24px 26px;animation:unfold .6s var(--ease) both}
.result.yes{background:var(--blush)}
.result h2{margin:8px 0}
.result p{margin:0 0 10px;max-width:46em}
.result .row{display:flex;gap:10px;flex-wrap:wrap;margin-top:16px}
.result .fp{font:12px/1.5 var(--mono);color:var(--ink60);overflow-wrap:anywhere;margin:16px 0 0}
@keyframes unfold{from{opacity:0;transform:scale(.97)}to{opacity:1;transform:none}}
@media (prefers-reduced-motion:reduce){*,*:before,*:after{animation:none!important;transition:none!important}}
`;

export type Ui = { legal: boolean; brand: Brand; origin?: string };
let UI: Ui = { legal: false, brand: brandFrom() };
/** Set once per request from the Worker's config. */
export function configureUi(c: Ui) { UI = c; }
export const ui = () => UI;

export const head = (title: string, o: { css?: string; index?: boolean; lang?: string; description?: string } = {}) => `<!doctype html><html lang="${o.lang || "en"}"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>${esc(title)}</title>${o.index ? "" : `<meta name="robots" content="noindex, nofollow">`}${o.description ? `<meta name="description" content="${esc(o.description)}">` : ""}<meta name="theme-color" content="#F6F1EE"><meta name="referrer" content="no-referrer">
<link rel="icon" href="/favicon.svg" type="image/svg+xml"><link rel="stylesheet" href="/assets/fonts.css">${o.index && UI.origin && o.description ? `<link rel="canonical" href="${esc(UI.origin)}/">` : ""}<style>${css}${o.css || ""}</style></head>`;

function operatorMark() {
  const o = UI.brand.operator;
  if (!o) return "";
  const inner = UI.brand.studioWordmark ? `shiftbloom<span>studio</span><i>.</i>` : esc(o.name);
  return o.url ? `<a class="sb" href="${esc(o.url)}" aria-label="${esc(o.name)}">${inner}</a>` : `<span class="sb">${inner}</span>`;
}

export const topbar = (right = "") =>
  `<header class="top"><a class="brand" href="/" aria-label="${esc(UI.brand.site)}, check a file">${bloomSvg({ size: 30, id: "tb" })}<span class="word">${esc(UI.brand.site)}<i>.</i></span></a>${right}</header>`;

/** AGPL section 13: people using the registry over the network are offered its source. */
export const footer = (lang: "en" | "de" = "en") => {
  const de = lang === "de";
  const legal = UI.legal ? (de ? ` · <a href="/datenschutz">Datenschutz</a> · <a href="/impressum">Impressum</a>` : ` · <a href="/privacy">Privacy</a> · <a href="/imprint">Imprint</a>`) : "";
  const o = UI.brand.operator;
  const site = esc(UI.brand.site);
  return `<footer class="foot"><p>${de ? `${site} gehört zu OmniSuite und ist Open Source unter AGPL-3.0-or-later.` : `${site} is part of OmniSuite, open source under AGPL-3.0-or-later.`} <a href="${esc(UI.brand.sourceUrl)}">${de ? "Zum Code" : "Read the code"}</a>${legal}</p>${o ? `<p>${operatorMark()}${o.place ? ` · ${esc(o.place)}` : ""}</p>` : ""}</footer>`;
};

const page = (title: string, body: string, o: Parameters<typeof head>[1] = {}) =>
  `${head(title, o)}<body><div class="wrap">${body}${footer()}</div><script src="/assets/app.js" defer></script></body></html>`;

/** Where a file is dropped. `receipt` is set on a receipt's own page, so the script can say whether the file belongs to it. */
const dropZone = (o: { big: string; receipt?: string }) => `<section id="check"${o.receipt ? ` data-receipt="${esc(o.receipt)}"` : ""}>
<div class="drop" id="drop"><p class="big">${o.big}</p><p>Your browser reads the file. Only its fingerprint is sent.</p>
<input type="file" id="file" accept=".wav,audio/wav,audio/x-wav,audio/*" hidden><button class="btn" type="button" id="pick">Choose a file</button></div>
<div id="result" role="status" aria-live="polite"></div>
<noscript><p style="margin-top:14px;color:var(--ink60)">Checking a file needs JavaScript, because the fingerprint is worked out in your browser.</p></noscript>
</section>`;

// ---------- start page ----------
const HOME_CSS = `
.lead{max-width:41em;margin-bottom:32px}
.lead p{color:var(--ink60);margin:16px 0 0;font-size:17px}
.about{display:grid;grid-template-columns:repeat(auto-fit,minmax(280px,1fr));gap:28px 48px;margin-top:64px}
.about h2{margin-bottom:10px}.about p{margin:0;color:var(--ink60)}
.find{margin-top:56px;display:flex;gap:10px;flex-wrap:wrap;align-items:flex-end;max-width:41em}
.find label{flex:1 1 320px;display:grid;gap:6px;font:500 14px/1.3 var(--sans)}
.find input{font:14px/1.5 var(--mono)}
`;

export function homePage() {
  const body = `${topbar()}
<main>
<div class="lead"><span class="label red">public receipts</span><h1 style="margin-top:10px">Does this file have a receipt<em>?</em></h1>
<p>OmniSuite marks every file it makes as AI-generated, and it can list a receipt for the file here. Drop a recording to see whether it is listed. Your browser works out the file's fingerprint and sends only that, so the audio stays on your device.</p></div>
${dropZone({ big: "Drop a WAV file here" })}
<form class="find" method="get" action="/r"><label>Have a receipt id? <input name="id" required maxlength="36" pattern="[0-9a-fA-F\\-]{36}" autocomplete="off" spellcheck="false" placeholder="748e6a9a-9e9c-433b-8677-8e60f4465499"></label><button class="btn ghost" type="submit">Open receipt</button></form>
<div class="about">
<section><h2>What a receipt holds</h2><p>The file's fingerprint (a SHA-256 over its bytes), its length, the model that made it and the watermark tag inside the audio. No audio and no text. A receipt only gets on this list while a mandate stands: a person signed with a passkey that one OmniSuite install may list receipts for one voice, and they can stop that at any time.</p></section>
<section><h2>What it can't tell you</h2><p>Whose voice is in the recording. The list shows that an install with a standing mandate registered this exact file, and when. It doesn't check the other details an install reports. A file without a receipt isn't suspicious for that reason alone, because most recordings were never listed.</p></section>
</div>
</main>`;
  return page(UI.brand.siteTitle, body, { index: true, description: UI.brand.description, css: HOME_CSS });
}

// ---------- one receipt ----------
const RECEIPT_CSS = `
.rc{max-width:50em}
.rc .id{font:500 14px/1.5 var(--mono);overflow-wrap:anywhere;color:var(--ink60);margin:12px 0 0}
.state{display:flex;gap:12px;align-items:flex-start;background:var(--panel);border-radius:16px;padding:16px 20px;margin:28px 0 0}
.state:before{content:"";flex:none;width:9px;height:9px;border-radius:50%;margin-top:.45em;background:var(--bloom)}
.state.off:before{background:transparent;box-shadow:inset 0 0 0 1.5px var(--ink60)}
.state p{margin:2px 0 0}
dl.facts{display:grid;grid-template-columns:minmax(120px,180px) 1fr;margin:28px 0 0;border-top:1px solid var(--line)}
dl.facts dt,dl.facts dd{margin:0;padding:12px 0;border-bottom:1px solid var(--line)}
dl.facts dt{font:500 11px/2.2 var(--mono);letter-spacing:.16em;text-transform:uppercase;color:var(--ink60)}
dl.facts dd{overflow-wrap:anywhere}
dl.facts .mono{font:13px/1.6 var(--mono)}
dl.facts small{display:block;color:var(--ink60);font-size:13px}
@media(max-width:560px){dl.facts{grid-template-columns:1fr}dl.facts dt{border-bottom:0;padding-bottom:0}dl.facts dd{padding-top:2px}}
.note{color:var(--ink60);font-size:14px;margin:14px 0 40px}
.rc h2{margin:0 0 14px}
`;

const STATE_LABEL: Record<PublicReceipt["mandate"]["status"], string> = {
  active: "mandate stands",
  revoked: "mandate stopped",
  expired: "mandate ran out",
  unknown: "mandate not known",
  unavailable: "mandate not checked",
};

export function receiptPage(r: PublicReceipt) {
  const enrolled = r.enrolment === "read-aloud" ? "The install says this voice was enrolled by reading a sentence aloud." : "The install doesn't say how this voice was enrolled.";
  const facts: [string, string][] = [
    ["Listed", `${moment(r.listed_at)}<small>Set by this registry.</small>`],
    ["Made", moment(r.created)],
    ["Length", `${esc(length(r.audio.seconds))} at ${esc(r.audio.sample_rate)} Hz`],
    ["Model", esc(r.model)],
    ["Fingerprint", `<span class="mono">${esc(r.audio.sha256)}</span><small>SHA-256 over the file's bytes.</small>`],
    ["Watermark", `<span class="mono">${esc(r.watermark.scheme)}</span>, tag <span class="mono">${esc(r.watermark.tag)}</span>`],
    ["Signed by", `${esc(r.signer.name)}<small>Certificate serial <span class="mono">${esc(r.signer.serial)}</span></small>`],
    ["Voice", `<span class="mono">${esc(r.voice)}</span><small>SHA-256 of the voice's reference clip. ${enrolled}</small>`],
  ];
  const body = `${topbar(`<a class="btn ghost sm" href="/">Check a file</a>`)}
<main class="rc"><span class="label red">receipt</span><h1 style="margin-top:10px">Listed on ${esc(new Date(r.listed_at).toLocaleDateString("en-GB", { day: "numeric", month: "long", year: "numeric", timeZone: "UTC" }))}<em>.</em></h1>
<p class="id">${esc(r.id)}</p>
<div class="state${r.mandate.status === "active" ? "" : " off"}"><div><span class="label">${STATE_LABEL[r.mandate.status]}</span><p>${esc(r.mandate.summary)}</p></div></div>
<dl class="facts">${facts.map(([k, v]) => `<dt>${k}</dt><dd>${v}</dd>`).join("")}</dl>
<p class="note">Everything except "Listed" is what the install reported. The registry checked the mandate, not these details, and it can't tell whose voice is in the recording. <a href="/api/receipts/${esc(r.id)}">This receipt as JSON</a></p>
<h2>Have the file?</h2>
${dropZone({ big: "Drop it here to compare it with this receipt", receipt: r.id })}
</main>`;
  return page(`Receipt ${r.id.slice(0, 8)} · ${UI.brand.site}.`, body, { css: RECEIPT_CSS });
}

// ---------- short pages ----------
const NF_CSS = `.nf{min-height:56vh;display:grid;place-items:center;text-align:center}.nf>div{max-width:34em}.nf p{color:var(--ink60);margin:14px 0 28px;font-size:17px}`;

export function messagePage(o: { title: string; label: string; h1: string; text: string }) {
  const body = `${topbar()}
<main class="nf"><div><span class="label">${esc(o.label)}</span><h1 style="margin-top:12px">${o.h1}</h1><p>${o.text}</p><a class="btn" href="/">Check a file</a></div></main>`;
  return page(`${o.title} · ${UI.brand.site}.`, body, { css: NF_CSS });
}

export const notFoundPage = () => messagePage({ title: "Not found", label: "404", h1: "Nothing here<em>.</em>", text: "The link may be incomplete." });

export const noReceiptPage = () =>
  messagePage({
    title: "No receipt",
    label: "no receipt",
    h1: "No receipt with this id<em>.</em>",
    text: "It was never listed here, or the id is mistyped. A file can also name a receipt on another registry.",
  });

export const slowDownPage = () => messagePage({ title: "Slow down", label: "429", h1: "Too many lookups<em>.</em>", text: "Wait a minute, then try again." });

export const brokenPage = () => messagePage({ title: "Something broke", label: "500", h1: "Something broke<em>.</em>", text: "That's on us. Try again in a moment." });
