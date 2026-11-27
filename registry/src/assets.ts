// SPDX-License-Identifier: AGPL-3.0-or-later
/** Self-hosted assets: visitors only talk to this origin (no third-party font or CDN requests). */
import { faviconSvg } from "./bloom";
import APP_JS from "./generated/app.txt";

const FONT_CSS = "https://api.fontshare.com/v2/css?f[]=clash-display@500,600&f[]=general-sans@400,500,600&display=swap";
const MONO = (w: number) => `https://cdn.jsdelivr.net/npm/@fontsource/jetbrains-mono@5/files/jetbrains-mono-latin-${w}-normal.woff2`;
const ALLOWED = /^https:\/\/(cdn\.fontshare\.com\/wf\/[A-Za-z0-9_\-/]+\.(woff2|woff|ttf)|cdn\.jsdelivr\.net\/npm\/@fontsource\/jetbrains-mono@5\/files\/[a-z0-9\-]+\.woff2)$/;
const YEAR = "public, max-age=31536000, immutable";

const proxied = (u: string) => `/assets/x?u=${encodeURIComponent(u)}`;

async function cached(req: Request, ctx: ExecutionContext, build: () => Promise<Response>) {
  const cache = (caches as unknown as { default: Cache }).default;
  const key = new Request(new URL(req.url).toString(), { method: "GET" });
  const hit = await cache.match(key);
  if (hit) return hit;
  const res = await build();
  if (res.ok) ctx.waitUntil(cache.put(key, res.clone()));
  return res;
}

export async function handleAsset(req: Request, ctx: ExecutionContext): Promise<Response | null> {
  const url = new URL(req.url);
  const p = url.pathname;
  if (p === "/favicon.svg" || p === "/favicon.ico")
    return new Response(faviconSvg(), { headers: { "content-type": "image/svg+xml", "cache-control": "public, max-age=604800" } });
  if (p === "/assets/app.js")
    return new Response(APP_JS, { headers: { "content-type": "application/javascript; charset=utf-8", "cache-control": "public, max-age=3600" } });
  if (p === "/assets/fonts.css")
    return cached(req, ctx, async () => {
      let cssText = "";
      try {
        const r = await fetch(FONT_CSS, { cf: { cacheTtl: 86400 } } as RequestInit);
        if (r.ok) cssText = await r.text();
      } catch {}
      cssText = cssText.replace(/url\((['"]?)(?:https?:)?\/\/(cdn\.fontshare\.com\/[^'")]+)\1\)/g, (_m, _q, path) => `url('${proxied("https://" + path)}')`);
      for (const w of [400, 500]) cssText += `@font-face{font-family:'JetBrains Mono';font-style:normal;font-weight:${w};font-display:swap;src:url('${proxied(MONO(w))}') format('woff2')}\n`;
      return new Response(cssText, { headers: { "content-type": "text/css; charset=utf-8", "cache-control": "public, max-age=86400" } });
    });
  if (p === "/assets/x") {
    const u = url.searchParams.get("u") || "";
    if (!ALLOWED.test(u)) return new Response("not allowed", { status: 403 });
    return cached(req, ctx, async () => {
      const r = await fetch(u).catch(() => new Response(null, { status: 502 }));
      if (!r.ok) return new Response("upstream error", { status: 502 });
      const type = u.endsWith(".woff") ? "font/woff" : u.endsWith(".ttf") ? "font/ttf" : "font/woff2";
      return new Response(r.body, { headers: { "content-type": type, "cache-control": YEAR } });
    });
  }
  return null;
}
