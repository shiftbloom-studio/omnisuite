// SPDX-License-Identifier: AGPL-3.0-or-later
// Text imports produced by `npm run build:client` (esbuild and wrangler load *.txt as strings).
declare module "*.txt" {
  const text: string;
  export default text;
}
