# The receipt registry

A public list of receipts for speech made with OmniSuite, and a page where anyone
can check a file against it. It runs as one Cloudflare Worker with a D1 database.

OmniSuite works without it. The registry is for people who want to be able to
say, to someone who has never seen their machine: this recording came out of my
install, for a voice I confirmed with a passkey, at this time.

## How a receipt gets on the list

1. In OmniSuite, the owner of a voice confirms it with a passkey. That signs a
   [stem](https://github.com/shiftbloom-studio/stem) mandate: this install may
   list receipts for this one voice clip, for 30 days.
2. After each file made with that voice, OmniSuite sends its receipt to
   `PUT /voices/<clip hash>/receipts/<receipt id>`, with the mandate and a fresh
   proof that it holds the mandate's key.
3. The registry asks stem whether the mandate covers this exact request and
   still stands. If it does, the receipt is stored.

A receipt holds the file's SHA-256, its length and sample rate, the model, the
watermark tag, the name and serial of the install's signing certificate, the
hash of the voice's reference clip and how the voice was enrolled. It holds no
audio, no text and no hash of the text.

## What anyone can read

| Address | What it gives |
| --- | --- |
| `/` | The check page. Drop a WAV file and the browser works out its SHA-256, reads the receipt id from the file's C2PA manifest and looks both up. The file is not uploaded. |
| `/r/<receipt id>` | One receipt, with the state of the mandate behind it. |
| `GET /api/receipts/<receipt id>` | The same as JSON. |
| `GET /api/receipts?audio=<sha-256>` | The receipts listed for a fingerprint, oldest first. |

```json
{
  "id": "748e6a9a-9e9c-433b-8677-8e60f4465499",
  "voice": "<sha-256 of the voice's reference clip>",
  "listed_at": "2026-11-27T22:48:03.000Z",
  "created": "2026-11-27T22:48:00+00:00",
  "model": "k2-fsa/OmniVoice",
  "audio": { "sha256": "<sha-256 of the file>", "seconds": 4.2, "sample_rate": 24000 },
  "watermark": { "scheme": "audioseal_wm_16bits", "tag": "2d3d" },
  "signer": { "name": "OmniSuite install da196087", "serial": "5566…" },
  "enrolment": "read-aloud",
  "mandate": {
    "status": "active",
    "signed_at": "2026-11-27T20:00:00.000Z",
    "expires_at": "2026-12-27T20:00:00.000Z",
    "revoked_at": null,
    "summary": "The mandate behind this listing stands. It was signed on 27 November 2026 and runs until 27 December 2026."
  }
}
```

`mandate.status` is `active`, `revoked`, `expired`, `unknown`, or `unavailable`
when stem could not be asked. The mandate's id is not shown.

The check page gives one of four answers:

| Answer | When |
| --- | --- |
| Listed | The file names a receipt, the receipt is listed, and it lists this file's fingerprint. |
| Changed | The file names a listed receipt, but the listed fingerprint is another one. |
| Claimed | The fingerprint is listed, but under a receipt the file does not name. |
| Not listed | Nothing matches. |

## What a listing shows, and what it doesn't

- It shows that an install holding a mandate, which a person signed with a
  passkey at the stem this registry is bound to, listed this fingerprint at this
  time. `listed_at` is set by the registry. Everything else is what the install
  reported, and the registry does not check it.
- It does not show whose voice is in the recording. A mandate is signed for the
  hash of a reference clip, not for a person's identity.
- A file without a receipt is not suspicious for that reason alone. Most
  recordings were never listed, and converting or trimming a listed file gives
  it a new fingerprint.
- The check page reads the receipt id from the file without checking the
  manifest's signature. `omnisuite verify` checks signatures.
- The first listing of a receipt id keeps it. OmniSuite lists a file right after
  writing it. If the registry can't be reached at that moment and the file gets
  out before the retry, someone with a mandate of their own could list its id
  first, and the page would then show their listing for it.
- One mandate can list 2000 receipts a day (`MAX_LISTINGS_PER_DAY`).

## Answers to an install

| Status | Meaning |
| --- | --- |
| 201 | Listed. |
| 200 | This receipt was listed before, with the same details. |
| 409 | The receipt id is listed with other details. |
| 400, 413 | The listing is not in the expected form, or too large. |
| 401 | The mandate or the proof is missing. |
| 403 | stem refused. `reason` is stem's reason, such as `revoked`, `expired` or `outside_mandate`. |
| 429, 503 | Try again later. |

A listing is checked for its form before stem is asked, because a proof is good
for one request only.

## Run your own

You need a Cloudflare account and a stem on the same account with mandates
switched on.

```sh
cd registry
npm install
npx wrangler d1 create omnisuite-registry   # put the id it prints into wrangler.jsonc
npm run db:migrate
npm run deploy
```

Before the deploy, in `wrangler.jsonc`:

- set `routes` to your hostname. A mandate is signed for one origin, so the
  registry has to be reached under exactly the origin the installs name.
- set the `service` of the `MANDATES` binding to the name of your stem Worker.

Then tell the other two sides about it:

- stem, in `MANDATE_APPS`, with the label people see when they sign:

  ```json
  { "https://receipts.example.com": { "name": "OmniSuite receipts", "actions": { "speak": "Put receipts for speech in this voice on the public list" } } }
  ```

- OmniSuite, in its environment:

  ```sh
  OMNISUITE_STEM_URL=https://stem.example.com
  OMNISUITE_REGISTRY_URL=https://receipts.example.com
  ```

With Workers Builds, use `registry` as the root directory,
`npm run build:client` as the build command and `npx wrangler deploy` as the
deploy command.

| Variable | What it does |
| --- | --- |
| `SITE_NAME` | The name in the header. Default `receipts`. |
| `OPERATOR_NAME`, `OPERATOR_URL`, `OPERATOR_PLACE` | Who runs this instance, shown in the footer. |
| `SOURCE_URL` | Where your source is, if you changed the code (AGPL section 13). |
| `LEGAL` | Operator details as JSON. Switches on `/imprint`, `/impressum`, `/privacy` and `/datenschutz`. |
| `MAX_LISTINGS_PER_DAY` | Listings one mandate may add per day. Default 2000, 0 for no ceiling. |

To take a receipt off the list:

```sh
npx wrangler d1 execute omnisuite-registry --remote --command "DELETE FROM receipts WHERE id = '<receipt id>'"
```

## Develop

```sh
npx wrangler d1 migrations apply omnisuite-registry --local   # once, for the local database
npm run dev     # lookups and pages work; listing answers 503 without a stem to ask
npm run check   # types, tests and a dry-run build
```

`src/index.ts` holds the routes, `src/receipts.ts` the shape of a listing,
`src/client.ts` the script behind the check page. The tests put node:sqlite in
place of D1 and a stand-in in place of stem.
