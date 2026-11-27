// SPDX-License-Identifier: AGPL-3.0-or-later
/** The registry's side of a stem mandate: what it asks stem, and how it reads the header an install sends. */
import type { MandateStatus } from "./receipts";

/** The one thing a voice mandate allows here. stem shows its label from MANDATE_APPS on the approval page. */
export const ACTION = "speak";

/** stem's MandateGateway entrypoint, as far as this Worker uses it (see stem, docs/mandates.md). */
export type MandateGateway = {
  authorize(input: { chain: string[]; pop: string; method: string; url: string; action: string; path?: string; bytes?: number }): Promise<
    { allowed: true; mandate: string } | { allowed: false; reason: string; message: string }
  >;
  status(mandate: string): Promise<MandateStatus>;
};

/** "Mandate a~b~c" → ["a", "b", "c"], like stem's parseAuthorization. */
export function parseAuthorization(header: string | null): string[] | null {
  const m = /^Mandate\s+(\S+)$/i.exec((header || "").trim());
  if (!m) return null;
  const chain = m[1].split("~").filter(Boolean);
  return chain.length && chain.length <= 8 ? chain : null;
}
