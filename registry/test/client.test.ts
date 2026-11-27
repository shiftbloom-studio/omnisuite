// SPDX-License-Identifier: AGPL-3.0-or-later
import { describe, expect, it } from "vitest";
import { c2paChunk, manifestHints, sha256Hex, verdict } from "../src/client";
import type { PublicReceipt } from "../src/receipts";

const ID = "748e6a9a-9e9c-433b-8677-8e60f4465499";
const REGISTRY = "https://receipts.example.com";
const ascii = (text: string) => Array.from(text, (c) => c.charCodeAt(0));
const u32 = (n: number) => [n & 255, (n >> 8) & 255, (n >> 16) & 255, (n >> 24) & 255];
const chunk = (tag: string, data: number[]) => [...ascii(tag), ...u32(data.length), ...data, ...(data.length % 2 ? [0] : [])];
/** CBOR text: a short one carries its length in the first byte, a longer one in the byte after 0x78. */
const cborText = (text: string) => (text.length < 24 ? [0x60 + text.length, ...ascii(text)] : [0x78, text.length, ...ascii(text)]);
const pair = (key: string, value: string) => [...cborText(key), ...cborText(value)];

/** A WAV shaped like OmniSuite's: fmt, a data chunk of odd length, then the manifest. */
function wav(manifest: number[] | null) {
  const body = [...ascii("WAVE"), ...chunk("fmt ", Array(16).fill(0)), ...chunk("data", [1, 2, 3]), ...(manifest ? chunk("C2PA", manifest) : [])];
  return new Uint8Array([...ascii("RIFF"), ...u32(body.length), ...body]);
}

const manifest = (more: number[] = []) => [0xa4, ...pair("receipt_id", ID), ...pair("created", "2026-11-27T22:48:00+00:00"), ...more, ...pair("model", "k2-fsa/OmniVoice")];

describe("what a file says about itself", () => {
  it("names its receipt and its registry", () => {
    expect(manifestHints(wav(manifest(pair("registry", REGISTRY))))).toEqual({ receiptId: ID, registry: REGISTRY });
  });

  it("may name no registry", () => {
    expect(manifestHints(wav(manifest()))).toEqual({ receiptId: ID, registry: null });
  });

  it("gives the registry as an origin and nothing more", () => {
    expect(manifestHints(wav(manifest(pair("registry", "https://user:pw@Receipts.example.com:443/r/?x=1#frag")))).registry).toBe(REGISTRY);
    expect(manifestHints(wav(manifest(pair("registry", "javascript:alert(1)")))).registry).toBeNull();
    expect(manifestHints(wav(manifest(pair("registry", "not a url")))).registry).toBeNull();
  });

  it("only takes a real id as the receipt", () => {
    expect(manifestHints(wav([0xa1, ...pair("receipt_id", "<script>alert(1)</script>-0000-0000000")])).receiptId).toBeNull();
    expect(manifestHints(wav([0xa1, ...pair("receipt_id", ID.toUpperCase())])).receiptId).toBeNull();
  });

  it("says nothing about a file without a manifest, or one that is no WAV", () => {
    expect(manifestHints(wav(null))).toEqual({ receiptId: null, registry: null });
    expect(manifestHints(new Uint8Array(ascii(`ID3 receipt_id ${ID}`)))).toEqual({ receiptId: null, registry: null });
    expect(manifestHints(new Uint8Array(0))).toEqual({ receiptId: null, registry: null });
  });

  it("does not read past a chunk that claims to be longer than the file", () => {
    const cut = wav(manifest()).slice(0, 60);
    expect(c2paChunk(cut)).toBeNull();
    const lying = wav(manifest());
    lying[lying.length - manifest().length - 4] = 0xff; // the manifest chunk's size
    expect(manifestHints(lying)).toEqual({ receiptId: null, registry: null });
  });

  it("ignores a key at the very end of the manifest", () => {
    expect(manifestHints(wav([...manifest(), ...cborText("receipt_id")])).receiptId).toBe(ID);
    expect(manifestHints(wav([...cborText("receipt_id"), 0x78])).receiptId).toBeNull();
  });

  it("fingerprints bytes as SHA-256 in hex", async () => {
    expect(await sha256Hex(new Uint8Array(ascii("abc")))).toBe("ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad");
  });
});

describe("what the list says about a file", () => {
  const sha256 = "a".repeat(64);
  const receipt = (id: string, audio: string) => ({ id, audio: { sha256: audio } }) as PublicReceipt;

  it("counts a file as listed when it names the receipt and the receipt names its fingerprint", () => {
    expect(verdict({ sha256, receiptId: ID }, receipt(ID, sha256), [])).toMatchObject({ kind: "same" });
  });

  it("sees a file that was changed after it was listed", () => {
    expect(verdict({ sha256, receiptId: ID }, receipt(ID, "b".repeat(64)), [])).toMatchObject({ kind: "changed" });
  });

  it("treats a fingerprint listed under a receipt the file doesn't name as a claim", () => {
    const other = "11111111-2222-4333-8444-555555555555";
    expect(verdict({ sha256, receiptId: null }, null, [other])).toEqual({ kind: "claimed", ids: [other] });
    expect(verdict({ sha256, receiptId: ID }, null, [other])).toEqual({ kind: "claimed", ids: [other] });
  });

  it("says a file is not listed when nothing matches", () => {
    expect(verdict({ sha256, receiptId: null }, null, [])).toEqual({ kind: "unlisted" });
    expect(verdict({ sha256, receiptId: ID }, null, [])).toEqual({ kind: "unlisted" });
  });

  it("does not take a receipt for one the file doesn't name", () => {
    expect(verdict({ sha256, receiptId: null }, receipt(ID, sha256), [ID])).toEqual({ kind: "claimed", ids: [ID] });
  });
});
