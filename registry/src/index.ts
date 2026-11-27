// SPDX-License-Identifier: AGPL-3.0-or-later
/**
 * The receipt registry: a public list of receipts for speech made with OmniSuite, on one Cloudflare Worker.
 *
 * An install lists a receipt with a stem mandate that a person signed for one voice. stem checks the mandate
 * on every listing, D1 keeps the row, and anyone can look a receipt up by its id or by a file's fingerprint.
 */
import { handleAsset } from "./assets";
import { brandFrom } from "./brand";
import { brokenPage, configureUi, homePage, noReceiptPage, notFoundPage, receiptPage, slowDownPage } from "./html";
import { LEGAL_PATHS, legalPage, parseLegal } from "./legal";
import { ACTION, parseAuthorization, type MandateGateway } from "./mandates";
import { mandateView, MAX_LISTING_BYTES, parseListing, publicReceipt, sameListing, SHA256_RE, UUID_RE, type MandateStatus, type PublicReceipt, type Row } from "./receipts";

export interface Env {
  DB: D1Database;
  /** Service binding to stem. Without it nothing can be listed, and receipts show no mandate state. */
  MANDATES?: MandateGateway;
  /** Listings one mandate may add per day (default 2000, 0 = no ceiling). */
  MAX_LISTINGS_PER_DAY?: string;
  LEGAL?: string;
  BRAND?: string;
  SITE_NAME?: string;
  SOURCE_URL?: string;
  OPERATOR_NAME?: string;
  OPERATOR_URL?: string;
  OPERATOR_PLACE?: string;
  /** Per IP and minute: listings sent by installs, and lookups. */
  LIST_RL?: RateLimit;
  READ_RL?: RateLimit;
}

const now = () => Math.floor(Date.now() / 1000);
const ip = (req: Request) => req.headers.get("cf-connecting-ip") || "unknown";

// ---------- responses ----------
/**
 * Page CSP. All of the registry's own scripts are files on 'self'. The per-response nonce is for Cloudflare,
 * which reads it from this header and adds it to the snippet it may inject for bot detection.
 */
const pageCsp = (nonce: string) =>
  ["default-src 'none'", `script-src 'self' 'nonce-${nonce}'`, "style-src 'self' 'unsafe-inline'", "font-src 'self'", "img-src 'self' data:", "connect-src 'self'", "form-action 'self'", "base-uri 'none'", "frame-ancestors 'none'"].join("; ");

const newNonce = () => btoa(String.fromCharCode(...crypto.getRandomValues(new Uint8Array(16))));

const SECURITY = { "x-content-type-options": "nosniff", "referrer-policy": "no-referrer", "x-frame-options": "DENY", "strict-transport-security": "max-age=31536000; includeSubDomains" };

const html = (body: string, status = 200, cache = "no-store") =>
  new Response(body, { status, headers: { "content-type": "text/html; charset=utf-8", "content-security-policy": pageCsp(newNonce()), "cache-control": cache, ...SECURITY } });

const json = (data: unknown, status = 200, headers: Record<string, string> = {}) =>
  new Response(JSON.stringify(data, null, 2) + "\n", { status, headers: { "content-type": "application/json; charset=utf-8", "cache-control": "no-store", ...SECURITY, ...headers } });

const apiError = (status: number, error: string, headers: Record<string, string> = {}) => json({ error }, status, headers);

/** Lookups are public data, so any page or tool may read them. */
const OPEN = { "access-control-allow-origin": "*" };

/** The request body as text, or null once it passes `max` bytes, with or without a Content-Length. */
async function readCapped(req: Request, max: number): Promise<string | null> {
  if (Number(req.headers.get("content-length") || 0) > max) return null;
  if (!req.body) return "";
  const reader = req.body.getReader();
  const chunks: Uint8Array[] = [];
  let total = 0;
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    total += value.byteLength;
    if (total > max) { await reader.cancel().catch(() => {}); return null; }
    chunks.push(value);
  }
  const all = new Uint8Array(total);
  let o = 0;
  for (const c of chunks) { all.set(c, o); o += c.byteLength; }
  return new TextDecoder().decode(all);
}

// ---------- listing ----------
/**
 * PUT /voices/<sha-256 of the voice's reference clip>/receipts/<receipt id>
 *
 * 201 listed, 200 it was listed already, 409 the id is taken by other details. 401 and 403 carry stem's
 * `reason`, which tells an install whether its mandate is over. 429 and 503 mean: try again later.
 */
async function listReceipt(req: Request, env: Env, voice: string, id: string): Promise<Response> {
  if (!SHA256_RE.test(voice) || !UUID_RE.test(id)) return apiError(404, "A receipt is listed at /voices/<sha-256 of the voice clip>/receipts/<receipt id>, both in lowercase.");
  if (env.LIST_RL && !(await env.LIST_RL.limit({ key: ip(req) })).success) return apiError(429, "Too many listings from this address. Try again in a minute.", { "retry-after": "60" });

  const chain = parseAuthorization(req.headers.get("authorization"));
  const pop = req.headers.get("mandate-pop");
  if (!chain || !pop) return json({ error: "A listing needs a mandate: send Authorization: Mandate <chain> and Mandate-PoP.", reason: "missing_mandate" }, 401, { "www-authenticate": "Mandate" });

  // Read the listing before stem is asked: a proof is good for one request, and a listing nobody can take should not use it up.
  const raw = await readCapped(req, MAX_LISTING_BYTES);
  if (raw === null) return apiError(413, "A listing is at most 4 KB.");
  let sent: unknown;
  try {
    sent = JSON.parse(raw);
  } catch {
    return apiError(400, "The listing is not JSON.");
  }
  const { listing, error } = parseListing(sent);
  if (!listing) return apiError(400, `The listing was not taken: ${error}.`);

  if (!env.MANDATES) return apiError(503, "This registry is not connected to stem, so it can't check mandates.");
  let answer: Awaited<ReturnType<MandateGateway["authorize"]>>;
  try {
    answer = await env.MANDATES.authorize({ chain, pop, method: "PUT", url: req.url, action: ACTION, path: `voices/${voice}/receipts/${id}`, bytes: new TextEncoder().encode(raw).byteLength });
  } catch (e) {
    console.error("[registry] stem did not answer", String(e));
    return apiError(503, "The mandate could not be checked just now.");
  }
  if (!answer.allowed) {
    // stem itself is switched off or did not understand us: nothing the install did, so it should try again.
    if (answer.reason === "disabled" || answer.reason === "invalid_request") return apiError(503, "The mandate could not be checked just now.");
    return json({ error: answer.message, reason: answer.reason }, 403);
  }

  // An empty or unreadable setting keeps the default: only a plain 0 lifts the ceiling.
  const set = Number(env.MAX_LISTINGS_PER_DAY || 2000);
  const cap = Number.isFinite(set) ? set : 2000;
  if (cap > 0) {
    const today = await env.DB.prepare("SELECT COUNT(*) AS n FROM receipts WHERE mandate = ? AND listed_at > ?").bind(answer.mandate, now() - 86400).first<{ n: number }>();
    if (today && today.n >= cap) return apiError(429, "This mandate has listed its share for today. Try again tomorrow.", { "retry-after": "3600" });
  }

  const added = await env.DB.prepare(
    "INSERT INTO receipts (id, voice, mandate, listed_at, created, model, audio_sha256, seconds, sample_rate, watermark_scheme, watermark_tag, signer_name, signer_serial, enrolment) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) ON CONFLICT(id) DO NOTHING",
  )
    .bind(id, voice, answer.mandate, now(), listing.created, listing.model, listing.audio.sha256, listing.audio.seconds, listing.audio.sample_rate, listing.watermark.scheme, listing.watermark.tag, listing.signer.name, listing.signer.serial, listing.enrolment)
    .run();
  const listed = { id, url: `${new URL(req.url).origin}/r/${id}` };
  if (added.meta.changes === 1) return json(listed, 201);
  const row = await env.DB.prepare("SELECT * FROM receipts WHERE id = ?").bind(id).first<Row>();
  if (row && sameListing(row, voice, listing)) return json(listed, 200);
  return json({ error: "This receipt id is already listed with other details.", reason: "conflict" }, 409);
}

// ---------- lookups ----------
const KNOWN_STATES = ["active", "revoked", "expired", "unknown"];

async function readReceipt(env: Env, id: string): Promise<PublicReceipt | null> {
  const row = await env.DB.prepare("SELECT * FROM receipts WHERE id = ?").bind(id).first<Row>();
  if (!row) return null;
  let state: MandateStatus | null = null;
  if (env.MANDATES) {
    try {
      const said = await env.MANDATES.status(row.mandate);
      if (said && KNOWN_STATES.includes(said.status)) state = said;
    } catch (e) {
      console.error("[registry] stem did not answer", String(e));
    }
  }
  return publicReceipt(row, mandateView(state, row.listed_at));
}

const readLimited = async (req: Request, env: Env) => !!env.READ_RL && !(await env.READ_RL.limit({ key: ip(req) })).success;

const robotsTxt = (origin: string) =>
  ["# Search engines may read the start page and the legal pages. Receipts are looked up, not indexed.", "User-agent: *", "Content-Signal: search=yes, ai-input=yes, ai-train=no", "Allow: /$", "Allow: /sitemap.xml", "Allow: /privacy", "Allow: /imprint", "Allow: /datenschutz", "Allow: /impressum", "Disallow: /", "", `Sitemap: ${origin}/sitemap.xml`, ""].join("\n");

async function route(req: Request, env: Env, ctx: ExecutionContext): Promise<Response> {
  const url = new URL(req.url);
  const path = url.pathname;
  const m = req.method;
  const get = m === "GET" || m === "HEAD";

  const listing = /^\/voices\/([^/]+)\/receipts\/([^/]+)$/.exec(path);
  if (listing) return m === "PUT" ? listReceipt(req, env, listing[1], listing[2]) : apiError(405, "Receipts are listed with PUT. To read one, GET /api/receipts/<receipt id>.", { allow: "PUT" });

  if (path.startsWith("/api/")) {
    if (m === "OPTIONS") return new Response(null, { status: 204, headers: { ...OPEN, "access-control-allow-methods": "GET, HEAD", "access-control-max-age": "86400" } });
    if (!get) return apiError(405, "The lookup API is read-only.", { ...OPEN, allow: "GET, HEAD" });
    if (await readLimited(req, env)) return apiError(429, "Too many lookups from this address. Try again in a minute.", { ...OPEN, "retry-after": "60" });
    if (path === "/api/receipts") {
      const audio = url.searchParams.get("audio") || "";
      if (!SHA256_RE.test(audio)) return apiError(400, "Give the file's fingerprint: /api/receipts?audio=<sha-256 in lowercase hex>.", OPEN);
      const { results } = await env.DB.prepare("SELECT id, listed_at FROM receipts WHERE audio_sha256 = ? ORDER BY listed_at, id LIMIT 20").bind(audio).all<{ id: string; listed_at: number }>();
      return json({ audio, receipts: results.map((r) => ({ id: r.id, listed_at: new Date(r.listed_at * 1000).toISOString() })) }, 200, OPEN);
    }
    const one = /^\/api\/receipts\/([^/]+)$/.exec(path);
    if (one) {
      const receipt = UUID_RE.test(one[1]) ? await readReceipt(env, one[1]) : null;
      return receipt ? json(receipt, 200, OPEN) : apiError(404, "No receipt with this id is listed here.", OPEN);
    }
    return apiError(404, "unknown endpoint", OPEN);
  }

  if (!get) return apiError(405, "method not allowed", { allow: "GET, HEAD" });
  if (path === "/") return html(homePage(), 200, "public, max-age=300");
  if (path === "/robots.txt") return new Response(robotsTxt(url.origin), { headers: { "content-type": "text/plain; charset=utf-8", "cache-control": "public, max-age=3600" } });
  if (path === "/sitemap.xml")
    return new Response(`<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"><url><loc>${url.origin}/</loc></url></urlset>\n`, { headers: { "content-type": "application/xml; charset=utf-8", "cache-control": "public, max-age=3600" } });
  if (path.startsWith("/assets/") || path.startsWith("/favicon")) {
    const asset = await handleAsset(req, ctx);
    if (asset) return asset;
  }
  if (LEGAL_PATHS[path]) {
    const legal = parseLegal(env.LEGAL);
    return legal ? html(legalPage(LEGAL_PATHS[path], legal), 200, "public, max-age=3600") : html(notFoundPage(), 404);
  }
  // The form on the start page: /r?id=<receipt id>
  if (path === "/r") {
    const id = (url.searchParams.get("id") || "").trim().toLowerCase();
    return UUID_RE.test(id) ? Response.redirect(`${url.origin}/r/${id}`, 303) : html(noReceiptPage(), 404);
  }
  const page = /^\/r\/([^/]+)$/.exec(path);
  if (page) {
    if (await readLimited(req, env)) return html(slowDownPage(), 429);
    const receipt = UUID_RE.test(page[1]) ? await readReceipt(env, page[1]) : null;
    return receipt ? html(receiptPage(receipt)) : html(noReceiptPage(), 404);
  }
  return html(notFoundPage(), 404);
}

const INDEXABLE = new Set(["/", "/robots.txt", "/sitemap.xml", "/favicon.svg", "/privacy", "/datenschutz", "/imprint", "/impressum"]);

export default {
  async fetch(req: Request, env: Env, ctx: ExecutionContext) {
    const path = new URL(req.url).pathname;
    try {
      configureUi({ legal: !!parseLegal(env.LEGAL), brand: brandFrom(env), origin: new URL(req.url).origin });
      const res = await route(req, env, ctx);
      if (INDEXABLE.has(path) || path.startsWith("/assets/")) return res;
      // receipts, the API and "not found" stay out of search engines
      const r = new Response(res.body, res);
      r.headers.set("x-robots-tag", "noindex, nofollow");
      return r;
    } catch (e) {
      console.error("[registry] unhandled", String(e), (e as Error)?.stack);
      return path.startsWith("/api/") || path.startsWith("/voices/") ? apiError(500, "internal error") : html(brokenPage(), 500);
    }
  },
} satisfies ExportedHandler<Env>;
