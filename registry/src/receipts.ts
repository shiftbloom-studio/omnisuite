// SPDX-License-Identifier: AGPL-3.0-or-later
/**
 * What a listing is: the shape an OmniSuite install sends, the row kept for it, and what the public gets to see.
 * A listing holds fingerprints and marks. No audio, no text, and nothing about the person who signed the mandate.
 */

export const UUID_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/;
export const SHA256_RE = /^[0-9a-f]{64}$/;
/** A listing is a few hundred bytes. Anything far beyond that is not one. */
export const MAX_LISTING_BYTES = 4096;

export type Listing = {
  created: string;
  model: string;
  audio: { sha256: string; seconds: number; sample_rate: number };
  watermark: { scheme: string; tag: string };
  signer: { name: string; serial: string };
  enrolment: "read-aloud" | "none" | null;
};

export type Row = {
  id: string;
  voice: string;
  mandate: string;
  listed_at: number;
  created: string;
  model: string;
  audio_sha256: string;
  seconds: number;
  sample_rate: number;
  watermark_scheme: string;
  watermark_tag: string;
  signer_name: string;
  signer_serial: string;
  enrolment: string | null;
};

class Refused extends Error {}

const PRINTABLE = /^[\x20-\x7e]+$/;
const CREATED = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d{1,6})?(Z|[+-]\d{2}:\d{2})$/;

/** An object with exactly the fields we know. An install that sends more is ahead of this registry, or is not an install. */
function fields(value: unknown, known: string[], where: string): Record<string, unknown> {
  if (!value || typeof value !== "object" || Array.isArray(value)) throw new Refused(`${where} must be an object`);
  for (const key of Object.keys(value)) if (!known.includes(key)) throw new Refused(`${where} has a field this registry does not know`);
  return value as Record<string, unknown>;
}

function text(value: unknown, where: string, max: number, shape: RegExp = PRINTABLE): string {
  if (typeof value !== "string" || !value || value.length > max || !shape.test(value)) throw new Refused(`${where} is missing or not in the expected form`);
  return value;
}

function number(value: unknown, where: string, min: number, max: number, whole = false): number {
  if (typeof value !== "number" || !Number.isFinite(value) || value < min || value > max || (whole && !Number.isInteger(value))) throw new Refused(`${where} is missing or out of range`);
  return value;
}

/** Reads a listing as sent by an install. Strict on purpose: these fields end up on a public page. */
export function parseListing(value: unknown): { listing: Listing; error?: undefined } | { listing?: undefined; error: string } {
  try {
    const top = fields(value, ["version", "created", "model", "audio", "watermark", "signer", "enrolment"], "the listing");
    if (top.version !== 1) throw new Refused("version must be 1");
    const created = text(top.created, "created", 40, CREATED);
    if (Number.isNaN(Date.parse(created))) throw new Refused("created is not a date");
    const audio = fields(top.audio, ["sha256", "seconds", "sample_rate"], "audio");
    const watermark = fields(top.watermark, ["scheme", "tag"], "watermark");
    const signer = fields(top.signer, ["name", "serial"], "signer");
    if (top.enrolment !== undefined && top.enrolment !== "read-aloud" && top.enrolment !== "none") throw new Refused("enrolment must be read-aloud or none");
    return {
      listing: {
        created,
        model: text(top.model, "model", 120),
        audio: {
          sha256: text(audio.sha256, "audio.sha256", 64, SHA256_RE),
          seconds: number(audio.seconds, "audio.seconds", 0.001, 86400),
          sample_rate: number(audio.sample_rate, "audio.sample_rate", 8000, 192000, true),
        },
        watermark: { scheme: text(watermark.scheme, "watermark.scheme", 64, /^[a-z0-9_.-]+$/), tag: text(watermark.tag, "watermark.tag", 4, /^[0-9a-f]{4}$/) },
        signer: { name: text(signer.name, "signer.name", 120), serial: text(signer.serial, "signer.serial", 60, /^[0-9]+$/) },
        enrolment: (top.enrolment as Listing["enrolment"] | undefined) ?? null,
      },
    };
  } catch (e) {
    if (e instanceof Refused) return { error: e.message };
    throw e;
  }
}

/** Whether a row already says what this listing says, so sending it twice is not an error. */
export function sameListing(row: Row, voice: string, l: Listing): boolean {
  return (
    row.voice === voice && row.created === l.created && row.model === l.model &&
    row.audio_sha256 === l.audio.sha256 && row.seconds === l.audio.seconds && row.sample_rate === l.audio.sample_rate &&
    row.watermark_scheme === l.watermark.scheme && row.watermark_tag === l.watermark.tag &&
    row.signer_name === l.signer.name && row.signer_serial === l.signer.serial && row.enrolment === l.enrolment
  );
}

// ---------- the mandate behind a listing ----------

/** What stem says about a mandate (MandateGateway.status). */
export type MandateStatus = { status: "active" | "revoked" | "expired" | "unknown"; created_at: string | null; expires_at: string | null; revoked_at: string | null };

export type MandateView = {
  /** "unavailable": stem could not be asked just now. */
  status: MandateStatus["status"] | "unavailable";
  signed_at: string | null;
  expires_at: string | null;
  revoked_at: string | null;
  /** One sentence for people. */
  summary: string;
};

export const day = (when: string | number | null) => {
  const date = new Date(typeof when === "number" ? when * 1000 : when ?? NaN);
  return Number.isNaN(date.getTime()) ? "an unknown date" : date.toLocaleDateString("en-GB", { day: "numeric", month: "long", year: "numeric", timeZone: "UTC" });
};

export function mandateView(s: MandateStatus | null, listedAt: number): MandateView {
  if (!s) return { status: "unavailable", signed_at: null, expires_at: null, revoked_at: null, summary: "The state of the mandate behind this listing can't be checked right now." };
  const dates = { signed_at: s.created_at, expires_at: s.expires_at, revoked_at: s.revoked_at };
  switch (s.status) {
    case "active":
      return { status: "active", ...dates, summary: `The mandate behind this listing stands. It was signed on ${day(s.created_at)} and runs until ${day(s.expires_at)}.` };
    case "revoked":
      return { status: "revoked", ...dates, summary: `The person who signed the mandate behind this listing stopped it on ${day(s.revoked_at)}. The receipt was listed before that, on ${day(listedAt)}.` };
    case "expired":
      return { status: "expired", ...dates, summary: `The mandate behind this listing ran out on ${day(s.expires_at)}. The receipt was listed while it stood, on ${day(listedAt)}.` };
    default:
      return { status: "unknown", ...dates, summary: "The service that keeps the mandates no longer knows the one behind this listing." };
  }
}

/** A receipt as anyone may read it. The mandate's id stays out: its state and dates are all a reader needs. */
export function publicReceipt(row: Row, mandate: MandateView) {
  return {
    id: row.id,
    voice: row.voice,
    listed_at: new Date(row.listed_at * 1000).toISOString(),
    created: row.created,
    model: row.model,
    audio: { sha256: row.audio_sha256, seconds: row.seconds, sample_rate: row.sample_rate },
    watermark: { scheme: row.watermark_scheme, tag: row.watermark_tag },
    signer: { name: row.signer_name, serial: row.signer_serial },
    enrolment: row.enrolment,
    mandate,
  };
}

export type PublicReceipt = ReturnType<typeof publicReceipt>;
