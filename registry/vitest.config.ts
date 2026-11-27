// SPDX-License-Identifier: AGPL-3.0-or-later
import { readFileSync } from "node:fs";
import { defineConfig } from "vitest/config";

export default defineConfig({
  // wrangler loads *.txt as a string; the tests need the same
  plugins: [{ name: "text", enforce: "pre", load: (id: string) => (id.endsWith(".txt") ? `export default ${JSON.stringify(readFileSync(id, "utf8"))}` : null) }],
  test: { environment: "node", include: ["test/**/*.test.ts"] },
});
