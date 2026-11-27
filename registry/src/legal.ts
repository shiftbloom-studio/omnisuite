// SPDX-License-Identifier: AGPL-3.0-or-later
/** Imprint and privacy policy in English and German. Operator details come from the LEGAL var; nothing personal is hardcoded. */
import { esc, footer, head, topbar, ui } from "./html";

export type LegalInfo = { name: string; business?: string; street: string; city: string; country: { en: string; de: string }; email: string; phone?: string; vatId?: string; authority: string };
export type LegalKind = "privacy" | "datenschutz" | "imprint" | "impressum";
export const LEGAL_PATHS: Record<string, LegalKind> = { "/privacy": "privacy", "/datenschutz": "datenschutz", "/imprint": "imprint", "/impressum": "impressum" };
const UPDATED = { en: "Last updated 27 November 2026", de: "Stand: 27. November 2026" };

/** LEGAL is a JSON string var; anything incomplete hides the legal pages instead of rendering half an imprint. */
export function parseLegal(raw: string | undefined): LegalInfo | null {
  if (!raw) return null;
  try {
    const l = JSON.parse(raw) as LegalInfo;
    if (!l.name || !l.street || !l.city || !l.email || !l.authority || !l.country?.en || !l.country?.de) return null;
    return l;
  } catch {
    return null;
  }
}

const CSS = `.legal{max-width:44em}
.legal h1{font-size:clamp(32px,4.6vw,48px)}
.legal h2{font-size:22px;margin:36px 0 10px}
.legal p,.legal address{margin:0 0 14px;font-style:normal}
.legal .meta{display:flex;gap:16px;flex-wrap:wrap;margin:14px 0 28px;font-size:14px;color:var(--ink60)}`;

export function legalPage(kind: LegalKind, l: LegalInfo) {
  const de = kind === "datenschutz" || kind === "impressum";
  const lang = de ? "de" : "en";
  const isPrivacy = kind === "privacy" || kind === "datenschutz";
  const site = esc(ui().brand.site);
  const title = { privacy: "Privacy policy", datenschutz: "Datenschutzerklärung", imprint: "Imprint", impressum: "Impressum" }[kind];
  const other = { privacy: "/datenschutz", datenschutz: "/privacy", imprint: "/impressum", impressum: "/imprint" }[kind];
  const mail = `<a href="mailto:${esc(l.email)}">${esc(l.email)}</a>`;
  const address = `<address>${esc(l.name)}<br>${l.business ? `${esc(l.business)}<br>` : ""}${esc(l.street)}<br>${esc(l.city)}<br>${esc(l.country[lang])}</address>`;
  const body = isPrivacy ? (de ? privacyDe(site, address, mail, l) : privacyEn(site, address, mail, l)) : imprint(site, de, address, mail, l);
  return `${head(`${title} · ${ui().brand.site}.`, { css: CSS, lang, index: true })}<body><div class="wrap">${topbar()}
<main class="legal"><span class="label">${de ? `${site}. Rechtliches` : `${site}. legal`}</span><h1 style="margin-top:12px">${title}</h1>
<div class="meta">${isPrivacy ? `<span>${UPDATED[lang]}</span>` : ""}<a href="${other}" hreflang="${de ? "en" : "de"}">${de ? "English" : "Deutsch"}</a></div>
${body}
</main>
${footer(lang)}
</div></body></html>`;
}

function imprint(site: string, de: boolean, address: string, mail: string, l: LegalInfo) {
  const phone = l.phone ? `<br>${de ? "Telefon" : "Phone"}: <a href="tel:${esc(l.phone.replace(/[^\d+]/g, ""))}">${esc(l.phone)}</a>` : "";
  const vat = l.vatId ? `<p>${de ? "Umsatzsteuer-Identifikationsnummer gemäß § 27a UStG" : "VAT ID pursuant to § 27a UStG"}: ${esc(l.vatId)}</p>` : "";
  return de
    ? `<p>Angaben gemäß § 5 DDG:</p>${address}<p>E-Mail: ${mail}${phone}</p>${vat}
<h2>Verbraucherstreitbeilegung</h2><p>Wir sind nicht bereit oder verpflichtet, an Streitbeilegungsverfahren vor einer Verbraucherschlichtungsstelle teilzunehmen.</p>
<h2>Einträge</h2><p>Die Belege auf ${site} stammen von den OmniSuite-Installationen, die sie gemeldet haben, nicht von uns. Wenn ein Eintrag gegen das Recht verstößt oder dich betrifft, schick uns seinen Link an ${mail}. Wir prüfen jeden Hinweis und entfernen rechtswidrige Einträge umgehend.</p>`
    : `<p>Information pursuant to § 5 DDG:</p>${address}<p>Email: ${mail}${phone}</p>${vat}
<h2>Consumer dispute resolution</h2><p>We are not willing or obliged to take part in dispute resolution proceedings before a consumer arbitration board.</p>
<h2>Listings</h2><p>The receipts on ${site} come from the OmniSuite installs that listed them, not from us. If a listing breaks the law or concerns you, send its link to ${mail}. We look into every report and remove unlawful listings without delay.</p>`;
}

function privacyEn(site: string, address: string, mail: string, l: LegalInfo) {
  return `<p>${site} has no user accounts and sets no cookies. There is no tracking or advertising, no analysis of visitors or their behavior, and no automated decision-making about you. This policy covers the personal data that is processed nonetheless when you open ${site}, above all your IP address, and what is kept about a listed receipt.</p>
<h2>Controller</h2>${address}<p>Email: ${mail}</p>
<h2>Hosting</h2>
<p>Cloudflare, Inc., 101 Townsend St., San Francisco, CA 94107, USA, runs ${site} on our behalf: the pages, the list of receipts and the program behind them (a Cloudflare Worker). To do so, Cloudflare processes your IP address, the address of the page you request, the time, and details your browser sends, such as its user agent. You don't have to provide this data, but without it nothing can be shown to you.</p>
<p>Requests that our Worker handles are also logged, including the IP address, the approximate location Cloudflare derives from it, and the address requested. We use these logs only to fix errors and to prevent abuse, and they are deleted after at most 7 days.</p>
<p>To prevent abuse, the Worker counts lookups and new listings per IP address over one minute and refuses requests above a limit. The count is held only in the memory of Cloudflare's rate limiter and is not stored with any receipt.</p>
<p>Fonts are fetched by our Worker and delivered from ${site} itself, so your browser doesn't contact Fontshare or jsDelivr.</p>
<p>The legal basis is our legitimate interest in running ${site} securely and reliably (Art. 6(1)(f) GDPR). Cloudflare processes the data as our processor under a data processing agreement (Art. 28 GDPR). Cloudflare, Inc. is certified under the EU-U.S. Data Privacy Framework, for which the European Commission has adopted an adequacy decision (Art. 45 GDPR); the agreement also contains the EU standard contractual clauses. More in <a href="https://www.cloudflare.com/privacypolicy/">Cloudflare's privacy policy</a>.</p>
<h2>Checking a file</h2>
<p>When you drop a file on a page, your browser reads it on your device and works out its SHA-256 fingerprint. The page then sends that fingerprint and, if the file names one, its receipt id to ${site} to look them up. The file itself, its audio and its name are not sent. Apart from the request log described above, lookups are not stored.</p>
<h2>Receipts</h2>
<p>An OmniSuite install can list a receipt for a file it made. For each receipt we store in Cloudflare D1: the receipt id, the file's SHA-256 fingerprint, its length and sample rate, the model, the watermark scheme and tag, the name and serial number of the install's signing certificate (a random name such as "OmniSuite install 1a2b3c4d"), the time the install gives for the file, the time of listing, the SHA-256 fingerprint of the voice's reference clip, how the install says the voice was enrolled, and the id of the mandate that allowed the listing. Everything except the mandate id is public: anyone who has the receipt id or the file can look the receipt up. We don't store audio, the spoken text, a name, an account or the IP address of the install with a receipt.</p>
<p>A listing needs a mandate, which a person signed with a passkey at the sign-in service this registry is connected to. To show whether a mandate still stands, ${site} asks that service for the mandate's state and three dates (signed, expiry, stop). It learns nothing else about the person.</p>
<p>A receipt stays listed until we remove it. If a receipt concerns you and you want it removed, for example because it was listed for your voice without your consent, email us. The legal basis for keeping and showing receipts is our legitimate interest in letting anyone check where an AI-generated recording came from (Art. 6(1)(f) GDPR).</p>
<h2>Your browser</h2>
<p>${site} stores nothing in your browser: no cookies and no local storage.</p>
<h2>Email</h2>
<p>If you email us, we use your address and message only to reply (Art. 6(1)(f) GDPR) and delete them once the matter is settled, unless the law requires us to keep them.</p>
<h2>Your rights</h2>
<p>You have the right of access to your personal data (Art. 15 GDPR), to rectification (Art. 16), to erasure (Art. 17), to restriction of processing (Art. 18) and to data portability (Art. 20). To exercise them, email us. You can also lodge a complaint with a data protection supervisory authority (Art. 77 GDPR), for example the one where you live or the one responsible for us: ${esc(l.authority)}.</p>
<h2>Right to object</h2>
<p><strong>You may object at any time, on grounds relating to your particular situation, to the processing of your personal data based on Art. 6(1)(f) GDPR (Art. 21 GDPR).</strong></p>`;
}

function privacyDe(site: string, address: string, mail: string, l: LegalInfo) {
  return `<p>${site} hat keine Benutzerkonten und setzt keine Cookies. Es verwendet keine Tracking- oder Werbedienste, wertet weder Besucher noch ihr Verhalten aus und trifft keine automatisierten Entscheidungen über dich. Diese Erklärung beschreibt, welche personenbezogenen Daten trotzdem verarbeitet werden, wenn du ${site} öffnest, vor allem deine IP-Adresse, und was zu einem eingetragenen Beleg gespeichert wird.</p>
<h2>Verantwortlicher</h2>${address}<p>E-Mail: ${mail}</p>
<h2>Hosting</h2>
<p>Cloudflare, Inc., 101 Townsend St., San Francisco, CA 94107, USA, betreibt ${site} in unserem Auftrag: die Seiten, die Liste der Belege und das Programm dahinter (einen Cloudflare Worker). Dazu verarbeitet Cloudflare deine IP-Adresse, die Adresse der aufgerufenen Seite, den Zeitpunkt und Angaben, die dein Browser mitsendet, etwa den User-Agent. Du musst diese Daten nicht bereitstellen, ohne sie kann dir aber nichts angezeigt werden.</p>
<p>Anfragen, die unser Worker bearbeitet, werden zusätzlich protokolliert, samt IP-Adresse, dem ungefähren Standort, den Cloudflare daraus ableitet, und der aufgerufenen Adresse. Wir nutzen diese Protokolle nur, um Fehler zu beheben und Missbrauch zu verhindern; sie werden nach spätestens 7 Tagen gelöscht.</p>
<p>Um Missbrauch zu verhindern, zählt der Worker Abfragen und neue Einträge je IP-Adresse über eine Minute und weist Anfragen oberhalb einer Grenze ab. Die Zählung liegt nur im Arbeitsspeicher von Cloudflares Rate-Limiter und wird nicht mit einem Beleg gespeichert.</p>
<p>Schriften lädt unser Worker selbst und liefert sie von ${site} aus, dein Browser verbindet sich also nicht mit Fontshare oder jsDelivr.</p>
<p>Rechtsgrundlage ist unser berechtigtes Interesse an einem sicheren und zuverlässigen Betrieb von ${site} (Art. 6 Abs. 1 lit. f DSGVO). Cloudflare verarbeitet die Daten als unser Auftragsverarbeiter auf Grundlage eines Auftragsverarbeitungsvertrags (Art. 28 DSGVO). Cloudflare, Inc. ist nach dem EU-U.S. Data Privacy Framework zertifiziert, für das ein Angemessenheitsbeschluss der Europäischen Kommission besteht (Art. 45 DSGVO); der Vertrag enthält zusätzlich die EU-Standardvertragsklauseln. Mehr dazu in der <a href="https://www.cloudflare.com/de-de/privacypolicy/">Datenschutzerklärung von Cloudflare</a>.</p>
<h2>Eine Datei prüfen</h2>
<p>Wenn du eine Datei auf eine Seite ziehst, liest dein Browser sie auf deinem Gerät und berechnet ihren SHA-256-Fingerabdruck. Die Seite sendet dann diesen Fingerabdruck und, falls die Datei eine nennt, ihre Beleg-ID an ${site}, um beides nachzuschlagen. Die Datei selbst, ihr Ton und ihr Name werden nicht gesendet. Abgesehen vom oben beschriebenen Anfrageprotokoll werden Abfragen nicht gespeichert.</p>
<h2>Belege</h2>
<p>Eine OmniSuite-Installation kann für eine Datei, die sie erzeugt hat, einen Beleg eintragen. Zu jedem Beleg speichern wir in Cloudflare D1: die Beleg-ID, den SHA-256-Fingerabdruck der Datei, ihre Länge und Abtastrate, das Modell, Verfahren und Kennung des Wasserzeichens, Name und Seriennummer des Signaturzertifikats der Installation (ein zufälliger Name wie „OmniSuite install 1a2b3c4d“), den Zeitpunkt, den die Installation für die Datei angibt, den Zeitpunkt des Eintrags, den SHA-256-Fingerabdruck des Referenzclips der Stimme, wie die Stimme laut Installation angemeldet wurde, und die ID der Vollmacht, die den Eintrag erlaubt hat. Alles außer der ID der Vollmacht ist öffentlich: Wer die Beleg-ID oder die Datei hat, kann den Beleg nachschlagen. Ton, den gesprochenen Text, einen Namen, ein Konto oder die IP-Adresse der Installation speichern wir nicht mit einem Beleg.</p>
<p>Ein Eintrag braucht eine Vollmacht, die eine Person mit einem Passkey bei dem Anmeldedienst unterschrieben hat, mit dem dieses Register verbunden ist. Um zu zeigen, ob eine Vollmacht noch gilt, fragt ${site} bei diesem Dienst ihren Zustand und drei Zeitpunkte ab (Unterschrift, Ablauf, Widerruf). Mehr erfährt es über die Person nicht.</p>
<p>Ein Beleg bleibt eingetragen, bis wir ihn entfernen. Wenn ein Beleg dich betrifft und du ihn entfernt haben möchtest, etwa weil er ohne deine Einwilligung für deine Stimme eingetragen wurde, schreib uns. Rechtsgrundlage für das Speichern und Anzeigen ist unser berechtigtes Interesse, dass jeder nachprüfen kann, woher eine KI-erzeugte Aufnahme stammt (Art. 6 Abs. 1 lit. f DSGVO).</p>
<h2>Dein Browser</h2>
<p>${site} speichert nichts in deinem Browser: keine Cookies und keinen lokalen Speicher.</p>
<h2>E-Mail</h2>
<p>Wenn du uns schreibst, nutzen wir deine Adresse und Nachricht nur, um dir zu antworten (Art. 6 Abs. 1 lit. f DSGVO), und löschen sie, sobald die Sache erledigt ist, es sei denn, das Gesetz verpflichtet uns zur Aufbewahrung.</p>
<h2>Deine Rechte</h2>
<p>Du hast das Recht auf Auskunft über deine personenbezogenen Daten (Art. 15 DSGVO), auf Berichtigung (Art. 16), Löschung (Art. 17), Einschränkung der Verarbeitung (Art. 18) und Datenübertragbarkeit (Art. 20). Schreib uns dazu eine E-Mail. Außerdem kannst du dich bei einer Datenschutz-Aufsichtsbehörde beschweren (Art. 77 DSGVO), etwa bei der an deinem Wohnort oder bei der für uns zuständigen: ${esc(l.authority)}.</p>
<h2>Widerspruchsrecht</h2>
<p><strong>Du kannst der Verarbeitung deiner personenbezogenen Daten auf Grundlage von Art. 6 Abs. 1 lit. f DSGVO jederzeit aus Gründen widersprechen, die sich aus deiner besonderen Situation ergeben (Art. 21 DSGVO).</strong></p>`;
}
