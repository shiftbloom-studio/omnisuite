"""Voice mandates: the owner of a voice signs off on its use, and receipts go on a public list.

A receipt in a file says which install made it. It cannot say that the person whose
voice it is agreed. A mandate adds that: the person confirms with a passkey on a stem
server (https://github.com/shiftbloom-studio/stem) that this install may speak with
this voice for a while. From then on each receipt is also listed in a registry, which
only takes receipts that come with a standing mandate. Anyone holding the file can
look its receipt up there and see whether the mandate still stands.

All of this is off unless ``OMNISUITE_STEM_URL`` and ``OMNISUITE_REGISTRY_URL`` are
set. Nothing here sends audio or text anywhere: a listing holds hashes and marks.

The wire format is stem's (docs/mandates.md there): an Ed25519 key per mandate, a
signed request, and a fresh proof of possession with every call.
"""

from __future__ import annotations

import base64
import datetime
import hashlib
import http.client
import json
import os
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from dataclasses import dataclass
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

STEM_ENV = "OMNISUITE_STEM_URL"
REGISTRY_ENV = "OMNISUITE_REGISTRY_URL"

ACTION = "speak"
MANDATE_SECONDS = 30 * 24 * 3600  # the longest stem signs for
REQUEST_TYP = "mandate-request+jwt"
POP_TYP = "mandate-pop+jwt"

WALLET_FILE = "mandate.json"
TIMEOUT_SECONDS = 10
MAX_ANSWER_BYTES = 64 * 1024
LOOPBACK = ("127.0.0.1", "localhost", "::1")
DEFAULT_PORTS = {"https": 443, "http": 80}
# Refusals that mean the mandate is over or cannot be used, as stem names them.
ENDED = ("revoked", "expired", "unknown", "invalid_chain", "invalid_human_proof")
# Refusals that say nothing against the receipt: a proof that came too late or
# twice (a clock that is off does that), or a budget that is used up for now.
NOT_NOW = ("invalid_pop", "replayed", "over_budget")


class MandateError(Exception):
    """Something went wrong that the person at the page should read about."""


class Unreachable(MandateError):
    """The other server did not answer, or not in a way that makes sense."""


# ── Where to ask ─────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class Services:
    """The two servers a mandate involves, each as an origin without a path."""

    stem: str
    registry: str


def origin(url: str) -> str | None:
    """``url`` as a bare origin, or None when it is not one this module will call.

    Only https, so a key proof never crosses the network in the clear. Plain http
    is accepted for this machine itself, which is what tests and local setups use.
    """
    try:
        parts = urllib.parse.urlsplit(url.strip())
        host, port = parts.hostname, parts.port
    except ValueError:
        return None
    if not host or parts.username or parts.password or parts.query or parts.fragment:
        return None
    if parts.path not in ("", "/"):
        return None
    if parts.scheme != "https" and not (parts.scheme == "http" and host in LOOPBACK):
        return None
    if ":" in host:
        host = f"[{host}]"
    if port is None or port == DEFAULT_PORTS[parts.scheme]:
        return f"{parts.scheme}://{host}"
    return f"{parts.scheme}://{host}:{port}"


def services(environ=None) -> Services | None:
    """The configured servers, or None when mandates are off."""
    environ = os.environ if environ is None else environ
    stem, registry = environ.get(STEM_ENV, ""), environ.get(REGISTRY_ENV, "")
    if not stem and not registry:
        return None
    found = Services(stem=origin(stem) or "", registry=origin(registry) or "")
    if not found.stem or not found.registry:
        print(
            f"Voice mandates stay off: {STEM_ENV} and {REGISTRY_ENV} must both be "
            "https origins, like https://id.example.com"
        )
        return None
    return found


# ── Keys and signed tokens ───────────────────────────────────────────────────


def _b64u(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _b64u_decode(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def _compact(value: dict) -> bytes:
    return json.dumps(value, separators=(",", ":")).encode()


def new_key() -> dict:
    """A new Ed25519 key as a private JWK. The mandate will be bound to it."""
    private = Ed25519PrivateKey.generate()
    return {
        "kty": "OKP",
        "crv": "Ed25519",
        "x": _b64u(
            private.public_key().public_bytes(
                serialization.Encoding.Raw, serialization.PublicFormat.Raw
            )
        ),
        "d": _b64u(
            private.private_bytes(
                serialization.Encoding.Raw,
                serialization.PrivateFormat.Raw,
                serialization.NoEncryption(),
            )
        ),
    }


def public_jwk(key: dict) -> dict:
    return {"kty": key["kty"], "crv": key["crv"], "x": key["x"]}


def sign_jwt(key: dict, header: dict, claims: dict) -> str:
    """A compact JWT signed with ``key`` (EdDSA)."""
    private = Ed25519PrivateKey.from_private_bytes(_b64u_decode(key["d"]))
    signed = f"{_b64u(_compact({'alg': 'EdDSA', **header}))}.{_b64u(_compact(claims))}"
    return f"{signed}.{_b64u(private.sign(signed.encode()))}"


def claims_of(token: str) -> dict:
    """The claims of a JWT, unchecked. Raises ValueError when it is not one."""
    parts = token.split(".")
    if len(parts) != 3:
        raise ValueError("not a JWT")
    claims = json.loads(_b64u_decode(parts[1]))
    if not isinstance(claims, dict):
        raise ValueError("not a JWT")
    return claims


def _printable(text: str) -> str:
    return "".join(ch for ch in text if ch.isprintable())


def rights(registry: str, voice: str) -> list[dict]:
    """What a voice mandate allows: listing receipts for this one voice, nothing else."""
    return [
        {
            "type": "stem_mandate",
            "locations": [registry],
            "actions": [ACTION],
            "path_prefix": f"voices/{voice}/",
        }
    ]


def request_jwt(key: dict, registry: str, voice: str, name: str) -> str:
    """The signed request for a mandate. The person reads ``purpose`` before signing."""
    return sign_jwt(
        key,
        {"typ": REQUEST_TYP, "jwk": public_jwk(key)},
        {
            "authorization_details": rights(registry, voice),
            "purpose": f'Speak as "{_printable(name)[:100]}" with OmniSuite',
            "ttl": MANDATE_SECONDS,
            "del_max_depth": 0,
            "iat": int(time.time()),
        },
    )


def proof(key: dict, token: str, method: str, url: str) -> str:
    """Proof that the caller holds the key of ``token``. Good for one call, for a minute."""
    parts = urllib.parse.urlsplit(url)
    return sign_jwt(
        key,
        {"typ": POP_TYP},
        {
            "htm": method.upper(),
            "htu": f"{parts.scheme}://{parts.netloc}{parts.path}",
            "ath": _b64u(hashlib.sha256(token.encode()).digest()),
            "iat": int(time.time()),
            "jti": str(uuid.uuid4()),
        },
    )


# ── Talking to the two servers ───────────────────────────────────────────────


class _NoRedirects(urllib.request.HTTPRedirectHandler):
    """A proof is made for one URL. Being sent elsewhere is an error, not a detour."""

    def redirect_request(self, *args, **kwargs):
        return None


def send(method: str, url: str, body: dict, headers: dict | None = None) -> tuple[int, dict]:
    """Send JSON, get (status, JSON answer). Raises Unreachable when nobody answers."""
    request = urllib.request.Request(
        url,
        data=_compact(body),
        method=method,
        headers={
            "content-type": "application/json",
            "accept": "application/json",
            "user-agent": "OmniSuite",
            **(headers or {}),
        },
    )
    try:
        opener = urllib.request.build_opener(_NoRedirects)
        with opener.open(request, timeout=TIMEOUT_SECONDS) as response:
            status, raw = response.status, response.read(MAX_ANSWER_BYTES + 1)
    except urllib.error.HTTPError as error:
        status, raw = error.code, error.read(MAX_ANSWER_BYTES + 1)
    except (OSError, ValueError, http.client.HTTPException) as error:
        raise Unreachable(f"{urllib.parse.urlsplit(url).netloc} did not answer") from error
    try:
        answer = json.loads(raw) if len(raw) <= MAX_ANSWER_BYTES else None
    except ValueError:
        answer = None
    return status, answer if isinstance(answer, dict) else {}


# ── The wallet of a voice ────────────────────────────────────────────────────
#
# One file next to the voice's clip. It holds the private key the mandate is bound
# to, so it is written owner-only and never served.
#
#   {"version": 1, "stem": ..., "registry": ..., "voice": <sha256 of the clip>,
#    "request": {"key", "id", "user_code", "approve_url", "expires"},   while waiting
#    "signed":  {"key", "mandate", "id", "expires", "ended"?}}          once approved


def clip_hash(voice_dir: Path) -> str | None:
    """The name a voice goes by outside this machine: the SHA-256 of its clip."""
    try:
        return hashlib.sha256((voice_dir / "ref.wav").read_bytes()).hexdigest()
    except OSError:
        return None


def load_wallet(voice_dir: Path, where: Services, voice: str) -> dict:
    """The wallet of a voice. Empty when there is none or it is for something else."""
    try:
        wallet = json.loads((voice_dir / WALLET_FILE).read_text())
    except (OSError, ValueError):
        wallet = None
    fresh = {"version": 1, "stem": where.stem, "registry": where.registry, "voice": voice}
    if not isinstance(wallet, dict):
        return fresh
    # Another server, or a clip that changed since: what was signed no longer applies.
    if any(wallet.get(key) != value for key, value in fresh.items()):
        return fresh
    return wallet


def save_wallet(voice_dir: Path, wallet: dict) -> None:
    path = voice_dir / WALLET_FILE
    draft = voice_dir / f"{WALLET_FILE}.{uuid.uuid4().hex}.tmp"
    # Owner-only from the first byte, and swapped in whole.
    fd = os.open(draft, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w") as handle:
        handle.write(json.dumps(wallet, indent=2))
    os.replace(draft, path)


_wallets = threading.Lock()


def _change(voice_dir: Path, where: Services, voice: str, change) -> dict:
    """Read a wallet, change it and write it back, one caller at a time."""
    with _wallets:
        wallet = load_wallet(voice_dir, where, voice)
        change(wallet)
        save_wallet(voice_dir, wallet)
        return wallet


def _iso(seconds: int) -> str:
    return datetime.datetime.fromtimestamp(seconds, datetime.timezone.utc).isoformat(
        timespec="seconds"
    )


def standing(wallet: dict, now: float | None = None) -> dict | None:
    """The signed mandate of a wallet while it can still be used."""
    signed = wallet.get("signed")
    now = time.time() if now is None else now
    if not isinstance(signed, dict) or signed.get("ended") or signed.get("expires", 0) <= now:
        return None
    return signed


def state(wallet: dict, now: float | None = None) -> dict:
    """Where a voice stands, in a form that is safe to show: no keys, no tokens."""
    now = time.time() if now is None else now
    signed, request = wallet.get("signed"), wallet.get("request")
    shown: dict = {"state": "none"}
    if isinstance(signed, dict):
        live = standing(wallet, now) is not None
        shown = {
            "state": "signed" if live else "ended",
            "until": _iso(int(signed.get("expires", 0))),
        }
        if not live:
            shown["reason"] = signed.get("ended") or "expired"
    if isinstance(request, dict) and request.get("expires", 0) > now:
        # A new request does not end the mandate that is still running.
        shown["was"] = shown["state"]
        shown["state"] = "waiting"
        shown["approve_url"] = request["approve_url"]
        shown["user_code"] = request["user_code"]
        shown["expires_in"] = int(request["expires"] - now)
    return shown


def ask(where: Services, voice_dir: Path, voice: str, name: str) -> dict:
    """Ask stem for a mandate for this voice. Returns the state, now waiting.

    While a request is open, asking again changes nothing: the person may be
    signing that one right now, and a new key would make their answer worthless.
    """
    open_now = state(load_wallet(voice_dir, where, voice))
    if open_now["state"] == "waiting":
        return open_now
    key = new_key()
    status, answer = send(
        "POST",
        f"{where.stem}/api/auth/mandates/request",
        {"request": request_jwt(key, where.registry, voice, name)},
    )
    if status == 404:
        raise MandateError("That stem server does not offer mandates.")
    if status == 429:
        raise MandateError("Too many requests in a row. Wait a minute and try again.")
    approve_url = answer.get("approve_url")
    if (
        status != 200
        or not isinstance(answer.get("request_id"), str)
        or not isinstance(answer.get("user_code"), str)
        or not isinstance(approve_url, str)
        # The page opens this link. It has to lead to the stem server and nowhere else.
        or not approve_url.startswith(f"{where.stem}/")
    ):
        print(f"Mandate request refused ({status}): {str(answer.get('message'))[:200]!r}")
        raise MandateError(
            "The stem server turned the request down. See the server console for details."
        )
    lifetime = answer.get("expires_in")
    request = {
        "key": key,
        "id": answer["request_id"],
        "user_code": answer["user_code"],
        "approve_url": approve_url,
        "expires": int(time.time()) + (lifetime if isinstance(lifetime, int) else 600),
    }
    return state(_change(voice_dir, where, voice, lambda w: w.update(request=request)))


def _accept(token: object, key: dict, where: Services, voice: str) -> dict:
    """Check that a collected mandate is the one that was asked for."""
    try:
        claims = claims_of(token) if isinstance(token, str) else {}
        holder = claims.get("cnf", {}).get("jwk", {}).get("x")
    except (ValueError, AttributeError):
        claims, holder = {}, None
    if (
        holder != key["x"]
        or claims.get("authorization_details") != rights(where.registry, voice)
        or not isinstance(claims.get("jti"), str)
        or not isinstance(claims.get("exp"), int)
    ):
        raise MandateError("The stem server answered with a mandate for something else.")
    return {"key": key, "mandate": token, "id": claims["jti"], "expires": claims["exp"]}


def collect(where: Services, voice_dir: Path, voice: str) -> dict:
    """Look whether the person has answered. Returns the state.

    ``answer`` is added when this call settled the request: ``approved``,
    ``denied`` or ``expired``.
    """
    wallet = load_wallet(voice_dir, where, voice)
    request = wallet.get("request")
    if not isinstance(request, dict):
        return state(wallet)
    answer, signed, refused = "expired", None, None
    if request.get("expires", 0) > time.time():
        status, body = send(
            "POST", f"{where.stem}/api/auth/mandates/collect", {"request_id": request["id"]}
        )
        answer = body.get("status")
        if status != 200 or answer not in ("pending", "approved", "denied", "expired"):
            raise Unreachable("The stem server gave no usable answer.")
        if answer == "pending":
            return state(wallet)
        if answer == "approved":
            try:
                signed = _accept(body.get("mandate"), request["key"], where, voice)
            except MandateError as error:
                refused = error

    def settle(wallet: dict) -> None:
        # Only the request that was asked about, not one made in the meantime.
        if (wallet.get("request") or {}).get("id") != request["id"]:
            return
        del wallet["request"]
        if signed:
            wallet["signed"] = signed

    wallet = _change(voice_dir, where, voice, settle)
    if refused:
        raise refused
    return {**state(wallet), "answer": answer}


# ── Listing receipts ─────────────────────────────────────────────────────────


def listing(receipt: dict) -> dict:
    """What the registry gets to know about a file.

    Hashes and marks only. The text stays out, and so does its hash: a short
    sentence can be guessed from one.
    """
    listed = {
        "version": 1,
        "created": receipt["created"],
        "model": receipt["model"],
        "audio": receipt["audio"],
        "watermark": receipt["watermark"],
        "signer": receipt["signer"],
    }
    enrolment = (receipt.get("voice") or {}).get("enrolment")
    if enrolment:
        listed["enrolment"] = enrolment
    return listed


def listing_url(registry: str, voice: str, receipt_id: str) -> str:
    """Where a receipt is put on the list. Only a real UUID may name one."""
    return f"{registry}/voices/{voice}/receipts/{uuid.UUID(receipt_id)}"


def list_receipt(where: Services, voice: str, signed: dict, receipt: dict) -> str:
    """Put one receipt on the registry's list.

    Returns ``listed``, ``later`` (try again), ``taken`` (the id is on the list
    with other details), ``refused`` (the registry will not take this one) or,
    when the mandate is over, the reason stem gives for that. Only a refusal that
    is about this receipt counts as ``refused``.
    """
    try:
        url = listing_url(where.registry, voice, str(receipt.get("id")))
        body = listing(receipt)
    except (KeyError, TypeError, ValueError):
        return "refused"
    headers = {
        "authorization": f"Mandate {signed['mandate']}",
        "mandate-pop": proof(signed["key"], signed["mandate"], "PUT", url),
    }
    try:
        status, answer = send("PUT", url, body, headers)
    except Unreachable:
        return "later"
    if status in (200, 201):  # 200: this install listed it before
        return "listed"
    if status == 409:
        # Listed with other details, so not by this install: the first listing of an id keeps it.
        print(
            f"Receipt {receipt['id']} is NOT listed: its id is on the registry's list with other "
            f"details, put there by someone else. See {where.registry}/r/{receipt['id']}"
        )
        return "taken"
    reason = answer.get("reason") if status in (401, 403) else None
    if reason in ENDED:
        return reason
    if reason in NOT_NOW:
        print(
            f"The registry did not take the proof for receipt {receipt['id']} ({reason}). "
            "It stays in the outbox. If this keeps happening, check this machine's clock."
        )
        return "later"
    if status == 429 or status >= 500:
        return "later"
    print(f"Registry refused receipt {receipt['id']} ({status})")
    return "refused"


class Outbox:
    """Receipts that still have to reach the registry.

    Listing must never hold up or fail a generation, and the machine may be
    offline. So each receipt is noted here first and sent in the background.
    Whatever could not be sent is tried again with the next one and at startup.
    """

    def __init__(self, data_dir: Path) -> None:
        self.folder = data_dir / "outbox"
        self.voices_dir = data_dir / "voices"
        self.receipts_dir = data_dir / "receipts"
        self._lock = threading.Lock()

    def add(self, receipt_id: str, voice_id: str) -> None:
        self.folder.mkdir(parents=True, exist_ok=True)
        name = str(uuid.UUID(receipt_id))
        # Swapped in whole: a send that runs right now never sees half a note.
        draft = self.folder / f"{name}.{uuid.uuid4().hex}.tmp"
        draft.write_text(json.dumps({"voice_id": voice_id}))
        os.replace(draft, self.folder / f"{name}.json")

    def waiting(self) -> list[Path]:
        return sorted(self.folder.glob("*.json"), key=lambda path: path.stat().st_mtime)

    def send(self, where: Services) -> None:
        """Send the waiting receipts, oldest first, until one has to wait."""
        with self._lock:
            for note in self.waiting():
                if self._send_one(where, note) == "later":
                    # The registry is away or not taking proofs: the rest would fare the same.
                    break
                note.unlink(missing_ok=True)

    def send_in_background(self, where: Services) -> None:
        threading.Thread(target=self.send, args=(where,), daemon=True).start()

    def _send_one(self, where: Services, note: Path) -> str:
        try:
            voice_dir = self.voices_dir / str(json.loads(note.read_text())["voice_id"])
            receipt = json.loads((self.receipts_dir / note.name).read_text())
        except FileNotFoundError:
            return "refused"
        except OSError:
            # Could not be read just now, which says nothing about the receipt.
            return "later"
        except (ValueError, KeyError, TypeError):
            return "refused"
        # Only for the voice the file was made with, and only while its mandate stands.
        voice = clip_hash(voice_dir) if voice_dir.parent == self.voices_dir else None
        if voice is None or not isinstance(receipt, dict):
            return "refused"
        if receipt.get("registry") != where.registry:
            return "refused"
        signed = standing(load_wallet(voice_dir, where, voice))
        if signed is None:
            return "refused"
        result = list_receipt(where, voice, signed, receipt)
        if result == "taken":
            # Noted with the receipt, so `omnisuite verify` can say it later.
            draft = self.receipts_dir / f"{note.stem}.{uuid.uuid4().hex}.tmp"
            draft.write_text(json.dumps({**receipt, "listing": "taken"}, indent=2))
            os.replace(draft, self.receipts_dir / note.name)
        if result in ENDED:

            def end(wallet: dict) -> None:
                # Only the mandate that was refused, not one signed in the meantime.
                if (wallet.get("signed") or {}).get("id") == signed["id"]:
                    wallet["signed"]["ended"] = result

            _change(voice_dir, where, voice, end)
        return result
