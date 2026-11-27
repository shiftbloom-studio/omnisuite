// SPDX-License-Identifier: AGPL-3.0-or-later
import { describe, expect, it } from "vitest";
import { mandateView, parseListing, publicReceipt, sameListing, type Row } from "../src/receipts";
import { AUDIO, ID, listing, MANDATE, VOICE } from "./stand";

const row = (): Row => ({
  id: ID, voice: VOICE, mandate: MANDATE, listed_at: 1795819680, created: "2026-11-27T22:48:00+00:00", model: "k2-fsa/OmniVoice",
  audio_sha256: AUDIO, seconds: 1, sample_rate: 24000, watermark_scheme: "audioseal_wm_16bits", watermark_tag: "2d3d",
  signer_name: "OmniSuite install da196087", signer_serial: "556690278968825384034285161086665120268254592962", enrolment: "read-aloud",
});

describe("a listing as an install sends it", () => {
  it("is taken as it is", () => {
    const { listing: read, error } = parseListing(listing());
    expect(error).toBeUndefined();
    expect(read).toEqual({ ...listing(), version: undefined, enrolment: "read-aloud" });
  });

  it("may leave the enrolment out", () => {
    const { enrolment: _left, ...rest } = listing();
    expect(parseListing(rest).listing?.enrolment).toBeNull();
  });

  const change = (path: string, value: unknown) => {
    const sent = listing() as Record<string, any>;
    const keys = path.split(".");
    const last = keys.pop()!;
    const at = keys.reduce((o, k) => o[k], sent);
    if (value === undefined) delete at[last];
    else at[last] = value;
    return sent;
  };

  it.each([
    ["version", 2],
    ["created", "yesterday"],
    ["created", "2026-13-45T99:00:00Z"],
    ["created", undefined],
    ["model", "x".repeat(121)],
    ["model", "<script>alert(1)</script>\n"],
    ["model", "modèle"],
    ["audio.sha256", AUDIO.toUpperCase()],
    ["audio.sha256", AUDIO.slice(1)],
    ["audio.seconds", 0],
    ["audio.seconds", 86401],
    ["audio.seconds", "1.0"],
    ["audio.sample_rate", 24000.5],
    ["audio.sample_rate", 4000],
    ["watermark.scheme", "Audio Seal"],
    ["watermark.tag", "2d3"],
    ["watermark.tag", "zzzz"],
    ["signer.name", ""],
    ["signer.serial", "0x1f"],
    ["signer", "OmniSuite"],
    ["audio", [1, 2, 3]],
    ["enrolment", "trust me"],
    // The text never belongs on the list, and neither does its hash.
    ["text", "Hello."],
    ["text_sha256", AUDIO],
    ["audio.note", "extra"],
  ])("is refused when %s is %j", (path, value) => {
    const { listing: read, error } = parseListing(change(path, value));
    expect(read).toBeUndefined();
    expect(error).toMatch(/\S/);
  });

  it.each([null, "listing", 7, []])("is refused when it is %j", (sent) => {
    expect(parseListing(sent).error).toMatch(/object/);
  });

  it("does not repeat what was sent in its refusal", () => {
    const { error } = parseListing({ ...listing(), "<img src=x>": 1 });
    expect(error).not.toContain("<");
  });
});

describe("the same listing twice", () => {
  const read = () => parseListing(listing()).listing!;
  it("is recognised", () => expect(sameListing(row(), VOICE, read())).toBe(true));
  it("is not the same under another voice", () => expect(sameListing(row(), "b".repeat(64), read())).toBe(false));
  it("is not the same with another fingerprint", () => expect(sameListing({ ...row(), audio_sha256: "c".repeat(64) }, VOICE, read())).toBe(false));
  it("is not the same without the enrolment", () => expect(sameListing({ ...row(), enrolment: null }, VOICE, read())).toBe(false));
});

describe("the mandate behind a listing", () => {
  const dates = { created_at: "2026-11-27T20:00:00.000Z", expires_at: "2026-12-27T20:00:00.000Z", revoked_at: null };
  it("stands", () => {
    const view = mandateView({ status: "active", ...dates }, 1795819680);
    expect(view).toMatchObject({ status: "active", signed_at: dates.created_at, expires_at: dates.expires_at, revoked_at: null });
    expect(view.summary).toBe("The mandate behind this listing stands. It was signed on 27 November 2026 and runs until 27 December 2026.");
  });
  it("was stopped", () => {
    const view = mandateView({ status: "revoked", ...dates, revoked_at: "2026-12-09T08:00:00.000Z" }, 1795819680);
    expect(view.summary).toContain("stopped it on 9 December 2026");
    expect(view.summary).toContain("listed before that, on 27 November 2026");
  });
  it("ran out", () => expect(mandateView({ status: "expired", ...dates }, 1795819680).summary).toContain("ran out on 27 December 2026"));
  it("is not known to stem", () => expect(mandateView({ status: "unknown", created_at: null, expires_at: null, revoked_at: null }, 1).status).toBe("unknown"));
  it("could not be asked about", () => expect(mandateView(null, 1)).toMatchObject({ status: "unavailable", signed_at: null }));
});

describe("a receipt as the public reads it", () => {
  it("holds the listing and the mandate's state, but not the mandate's id", () => {
    const shown = publicReceipt(row(), mandateView(null, 1795819680));
    expect(shown).toMatchObject({ id: ID, voice: VOICE, listed_at: "2026-11-27T22:48:00.000Z", audio: { sha256: AUDIO, seconds: 1, sample_rate: 24000 }, enrolment: "read-aloud" });
    expect(JSON.stringify(shown)).not.toContain(MANDATE);
  });
});
