// SPDX-License-Identifier: AGPL-3.0-or-later
/**
 * The one script the pages load (built into src/generated/app.txt, served as /assets/app.js).
 * It reads a dropped file in the browser, works out its SHA-256 and looks that up. The file never leaves the device.
 */
import type { PublicReceipt } from "./receipts";

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/;
/** Hashing needs the whole file in memory. */
export const MAX_FILE_BYTES = 300 * 1024 * 1024;

// ---------- what the file says about itself ----------

/** The C2PA chunk of a RIFF/WAVE file, or null when there is none. */
export function c2paChunk(bytes: Uint8Array): Uint8Array | null {
  const tag = (at: number) => String.fromCharCode(bytes[at], bytes[at + 1], bytes[at + 2], bytes[at + 3]);
  if (bytes.length < 12 || tag(0) !== "RIFF" || tag(8) !== "WAVE") return null;
  const view = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength);
  let at = 12;
  while (at + 8 <= bytes.length) {
    const size = view.getUint32(at + 4, true);
    const end = at + 8 + size;
    if (end > bytes.length) return null;
    if (tag(at) === "C2PA") return bytes.subarray(at + 8, end);
    at = end + (size % 2); // chunks are padded to an even length
  }
  return null;
}

/** The CBOR text that follows `key` (itself CBOR text), for every place the key shows up. */
function textsAfter(chunk: Uint8Array, key: string): string[] {
  const needle = [0x60 + key.length, ...Array.from(key, (c) => c.charCodeAt(0))];
  const found: string[] = [];
  for (let at = 0; at + needle.length < chunk.length; at++) {
    if (!needle.every((byte, i) => chunk[at + i] === byte)) continue;
    let from = at + needle.length;
    const head = chunk[from++];
    let size: number;
    if (head >= 0x60 && head <= 0x77) size = head - 0x60;
    else if (head === 0x78) size = chunk[from++];
    else if (head === 0x79) { size = (chunk[from] << 8) | chunk[from + 1]; from += 2; }
    else continue;
    if (from + size > chunk.length) continue;
    found.push(new TextDecoder().decode(chunk.subarray(from, from + size)));
  }
  return found;
}

export type Hints = { receiptId: string | null; registry: string | null };

/**
 * The receipt id and the registry an OmniSuite file names in its manifest. This reads, it does not check
 * the manifest's signature: a hint for where to look, never proof. `omnisuite verify` checks signatures.
 */
export function manifestHints(bytes: Uint8Array): Hints {
  const chunk = c2paChunk(bytes);
  if (!chunk) return { receiptId: null, registry: null };
  const receiptId = textsAfter(chunk, "receipt_id").find((t) => UUID.test(t)) ?? null;
  let registry: string | null = null;
  for (const t of textsAfter(chunk, "registry")) {
    try {
      const url = new URL(t);
      if (url.protocol === "https:" || url.protocol === "http:") { registry = url.origin; break; }
    } catch {}
  }
  return { receiptId, registry };
}

export async function sha256Hex(bytes: BufferSource): Promise<string> {
  const digest = new Uint8Array(await crypto.subtle.digest("SHA-256", bytes));
  return Array.from(digest, (b) => b.toString(16).padStart(2, "0")).join("");
}

// ---------- what the list says about the file ----------

export type Verdict =
  /** The file names a receipt, the receipt is listed, and the fingerprints are the same. */
  | { kind: "same"; receipt: PublicReceipt }
  /** The file names a listed receipt, but the listed fingerprint is another one. */
  | { kind: "changed"; receipt: PublicReceipt }
  /** The fingerprint is listed, but under a receipt the file does not name. */
  | { kind: "claimed"; ids: string[] }
  | { kind: "unlisted" };

/**
 * A file counts as listed only when both agree: the file names the receipt, and the receipt names the
 * file's fingerprint. A fingerprint on its own can be listed by anyone who holds a mandate and the file.
 */
export function verdict(file: { sha256: string; receiptId: string | null }, named: PublicReceipt | null, sameFingerprint: string[]): Verdict {
  if (named && file.receiptId === named.id) return { kind: named.audio.sha256 === file.sha256 ? "same" : "changed", receipt: named };
  const others = sameFingerprint.filter((id) => id !== file.receiptId);
  return others.length ? { kind: "claimed", ids: others } : { kind: "unlisted" };
}

class LookupError extends Error {
  constructor(public status: number) { super(`lookup failed (${status})`); }
}

async function getJson<T>(path: string): Promise<T | null> {
  const res = await fetch(path, { headers: { accept: "application/json" } });
  if (res.status === 404) return null;
  if (!res.ok) throw new LookupError(res.status);
  return (await res.json()) as T;
}

async function lookUp(file: { sha256: string; receiptId: string | null }): Promise<Verdict> {
  const named = file.receiptId ? await getJson<PublicReceipt>(`/api/receipts/${file.receiptId}`) : null;
  if (named) return verdict(file, named, []);
  const same = await getJson<{ receipts: { id: string }[] }>(`/api/receipts?audio=${file.sha256}`);
  return verdict(file, null, (same?.receipts ?? []).map((r) => r.id).filter((id) => UUID.test(id)));
}

// ---------- the page ----------

function el<K extends keyof HTMLElementTagNameMap>(tag: K, text = "", cls = ""): HTMLElementTagNameMap[K] {
  const node = document.createElement(tag);
  if (text) node.textContent = text;
  if (cls) node.className = cls;
  return node;
}

function show(result: HTMLElement, o: { label: string; title: string; text: string[]; links?: { href: string; text: string }[]; fingerprint?: string; yes?: boolean }) {
  const card = el("div", "", o.yes ? "result yes" : "result");
  card.append(el("span", o.label, o.yes ? "label red" : "label"), el("h2", o.title));
  for (const line of o.text) card.append(el("p", line));
  if (o.links?.length) {
    const row = el("div", "", "row");
    for (const link of o.links) {
      const a = el("a", link.text, "btn sm ghost");
      a.href = link.href;
      row.append(a);
    }
    card.append(row);
  }
  if (o.fingerprint) card.append(el("p", `SHA-256 ${o.fingerprint}`, "fp"));
  result.replaceChildren(card);
}

const dayOf = (iso: string) => new Date(iso).toLocaleDateString("en-GB", { day: "numeric", month: "long", year: "numeric", timeZone: "UTC" });

/** `onPage`: the receipt whose page this is, if any. */
function describe(result: HTMLElement, file: { sha256: string } & Hints, v: Verdict, onPage: string | null) {
  const open = (id: string, text = "Open the receipt") => ({ href: `/r/${id}`, text });
  const about = v.kind === "same" || v.kind === "changed" ? [v.receipt.id] : v.kind === "claimed" ? v.ids : [];
  const other = onPage && !about.includes(onPage) ? ["This file does not belong to the receipt on this page."] : [];
  const links = (id: string) => (id === onPage ? [] : [open(id)]);
  if (v.kind === "same")
    return show(result, {
      yes: true,
      label: "listed",
      title: onPage === v.receipt.id ? "This is the listed file." : "This file is on the list.",
      text: [
        ...other,
        `It names receipt ${v.receipt.id}, and its fingerprint is the one listed on ${dayOf(v.receipt.listed_at)}.`,
        v.receipt.mandate.summary,
        "A listing shows that someone holding a mandate put this exact file on the list. It doesn't show who made the file. For that, check its signature with omnisuite verify.",
      ],
      links: links(v.receipt.id),
      fingerprint: file.sha256,
    });
  if (v.kind === "changed")
    return show(result, {
      label: "changed",
      title: "The receipt is listed, but for a different file.",
      text: [...other, `This file names receipt ${v.receipt.id}. The fingerprint listed for that receipt is another one, so the file was changed after it was listed, or the receipt was copied into it.`],
      links: links(v.receipt.id),
      fingerprint: file.sha256,
    });
  if (v.kind === "claimed")
    return show(result, {
      label: "claimed",
      title: "Someone listed this fingerprint, but the file doesn't name that receipt.",
      text: [...other, `A file made with OmniSuite names its own receipt. This one ${file.receiptId ? "names another" : "names none"}, so the listing is a claim about the file and not a receipt for it.`],
      links: v.ids.filter((id) => id !== onPage).slice(0, 3).map((id) => open(id, `Receipt ${id.slice(0, 8)}`)),
      fingerprint: file.sha256,
    });
  const text = [...other, "That alone says little. Most recordings were never listed, and a listed file that was converted, trimmed or saved again has a new fingerprint."];
  if (file.receiptId) text.push(`The file names receipt ${file.receiptId}, which is not on this list.`);
  if (file.registry && file.registry !== location.origin) text.push(`It names another registry, ${file.registry}. Its receipt may be listed there.`);
  show(result, { label: "not listed", title: "This file has no receipt here.", text, fingerprint: file.sha256 });
}

async function check(file: File, result: HTMLElement, onPage: string | null) {
  if (file.size > MAX_FILE_BYTES) return show(result, { label: "too large", title: "This file is too large to check in the browser.", text: ["The limit is 300 MB."] });
  show(result, { label: "reading", title: "Working out the fingerprint", text: [file.name] });
  let facts: { sha256: string } & Hints;
  try {
    const bytes = new Uint8Array(await file.arrayBuffer());
    facts = { sha256: await sha256Hex(bytes), ...manifestHints(bytes) };
  } catch {
    return show(result, { label: "not read", title: "The file could not be read.", text: ["Try choosing it again."] });
  }
  try {
    describe(result, facts, await lookUp(facts), onPage);
  } catch (e) {
    const busy = e instanceof LookupError && e.status === 429;
    show(result, {
      label: "not checked",
      title: busy ? "Too many lookups from your address." : "The lookup did not work.",
      text: [busy ? "Wait a minute, then drop the file again." : "Try again in a moment."],
      fingerprint: facts.sha256,
    });
  }
}

function start() {
  const section = document.getElementById("check");
  const drop = document.getElementById("drop");
  const input = document.getElementById("file") as HTMLInputElement | null;
  const pick = document.getElementById("pick");
  const result = document.getElementById("result");
  if (!section || !drop || !input || !pick || !result) return;
  const onPage = section.getAttribute("data-receipt");
  const take = (file: File | null | undefined) => { if (file) void check(file, result, onPage); };
  pick.addEventListener("click", () => input.click());
  input.addEventListener("change", () => { take(input.files?.[0]); input.value = ""; });
  // A file dropped anywhere on the page is meant for the check, not for the browser to open.
  document.addEventListener("dragover", (e) => { e.preventDefault(); drop.classList.add("over"); });
  document.addEventListener("dragleave", (e) => { if (!e.relatedTarget) drop.classList.remove("over"); });
  document.addEventListener("drop", (e) => { e.preventDefault(); drop.classList.remove("over"); take(e.dataTransfer?.files?.[0]); });
}

if (typeof document !== "undefined") start();
