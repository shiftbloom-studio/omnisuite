// SPDX-License-Identifier: AGPL-3.0-or-later
import { describe, expect, it } from "vitest";
import { parseAuthorization } from "../src/mandates";
import { AUDIO, ID, limiter, listing, MANDATE, ORIGIN, stand, VOICE } from "./stand";

const OTHER_ID = "11111111-2222-4333-8444-555555555555";
const LEGAL = JSON.stringify({ name: "Jane Doe", street: "Example St 1", city: "12345 Town", country: { en: "Germany", de: "Deutschland" }, email: "jane@example.com", authority: "The authority" });

describe("listing a receipt", () => {
  it("asks stem about exactly this request and keeps the receipt", async () => {
    const { put, stem, call } = stand();
    const res = await put();
    expect(res.status).toBe(201);
    expect(await res.json()).toEqual({ id: ID, url: `${ORIGIN}/r/${ID}` });
    expect(stem.asked).toEqual([
      { chain: ["root.token.here"], pop: "pop.token.here", method: "PUT", url: `${ORIGIN}/voices/${VOICE}/receipts/${ID}`, action: "speak", path: `voices/${VOICE}/receipts/${ID}`, bytes: JSON.stringify(listing()).length },
    ]);
    const shown = (await (await call("GET", `/api/receipts/${ID}`)).json()) as Record<string, any>;
    expect(shown).toMatchObject({ id: ID, voice: VOICE, created: "2026-11-27T22:48:00+00:00", model: "k2-fsa/OmniVoice", audio: { sha256: AUDIO, seconds: 1, sample_rate: 24000 }, enrolment: "read-aloud" });
  });

  it("answers 200 when the same receipt comes again, and 409 when the id comes with other details", async () => {
    const { put } = stand();
    expect((await put()).status).toBe(201);
    expect((await put()).status).toBe(200);
    const other = await put({ ...listing(), audio: { ...listing().audio, sha256: "c".repeat(64) } });
    expect(other.status).toBe(409);
    expect(await other.json()).toMatchObject({ reason: "conflict" });
    expect((await put(listing(), { voice: "b".repeat(64) })).status).toBe(409);
  });

  it("needs a mandate and a proof", async () => {
    const { put, stem, signed } = stand();
    const incomplete: Record<string, string>[] = [{}, { authorization: signed.authorization }, { "mandate-pop": signed["mandate-pop"] }, { authorization: "Bearer abc", "mandate-pop": "x" }];
    for (const headers of incomplete) {
      const res = await put(listing(), { headers });
      expect(res.status).toBe(401);
      expect(await res.json()).toMatchObject({ reason: "missing_mandate" });
    }
    expect(stem.asked).toEqual([]);
  });

  it("passes on why stem said no, so an install knows whether its mandate is over", async () => {
    const { put, stem, call } = stand();
    for (const reason of ["revoked", "expired", "unknown", "invalid_pop", "replayed", "outside_mandate"]) {
      stem.answer = { allowed: false, reason, message: `refused: ${reason}` };
      const res = await put();
      expect(res.status).toBe(403);
      expect(await res.json()).toEqual({ error: `refused: ${reason}`, reason });
    }
    expect((await call("GET", `/api/receipts/${ID}`)).status).toBe(404);
  });

  it("asks an install to come back when stem can't be asked", async () => {
    const down = stand();
    down.stem.answer = new Error("stem is away");
    expect((await down.put()).status).toBe(503);
    down.stem.answer = { allowed: false, reason: "disabled", message: "Mandates are not enabled on this stem." };
    expect((await down.put()).status).toBe(503);
    const unbound = stand({ MANDATES: undefined });
    expect((await unbound.put()).status).toBe(503);
    expect((await down.call("GET", `/api/receipts/${ID}`)).status).toBe(404);
  });

  it("reads the listing before it asks stem, so a listing it can't take doesn't use up the proof", async () => {
    const { put, stem, call, signed } = stand();
    expect((await put({ ...listing(), text: "Hello." })).status).toBe(400);
    expect((await put("{not json")).status).toBe(400);
    expect((await put({ ...listing(), model: "x".repeat(5000) })).status).toBe(413);
    // without a Content-Length the body is still cut off at the cap
    const body = new ReadableStream({ start(c) { c.enqueue(new TextEncoder().encode(" ".repeat(5000))); c.close(); } });
    const streamed = await (await import("../src/index")).default.fetch(
      new Request(`${ORIGIN}/voices/${VOICE}/receipts/${ID}`, { method: "PUT", headers: signed, body, duplex: "half" } as RequestInit),
      stand().env,
      { waitUntil() {}, passThroughOnException() {} } as unknown as ExecutionContext,
    );
    expect(streamed.status).toBe(413);
    expect(stem.asked).toEqual([]);
    expect((await call("GET", `/api/receipts/${ID}`)).status).toBe(404);
  });

  it("only takes a clip hash and a receipt id in the address", async () => {
    const { put, stem, call } = stand();
    expect((await put(listing(), { voice: "my-voice" })).status).toBe(404);
    expect((await put(listing(), { id: "1" })).status).toBe(404);
    expect((await put(listing(), { id: ID.toUpperCase() })).status).toBe(404);
    expect(stem.asked).toEqual([]);
    const read = await call("GET", `/voices/${VOICE}/receipts/${ID}`);
    expect(read.status).toBe(405);
    expect(read.headers.get("allow")).toBe("PUT");
  });

  it("slows down an address that lists too fast, and a mandate that lists too much", async () => {
    const fast = stand({ LIST_RL: limiter(1) });
    expect((await fast.put()).status).toBe(201);
    const second = await fast.put(listing(), { id: OTHER_ID });
    expect(second.status).toBe(429);
    expect(second.headers.get("retry-after")).toBe("60");
    expect(fast.stem.asked).toHaveLength(1);

    const full = stand({ MAX_LISTINGS_PER_DAY: "1" });
    expect((await full.put()).status).toBe(201);
    expect((await full.put(listing(), { id: OTHER_ID })).status).toBe(429);
    // another mandate still has its own share
    full.stem.answer = { allowed: true, mandate: "9d3c1f6e-0a61-4c4e-8a57-3a3f3f0f6b22" };
    expect((await full.put(listing(), { id: OTHER_ID })).status).toBe(201);

    // 0 lifts the ceiling
    const open = stand({ MAX_LISTINGS_PER_DAY: "0" });
    expect((await open.put()).status).toBe(201);
    expect((await open.put(listing(), { id: OTHER_ID })).status).toBe(201);
  });
});

describe("looking a receipt up", () => {
  it("shows whether the mandate still stands, and never its id", async () => {
    const { put, call, stem } = stand();
    await put();
    const res = await call("GET", `/api/receipts/${ID}`);
    expect(res.headers.get("access-control-allow-origin")).toBe("*");
    expect(res.headers.get("cache-control")).toBe("no-store");
    const text = await res.text();
    expect(text).not.toContain(MANDATE);
    expect(JSON.parse(text).mandate).toMatchObject({ status: "active", signed_at: "2026-11-27T20:00:00.000Z", expires_at: "2026-12-27T20:00:00.000Z" });

    stem.state = { status: "revoked", created_at: "2026-11-27T20:00:00.000Z", expires_at: "2026-12-27T20:00:00.000Z", revoked_at: "2026-12-09T08:00:00.000Z" };
    expect(((await (await call("GET", `/api/receipts/${ID}`)).json()) as any).mandate).toMatchObject({ status: "revoked", revoked_at: "2026-12-09T08:00:00.000Z" });

    stem.state = new Error("stem is away");
    expect(((await (await call("GET", `/api/receipts/${ID}`)).json()) as any).mandate.status).toBe("unavailable");
    stem.state = { status: "surprise" } as never;
    expect(((await (await call("GET", `/api/receipts/${ID}`)).json()) as any).mandate.status).toBe("unavailable");
  });

  it("finds receipts by a file's fingerprint, oldest first", async () => {
    const { put, call } = stand();
    await put();
    await put(listing(), { id: OTHER_ID, voice: "b".repeat(64) });
    const found = (await (await call("GET", `/api/receipts?audio=${AUDIO}`)).json()) as any;
    expect(found.audio).toBe(AUDIO);
    expect(found.receipts.map((r: any) => r.id).sort()).toEqual([OTHER_ID, ID].sort());
    expect(((await (await call("GET", `/api/receipts?audio=${"d".repeat(64)}`)).json()) as any).receipts).toEqual([]);
    expect((await call("GET", "/api/receipts?audio=nope")).status).toBe(400);
    expect((await call("GET", "/api/receipts")).status).toBe(400);
  });

  it("answers 404 for what is not listed, and only reads", async () => {
    const { call } = stand();
    expect((await call("GET", `/api/receipts/${ID}`)).status).toBe(404);
    expect((await call("GET", "/api/receipts/1%27%20OR%201=1")).status).toBe(404);
    expect((await call("GET", "/api/else")).status).toBe(404);
    expect((await call("DELETE", `/api/receipts/${ID}`)).status).toBe(405);
    const preflight = await call("OPTIONS", `/api/receipts/${ID}`);
    expect(preflight.status).toBe(204);
    expect(preflight.headers.get("access-control-allow-methods")).toBe("GET, HEAD");
  });

  it("slows down an address that looks up too fast", async () => {
    const { put, call } = stand({ READ_RL: limiter(1) });
    await put();
    expect((await call("GET", `/api/receipts/${ID}`)).status).toBe(200);
    expect((await call("GET", `/api/receipts/${ID}`)).status).toBe(429);
    expect((await call("GET", `/r/${ID}`)).status).toBe(429);
  });
});

describe("the pages", () => {
  it("serve the check without inline scripts and under a strict policy", async () => {
    const { call } = stand();
    const res = await call("GET", "/");
    expect(res.status).toBe(200);
    const csp = res.headers.get("content-security-policy")!;
    expect(csp).toContain("default-src 'none'");
    expect(csp).toContain("connect-src 'self'");
    expect(csp).toContain("frame-ancestors 'none'");
    expect(res.headers.get("x-frame-options")).toBe("DENY");
    expect(res.headers.get("x-robots-tag")).toBeNull();
    const page = await res.text();
    expect(page).toContain('id="drop"');
    expect(page).toContain('<script src="/assets/app.js" defer></script>');
    expect(page.match(/<script/g)).toHaveLength(1);
    expect(page).not.toContain("/privacy");
    const script = await call("GET", "/assets/app.js");
    expect(script.headers.get("content-type")).toContain("javascript");
    expect(await script.text()).toContain("/api/receipts");
  });

  it("show a receipt with its mandate and keep it out of search engines", async () => {
    const { put, call } = stand();
    await put();
    const res = await call("GET", `/r/${ID}`);
    expect(res.status).toBe(200);
    expect(res.headers.get("x-robots-tag")).toBe("noindex, nofollow");
    expect(res.headers.get("cache-control")).toBe("no-store");
    const page = await res.text();
    expect(page).toContain(`data-receipt="${ID}"`);
    expect(page).toContain(AUDIO);
    expect(page).toContain("mandate stands");
    expect(page).toContain("The mandate behind this listing stands.");
    expect(page).toContain("Listed on 27 November 2026");
    expect(page).not.toContain(MANDATE);
  });

  it("escape whatever a row holds", async () => {
    const { env, call } = stand();
    await env.DB.prepare(
      "INSERT INTO receipts (id, voice, mandate, listed_at, created, model, audio_sha256, seconds, sample_rate, watermark_scheme, watermark_tag, signer_name, signer_serial, enrolment) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
    ).bind(ID, VOICE, MANDATE, 1795819680, "<b>when</b>", "<script>alert(1)</script>", AUDIO, 1, 24000, "<i>", "2d3d", "\"><img src=x onerror=alert(1)>", "1", null).run();
    const page = await (await call("GET", `/r/${ID}`)).text();
    expect(page).not.toContain("<script>alert(1)</script>");
    expect(page).not.toContain("<img src=x");
    expect(page).not.toContain("<b>when</b>");
    expect(page).toContain("&lt;script&gt;alert(1)&lt;/script&gt;");
  });

  it("send the form's id to its receipt, and say so when there is none", async () => {
    const { call } = stand();
    const to = await call("GET", `/r?id=%20${ID.toUpperCase()}%20`);
    expect(to.status).toBe(303);
    expect(to.headers.get("location")).toBe(`${ORIGIN}/r/${ID}`);
    expect((await call("GET", "/r?id=https://evil.test")).status).toBe(404);
    const none = await call("GET", `/r/${ID}`);
    expect(none.status).toBe(404);
    expect(await none.text()).toContain("No receipt with this id");
    expect((await call("GET", "/nowhere")).status).toBe(404);
    expect((await call("POST", "/")).status).toBe(405);
  });

  it("show the legal pages only when the operator is named", async () => {
    const off = stand();
    for (const path of ["/privacy", "/datenschutz", "/imprint", "/impressum"]) expect((await off.call("GET", path)).status).toBe(404);
    const on = stand({ LEGAL, SITE_NAME: "rings" });
    const privacy = await (await on.call("GET", "/privacy")).text();
    expect(privacy).toContain("Jane Doe");
    expect(privacy).toContain("rings has no user accounts");
    expect(await (await on.call("GET", "/datenschutz")).text()).toContain('lang="de"');
    expect(await (await on.call("GET", "/impressum")).text()).toContain("Angaben gemäß § 5 DDG");
    expect(await (await on.call("GET", "/imprint")).text()).toContain("jane@example.com");
    const home = await (await on.call("GET", "/")).text();
    expect(home).toContain('href="/privacy"');
    expect(home).toContain("rings<i>.</i>");
  });

  it("tell crawlers what is theirs to read", async () => {
    const { call } = stand();
    const robots = await (await call("GET", "/robots.txt")).text();
    expect(robots).toContain("Allow: /$");
    expect(robots).toContain("Disallow: /");
    expect(robots).toContain(`Sitemap: ${ORIGIN}/sitemap.xml`);
    expect(await (await call("GET", "/sitemap.xml")).text()).toContain(`<loc>${ORIGIN}/</loc>`);
    expect((await call("GET", "/favicon.svg")).headers.get("content-type")).toBe("image/svg+xml");
  });
});

describe("the Authorization header", () => {
  it("is read like stem reads it", () => {
    expect(parseAuthorization("Mandate a~b~c")).toEqual(["a", "b", "c"]);
    expect(parseAuthorization("mandate  a")).toEqual(["a"]);
    expect(parseAuthorization("Bearer a")).toBeNull();
    expect(parseAuthorization("Mandate ")).toBeNull();
    expect(parseAuthorization("Mandate a b")).toBeNull();
    expect(parseAuthorization(`Mandate ${Array(9).fill("a").join("~")}`)).toBeNull();
    expect(parseAuthorization(null)).toBeNull();
  });
});

describe("the Worker's entry module", () => {
  it("exports its handler and nothing else, because the Workers runtime takes every export for an entrypoint", async () => {
    expect(Object.keys(await import("../src/index"))).toEqual(["default"]);
  });
});
