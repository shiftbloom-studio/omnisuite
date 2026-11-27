// SPDX-License-Identifier: AGPL-3.0-or-later
/** What the tests put in place of Cloudflare and stem: D1 on node:sqlite, and a gateway that answers as told. */
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { DatabaseSync, type SQLInputValue } from "node:sqlite";
import worker, { type Env } from "../src/index";
import type { MandateGateway } from "../src/mandates";
import type { MandateStatus } from "../src/receipts";

export function d1(): D1Database {
  const db = new DatabaseSync(":memory:");
  db.exec(readFileSync(fileURLToPath(new URL("../migrations/0001_receipts.sql", import.meta.url).href), "utf8"));
  const prepare = (sql: string) => {
    let args: SQLInputValue[] = [];
    const statement = {
      bind: (...values: SQLInputValue[]) => { args = values; return statement; },
      first: async () => db.prepare(sql).get(...args) ?? null,
      all: async () => ({ results: db.prepare(sql).all(...args) }),
      run: async () => ({ meta: { changes: Number(db.prepare(sql).run(...args).changes) } }),
    };
    return statement;
  };
  return { prepare } as unknown as D1Database;
}

export const MANDATE = "0b0e8a52-55ad-4f0c-9d0e-3f1c0b6f7a11";
type Authorize = MandateGateway["authorize"];

/** stem as the registry sees it. `asked` keeps every authorize() call. */
export class Stem implements MandateGateway {
  asked: Parameters<Authorize>[0][] = [];
  answer: Awaited<ReturnType<Authorize>> | Error = { allowed: true, mandate: MANDATE };
  state: MandateStatus | Error = { status: "active", created_at: "2026-11-27T20:00:00.000Z", expires_at: "2026-12-27T20:00:00.000Z", revoked_at: null };
  async authorize(input: Parameters<Authorize>[0]) {
    this.asked.push(input);
    if (this.answer instanceof Error) throw this.answer;
    return this.answer;
  }
  async status() {
    if (this.state instanceof Error) throw this.state;
    return this.state;
  }
}

/** A rate limiter that lets `allowed` calls through. */
export const limiter = (allowed: number) => ({ limit: async () => ({ success: allowed-- > 0 }) }) as unknown as RateLimit;

export const ORIGIN = "https://receipts.example.com";
export const VOICE = "a".repeat(64);
export const ID = "748e6a9a-9e9c-433b-8677-8e60f4465499";
export const AUDIO = "2dc379677b4d6485e95818a1c0ffc9e3b5a2bc68635fd298d30ff7f0e6fadf07";

/** A listing exactly as omnisuite's mandate.py sends it. */
export const listing = () => ({
  version: 1,
  created: "2026-11-27T22:48:00+00:00",
  model: "k2-fsa/OmniVoice",
  audio: { sample_rate: 24000, seconds: 1.0, sha256: AUDIO },
  watermark: { scheme: "audioseal_wm_16bits", tag: "2d3d" },
  signer: { name: "OmniSuite install da196087", serial: "556690278968825384034285161086665120268254592962" },
  enrolment: "read-aloud",
});

export function stand(more: Partial<Env> = {}) {
  const stem = new Stem();
  const env: Env = { DB: d1(), MANDATES: stem, ...more };
  const ctx = { waitUntil() {}, passThroughOnException() {} } as unknown as ExecutionContext;
  const call = (method: string, path: string, init: { body?: unknown; headers?: Record<string, string> } = {}) =>
    worker.fetch(
      new Request(ORIGIN + path, { method, headers: init.headers, body: init.body === undefined ? undefined : typeof init.body === "string" ? init.body : JSON.stringify(init.body) }),
      env,
      ctx,
    );
  const signed = { authorization: "Mandate root.token.here", "mandate-pop": "pop.token.here" };
  /** Lists a receipt the way an install does. */
  const put = (body: unknown = listing(), o: { id?: string; voice?: string; headers?: Record<string, string> } = {}) =>
    call("PUT", `/voices/${o.voice ?? VOICE}/receipts/${o.id ?? ID}`, { body, headers: o.headers ?? signed });
  return { env, stem, call, put, signed };
}
