"""Voice mandates, against a stand-in for the stem server and the registry."""

import base64
import hashlib
import json
import os
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import numpy as np
import pytest
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)

import app as server
import mandate
import receipts
from conftest import FakeWatermark
from test_enrolment import finish, start, studio, wav  # noqa: F401  (studio is a fixture)

VOICE = "ab" * 32


def b64u_decode(text):
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def read_jwt(token, x=None):
    """Header and claims of a JWT. Checks the signature against ``x``, or the key in its header."""
    head, body, signature = token.split(".")
    header = json.loads(b64u_decode(head))
    key = Ed25519PublicKey.from_public_bytes(b64u_decode(x or header["jwk"]["x"]))
    key.verify(b64u_decode(signature), f"{head}.{body}".encode())
    return header, json.loads(b64u_decode(body))


# ── The stand-in ─────────────────────────────────────────────────────────────


class Refused(Exception):
    def __init__(self, reason):
        super().__init__(reason)
        self.reason = reason


class Stand:
    """A stem server and a registry, as far as OmniSuite can tell.

    Checks what the real ones check: signatures, the request's shape, the proof
    of possession, the rights and the stop button.
    """

    def __init__(self):
        self.key = mandate.new_key()  # stem's own signing key
        self.requests = {}
        self.listed = {}
        self.stopped = set()
        self.proofs_seen = set()
        self.calls = []
        self.registry_down = False
        self.stem_answer = None  # when set: (status, headers, body) for every stem call
        self.servers = [self._serve(self.stem_call), self._serve(self.registry_call)]
        self.stem, self.registry = (
            f"http://127.0.0.1:{s.server_address[1]}" for s in self.servers
        )
        self.where = mandate.Services(stem=self.stem, registry=self.registry)

    def _serve(self, answer):
        stand = self

        class Handler(BaseHTTPRequestHandler):
            def handle_call(self):
                length = int(self.headers.get("content-length") or 0)
                raw = self.rfile.read(length)
                stand.calls.append((self.command, self.path))
                status, headers, body = answer(self.command, self.path, self.headers, raw)
                payload = json.dumps(body).encode()
                self.send_response(status)
                for name, value in {"content-type": "application/json", **headers}.items():
                    self.send_header(name, value)
                self.send_header("content-length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

            do_GET = do_POST = do_PUT = handle_call

            def log_message(self, *args):
                pass

        httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(
            target=httpd.serve_forever, kwargs={"poll_interval": 0.02}, daemon=True
        ).start()
        return httpd

    def close(self):
        for httpd in self.servers:
            httpd.shutdown()
            httpd.server_close()

    # stem

    def stem_call(self, method, path, headers, raw):
        if self.stem_answer:
            return self.stem_answer
        body = json.loads(raw)
        if (method, path) == ("POST", "/api/auth/mandates/request"):
            try:
                header, terms = read_jwt(body["request"])
            except (InvalidSignature, KeyError, ValueError):
                return 400, {}, {"message": "request signature"}
            right = terms["authorization_details"][0]
            if (
                header["typ"] != "mandate-request+jwt"
                or header["alg"] != "EdDSA"
                or "d" in header["jwk"]
                or abs(time.time() - terms["iat"]) > 300
                or right["locations"] != [self.registry]
                or right["actions"] != ["speak"]
                or not 0 < len(terms["purpose"]) <= 200
                or not 60 <= terms["ttl"] <= 30 * 24 * 3600
            ):
                return 400, {}, {"message": "bad request"}
            request_id = uuid.uuid4().hex
            self.requests[request_id] = {"jwk": header["jwk"], "terms": terms, "status": "pending"}
            return 200, {}, {
                "request_id": request_id,
                "user_code": "WXYZ-2345",
                "approve_url": f"{self.stem}/mandates/approve?request={request_id}",
                "expires_in": 600,
                "interval": 3,
            }
        if (method, path) == ("POST", "/api/auth/mandates/collect"):
            request = self.requests.get(body.get("request_id"))
            if request is None:
                return 200, {}, {"status": "expired"}
            if request["status"] == "approved":
                return 200, {}, {"status": "approved", "mandate": request["mandate"]}
            return 200, {}, {"status": request["status"]}
        return 404, {}, {}

    def approve(self, request_id=None, **changes):
        """The person signs. ``changes`` lets a test hand out a mandate that was not asked for."""
        request_id = request_id or list(self.requests)[-1]
        request = self.requests[request_id]
        now = int(time.time())
        claims = {
            "iss": self.stem,
            "sub": "person-1",
            "jti": str(uuid.uuid4()),
            "iat": now,
            "exp": now + request["terms"]["ttl"],
            "cnf": {"jwk": request["jwk"]},
            "authorization_details": request["terms"]["authorization_details"],
            "del_depth": 0,
            "del_max_depth": 0,
            "purpose": request["terms"]["purpose"],
            **changes,
        }
        request["mandate"] = mandate.sign_jwt(self.key, {"typ": "mandate+jwt"}, claims)
        request["status"] = "approved"
        return claims

    def deny(self):
        self.requests[list(self.requests)[-1]]["status"] = "denied"

    # registry

    def registry_call(self, method, path, headers, raw):
        if self.registry_down:
            return 503, {}, {}
        try:
            claims = self.authorize(method, path, headers)
        except Refused as refusal:
            return 403, {}, {"error": "Not allowed.", "reason": refusal.reason}
        if path in self.listed:
            return 409, {}, {"error": "Already listed."}
        self.listed[path] = {"body": json.loads(raw), "mandate": claims["jti"]}
        return 201, {}, {"id": path.rsplit("/", 1)[-1]}

    def authorize(self, method, path, headers):
        scheme, _, token = (headers.get("authorization") or "").partition(" ")
        if scheme != "Mandate" or "~" in token:
            raise Refused("invalid_chain")
        try:
            _, claims = read_jwt(token, self.key["x"])
        except (InvalidSignature, ValueError):
            raise Refused("invalid_chain") from None
        try:
            header, pop = read_jwt(headers.get("mandate-pop") or "", claims["cnf"]["jwk"]["x"])
        except (InvalidSignature, ValueError):
            raise Refused("invalid_pop") from None
        if (
            header["typ"] != "mandate-pop+jwt"
            or pop["htm"] != method
            or pop["htu"] != f"{self.registry}{path.split('?')[0]}"
            or pop["ath"] != mandate._b64u(hashlib.sha256(token.encode()).digest())
            or abs(time.time() - pop["iat"]) > 60
            or not 16 <= len(pop["jti"]) <= 128
        ):
            raise Refused("invalid_pop")
        right = claims["authorization_details"][0]
        if (
            method != "PUT"
            or right["locations"] != [self.registry]
            or "speak" not in right["actions"]
            or not path.lstrip("/").startswith(right["path_prefix"])
        ):
            raise Refused("outside_mandate")
        if claims["jti"] in self.stopped:
            raise Refused("revoked")
        if claims["exp"] <= time.time():
            raise Refused("expired")
        if pop["jti"] in self.proofs_seen:
            raise Refused("replayed")
        self.proofs_seen.add(pop["jti"])
        return claims


@pytest.fixture
def stand(monkeypatch):
    # The stand-in runs on this machine: never by way of a proxy.
    monkeypatch.setenv("NO_PROXY", "127.0.0.1")
    monkeypatch.setenv("no_proxy", "127.0.0.1")
    stand = Stand()
    yield stand
    stand.close()


@pytest.fixture
def voice_dir(tmp_path):
    folder = tmp_path / "data" / "voices" / "ada"
    folder.mkdir(parents=True)
    (folder / "ref.wav").write_bytes(wav(4.0))
    return folder


def signed_voice(stand, voice_dir):
    """A voice whose owner has signed. Returns its name outside this machine."""
    voice = mandate.clip_hash(voice_dir)
    mandate.ask(stand.where, voice_dir, voice, "Ada")
    stand.approve()
    assert mandate.collect(stand.where, voice_dir, voice)["answer"] == "approved"
    return voice


def receipt_for(data_dir, registry, **changes):
    """A receipt on disk, like Marker.mark leaves one."""
    receipt = {
        "version": 1,
        "id": str(uuid.uuid4()),
        "created": "2026-11-27T22:00:00+00:00",
        "model": "k2-fsa/OmniVoice",
        "text_sha256": hashlib.sha256(b"Hello.").hexdigest(),
        "audio": {"sample_rate": 24000, "seconds": 1.0, "sha256": "cd" * 32},
        "watermark": {"scheme": "audioseal_wm_16bits", "tag": "beef"},
        "signer": {"name": "OmniSuite install 12345678", "serial": "42"},
        "voice": {"id": "ada", "enrolment": "read-aloud"},
        "registry": registry,
        **changes,
    }
    (data_dir / "receipts").mkdir(exist_ok=True)
    (data_dir / "receipts" / f"{receipt['id']}.json").write_text(json.dumps(receipt))
    return receipt


# ── Where to ask ─────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "url, expected",
    [
        ("https://id.example.com", "https://id.example.com"),
        ("https://ID.Example.com:443/", "https://id.example.com"),
        (" https://id.example.com:8443 ", "https://id.example.com:8443"),
        ("http://127.0.0.1:8787", "http://127.0.0.1:8787"),
        ("http://localhost", "http://localhost"),
        ("https://[::1]:8443", "https://[::1]:8443"),
        # In the clear across the network: no.
        ("http://id.example.com", None),
        ("https://id.example.com/auth", None),
        ("https://id.example.com/?x=1", None),
        ("https://user:secret@id.example.com", None),
        ("https://id.example.com:port", None),
        ("ftp://id.example.com", None),
        ("id.example.com", None),
        ("", None),
    ],
)
def test_only_an_https_origin_is_called(url, expected):
    assert mandate.origin(url) == expected


def test_mandates_are_off_until_both_servers_are_named(capsys):
    assert mandate.services({}) is None
    assert capsys.readouterr().out == ""
    both = {mandate.STEM_ENV: "https://id.example.com/", mandate.REGISTRY_ENV: "https://list.example.com"}
    assert mandate.services(both) == mandate.Services("https://id.example.com", "https://list.example.com")
    # Half set up, or set up wrongly: off, and the console says why.
    assert mandate.services({mandate.STEM_ENV: "https://id.example.com"}) is None
    assert mandate.services({**both, mandate.REGISTRY_ENV: "http://list.example.com"}) is None
    assert capsys.readouterr().out.count("Voice mandates stay off") == 2


# ── Signed tokens ────────────────────────────────────────────────────────────


def test_the_request_is_signed_by_the_key_it_names():
    key = mandate.new_key()
    token = mandate.request_jwt(key, "https://list.example.com", VOICE, "Ada")
    header, claims = read_jwt(token)
    assert header == {"alg": "EdDSA", "typ": "mandate-request+jwt", "jwk": mandate.public_jwk(key)}
    assert "d" not in header["jwk"]
    assert claims["authorization_details"] == [
        {
            "type": "stem_mandate",
            "locations": ["https://list.example.com"],
            "actions": ["speak"],
            "path_prefix": f"voices/{VOICE}/",
        }
    ]
    assert claims["purpose"] == 'Speak as "Ada" with OmniSuite'
    assert claims["ttl"] == 30 * 24 * 3600
    assert claims["del_max_depth"] == 0
    assert abs(claims["iat"] - time.time()) < 5
    # Not signed by anyone else.
    with pytest.raises(InvalidSignature):
        read_jwt(token, mandate.new_key()["x"])


def test_the_purpose_stays_one_readable_line():
    key = mandate.new_key()
    token = mandate.request_jwt(key, "https://list.example.com", VOICE, "A\nd\x00a " + "x" * 300)
    purpose = read_jwt(token)[1]["purpose"]
    assert purpose.startswith('Speak as "Ada xxx')
    assert len(purpose) <= 200 and purpose.isprintable()


def test_a_proof_is_for_one_call():
    key = mandate.new_key()
    url = "https://list.example.com/voices/abc/receipts/1?x=1"
    first = read_jwt(mandate.proof(key, "the.token.itself", "put", url), key["x"])
    second = read_jwt(mandate.proof(key, "the.token.itself", "put", url), key["x"])
    header, claims = first
    assert header == {"alg": "EdDSA", "typ": "mandate-pop+jwt"}
    assert claims["htm"] == "PUT"
    assert claims["htu"] == "https://list.example.com/voices/abc/receipts/1"
    assert claims["ath"] == mandate._b64u(hashlib.sha256(b"the.token.itself").digest())
    assert claims["jti"] != second[1]["jti"]


# ── Asking and collecting ────────────────────────────────────────────────────


def test_asking_shows_where_to_sign_and_keeps_the_key_to_itself(stand, voice_dir):
    voice = mandate.clip_hash(voice_dir)
    shown = mandate.ask(stand.where, voice_dir, voice, "Ada")
    assert shown["state"] == "waiting" and shown["was"] == "none"
    assert shown["approve_url"].startswith(f"{stand.stem}/mandates/approve?request=")
    assert shown["user_code"] == "WXYZ-2345"
    assert 590 < shown["expires_in"] <= 600

    wallet_file = voice_dir / mandate.WALLET_FILE
    wallet = json.loads(wallet_file.read_text())
    assert wallet["request"]["key"]["d"]
    if os.name != "nt":
        assert wallet_file.stat().st_mode & 0o777 == 0o600
    assert [p.name for p in voice_dir.iterdir() if p.name.endswith(".tmp")] == []
    # Nothing that could sign leaves through the state.
    assert wallet["request"]["key"]["d"] not in json.dumps(shown)

    assert mandate.collect(stand.where, voice_dir, voice)["state"] == "waiting"


def test_the_signed_mandate_is_kept_until_it_runs_out(stand, voice_dir):
    voice = mandate.clip_hash(voice_dir)
    mandate.ask(stand.where, voice_dir, voice, "Ada")
    claims = stand.approve()
    assert claims["purpose"] == 'Speak as "Ada" with OmniSuite'

    shown = mandate.collect(stand.where, voice_dir, voice)
    assert shown["state"] == "signed" and shown["answer"] == "approved"
    assert shown["until"].startswith(time.strftime("%Y-", time.gmtime(claims["exp"])))
    wallet = mandate.load_wallet(voice_dir, stand.where, voice)
    assert "request" not in wallet
    assert wallet["signed"]["id"] == claims["jti"]
    assert wallet["signed"]["mandate"] not in json.dumps(shown)
    assert mandate.standing(wallet) is not None
    # Asked again without a request open: nothing to collect, no call made.
    calls = len(stand.calls)
    assert mandate.collect(stand.where, voice_dir, voice) == {"state": "signed", "until": shown["until"]}
    assert len(stand.calls) == calls

    after = claims["exp"] + 1
    assert mandate.standing(wallet, now=after) is None
    assert mandate.state(wallet, now=after) == {
        "state": "ended",
        "until": shown["until"],
        "reason": "expired",
    }


def test_a_no_or_no_answer_ends_the_request(stand, voice_dir):
    voice = mandate.clip_hash(voice_dir)
    mandate.ask(stand.where, voice_dir, voice, "Ada")
    stand.deny()
    assert mandate.collect(stand.where, voice_dir, voice) == {"state": "none", "answer": "denied"}

    mandate.ask(stand.where, voice_dir, voice, "Ada")
    stand.requests.clear()  # stem forgot it: too late
    assert mandate.collect(stand.where, voice_dir, voice) == {"state": "none", "answer": "expired"}

    # A request that ran out here is not asked about any more.
    mandate.ask(stand.where, voice_dir, voice, "Ada")
    wallet = json.loads((voice_dir / mandate.WALLET_FILE).read_text())
    wallet["request"]["expires"] = int(time.time()) - 1
    mandate.save_wallet(voice_dir, wallet)
    calls = len(stand.calls)
    assert mandate.collect(stand.where, voice_dir, voice)["answer"] == "expired"
    assert len(stand.calls) == calls


def test_renewing_does_not_end_the_mandate_that_still_runs(stand, voice_dir):
    voice = signed_voice(stand, voice_dir)
    first = mandate.load_wallet(voice_dir, stand.where, voice)["signed"]["id"]

    shown = mandate.ask(stand.where, voice_dir, voice, "Ada")
    assert shown["state"] == "waiting" and shown["was"] == "signed"
    wallet = mandate.load_wallet(voice_dir, stand.where, voice)
    assert mandate.standing(wallet)["id"] == first

    stand.approve()
    mandate.collect(stand.where, voice_dir, voice)
    second = mandate.load_wallet(voice_dir, stand.where, voice)["signed"]
    assert second["id"] != first
    assert second["key"]["x"] != wallet["signed"]["key"]["x"]


@pytest.mark.parametrize(
    "changes",
    [
        {"cnf": {"jwk": mandate.public_jwk(mandate.new_key())}},
        {"authorization_details": mandate.rights("https://elsewhere.example.com", VOICE)},
        {"authorization_details": mandate.rights("http://127.0.0.1:1", "f" * 64)},
        {"exp": "tomorrow"},
        {"jti": None},
    ],
)
def test_a_mandate_for_something_else_is_not_kept(stand, voice_dir, changes):
    voice = mandate.clip_hash(voice_dir)
    mandate.ask(stand.where, voice_dir, voice, "Ada")
    stand.approve(**changes)
    with pytest.raises(mandate.MandateError, match="something else"):
        mandate.collect(stand.where, voice_dir, voice)
    assert mandate.state(mandate.load_wallet(voice_dir, stand.where, voice)) == {"state": "none"}


def test_the_link_to_sign_has_to_lead_to_the_stem_server(stand, voice_dir, capsys):
    voice = mandate.clip_hash(voice_dir)
    for link in ("https://elsewhere.example.com/mandates/approve", "javascript:alert(1)", f"{stand.stem}.evil.example/x"):
        stand.stem_answer = (200, {}, {"request_id": "r", "user_code": "c", "approve_url": link})
        with pytest.raises(mandate.MandateError, match="turned the request down"):
            mandate.ask(stand.where, voice_dir, voice, "Ada")
    assert not (voice_dir / mandate.WALLET_FILE).exists()

    stand.stem_answer = (400, {}, {"message": "https://list.example.com doesn't take mandates"})
    with pytest.raises(mandate.MandateError, match="turned the request down"):
        mandate.ask(stand.where, voice_dir, voice, "Ada")
    assert "doesn't take mandates" in capsys.readouterr().out
    stand.stem_answer = (404, {}, {})
    with pytest.raises(mandate.MandateError, match="does not offer mandates"):
        mandate.ask(stand.where, voice_dir, voice, "Ada")


def test_being_sent_elsewhere_is_an_error_not_a_detour(stand, voice_dir):
    voice = mandate.clip_hash(voice_dir)
    stand.stem_answer = (302, {"location": f"{stand.registry}/caught"}, {})
    with pytest.raises(mandate.MandateError):
        mandate.ask(stand.where, voice_dir, voice, "Ada")
    assert all(path != "/caught" for _, path in stand.calls)


def test_a_server_that_is_not_there(stand, voice_dir):
    nowhere = mandate.Services(stem="http://127.0.0.1:9", registry=stand.registry)
    with pytest.raises(mandate.Unreachable, match="127.0.0.1:9 did not answer"):
        mandate.ask(nowhere, voice_dir, mandate.clip_hash(voice_dir), "Ada")


def test_a_wallet_is_for_one_clip_and_one_pair_of_servers(stand, voice_dir):
    voice = signed_voice(stand, voice_dir)
    assert mandate.standing(mandate.load_wallet(voice_dir, stand.where, voice))

    moved = mandate.Services(stem=stand.stem, registry="https://other.example.com")
    assert mandate.state(mandate.load_wallet(voice_dir, moved, voice)) == {"state": "none"}

    (voice_dir / "ref.wav").write_bytes(wav(5.0))
    swapped = mandate.clip_hash(voice_dir)
    assert swapped != voice
    assert mandate.state(mandate.load_wallet(voice_dir, stand.where, swapped)) == {"state": "none"}

    (voice_dir / mandate.WALLET_FILE).write_text("not json")
    assert mandate.state(mandate.load_wallet(voice_dir, stand.where, voice)) == {"state": "none"}


# ── Listing receipts ─────────────────────────────────────────────────────────


def test_a_listing_holds_hashes_and_marks_only():
    receipt = {
        "id": str(uuid.uuid4()),
        "created": "2026-11-27T22:00:00+00:00",
        "model": "k2-fsa/OmniVoice",
        "text_sha256": "ee" * 32,
        "audio": {"sample_rate": 24000, "seconds": 1.0, "sha256": "cd" * 32},
        "watermark": {"scheme": "audioseal_wm_16bits", "tag": "beef"},
        "signer": {"name": "OmniSuite install 12345678", "serial": "42"},
        "voice": {"id": "a-local-voice-id", "enrolment": "read-aloud"},
    }
    listed = mandate.listing(receipt)
    assert sorted(listed) == ["audio", "created", "enrolment", "model", "signer", "version", "watermark"]
    # Not the text, not its hash (a short sentence can be guessed), not the local voice id.
    assert "ee" * 32 not in json.dumps(listed)
    assert "a-local-voice-id" not in json.dumps(listed)


def test_receipts_reach_the_registry_while_the_mandate_stands(stand, voice_dir):
    data_dir = voice_dir.parent.parent
    voice = signed_voice(stand, voice_dir)
    outbox = mandate.Outbox(data_dir)
    receipt = receipt_for(data_dir, stand.registry)
    outbox.add(receipt["id"], "ada")

    outbox.send(stand.where)
    assert outbox.waiting() == []
    listed = stand.listed[f"/voices/{voice}/receipts/{receipt['id']}"]
    assert listed["body"] == mandate.listing(receipt)
    assert listed["mandate"] == mandate.load_wallet(voice_dir, stand.where, voice)["signed"]["id"]

    # Sent twice (say the answer got lost): the registry has it, that is fine.
    outbox.add(receipt["id"], "ada")
    outbox.send(stand.where)
    assert outbox.waiting() == [] and len(stand.listed) == 1


def test_receipts_wait_while_the_registry_is_away(stand, voice_dir):
    data_dir = voice_dir.parent.parent
    signed_voice(stand, voice_dir)
    outbox = mandate.Outbox(data_dir)
    first, second = receipt_for(data_dir, stand.registry), receipt_for(data_dir, stand.registry)

    stand.registry_down = True
    outbox.add(first["id"], "ada")
    outbox.send(stand.where)
    assert len(outbox.waiting()) == 1 and stand.listed == {}

    stand.registry_down = False
    outbox.add(second["id"], "ada")
    outbox.send(stand.where)
    assert outbox.waiting() == []
    assert len(stand.listed) == 2

    # Nobody at that address at all, as on a machine that is offline.
    stand.servers[1].shutdown()
    stand.servers[1].server_close()
    outbox.add(receipt_for(data_dir, stand.registry)["id"], "ada")
    outbox.send(stand.where)
    assert len(outbox.waiting()) == 1


def test_a_stop_at_stem_ends_the_listing(stand, voice_dir):
    data_dir = voice_dir.parent.parent
    voice = signed_voice(stand, voice_dir)
    wallet = mandate.load_wallet(voice_dir, stand.where, voice)
    stand.stopped.add(wallet["signed"]["id"])
    outbox = mandate.Outbox(data_dir)
    for _ in range(3):
        outbox.add(receipt_for(data_dir, stand.registry)["id"], "ada")

    calls = len(stand.calls)
    outbox.send(stand.where)
    # The first refusal settles it: the others are not even tried.
    assert len(stand.calls) == calls + 1
    assert outbox.waiting() == [] and stand.listed == {}
    wallet = mandate.load_wallet(voice_dir, stand.where, voice)
    assert mandate.standing(wallet) is None
    shown = mandate.state(wallet)
    assert shown["state"] == "ended" and shown["reason"] == "revoked"


def test_only_receipts_of_the_signed_voice_are_listed(stand, voice_dir):
    data_dir = voice_dir.parent.parent
    voice = signed_voice(stand, voice_dir)
    outbox = mandate.Outbox(data_dir)

    # A receipt that never named this registry, a voice that is gone, a voice
    # outside the voices folder, a note without a receipt.
    outbox.add(receipt_for(data_dir, None)["id"], "ada")
    outbox.add(receipt_for(data_dir, stand.registry)["id"], "gone")
    outbox.add(receipt_for(data_dir, stand.registry)["id"], "../../data/voices/ada")
    outbox.add(str(uuid.uuid4()), "ada")
    with pytest.raises(ValueError):
        outbox.add("../../etc/passwd", "ada")
    calls = len(stand.calls)
    outbox.send(stand.where)
    assert outbox.waiting() == [] and len(stand.calls) == calls

    # The mandate is for one voice: the registry turns down any other.
    signed = mandate.load_wallet(voice_dir, stand.where, voice)["signed"]
    receipt = receipt_for(data_dir, stand.registry)
    assert mandate.list_receipt(stand.where, "f" * 64, signed, receipt) == "refused"
    assert mandate.list_receipt(stand.where, voice, signed, {**receipt, "id": "not-a-uuid"}) == "refused"
    assert mandate.list_receipt(stand.where, voice, signed, receipt) == "listed"
    assert list(stand.listed) == [f"/voices/{voice}/receipts/{receipt['id']}"]


# ── The server ───────────────────────────────────────────────────────────────


@pytest.fixture
def signing_studio(studio, stand, monkeypatch):
    http, model, data_dir = studio
    monkeypatch.setattr(server, "services", stand.where)
    monkeypatch.setattr(server, "outbox", mandate.Outbox(data_dir))
    # In the foreground, so a test sees the listing as soon as the file is back.
    monkeypatch.setattr(mandate.Outbox, "send_in_background", mandate.Outbox.send)
    return http, model, data_dir, stand


def enrol(http, model, name="Ada"):
    challenge = start(http)
    model.hears = challenge["sentence"]
    return finish(http, challenge["challenge_id"], name=name).json()


def listed_voice(http, voice_id):
    return next(v for v in http.get("/api/voices").json() if v["id"] == voice_id)


def test_without_the_two_servers_nothing_changes(studio, tmp_path):
    http, model, data_dir = studio
    assert server.services is None
    voice = enrol(http, model)
    assert "mandate" not in listed_voice(http, voice["id"])
    assert http.post(f"/api/voices/{voice['id']}/mandate").status_code == 404
    assert http.post(f"/api/voices/{voice['id']}/mandate/collect").status_code == 404

    response = http.post("/api/generate", data={"text": "Hello.", "voice_id": voice["id"]})
    assert "X-Receipt-Url" not in response.headers
    path = tmp_path / "out.wav"
    path.write_bytes(response.content)
    result = receipts.verify_file(path, data_dir, watermark=FakeWatermark())
    assert result["verdict"] == "intact" and result["registry"] is None
    assert "registry" not in receipts._describe(result)
    assert not (data_dir / "outbox").exists()


def test_only_a_voice_enrolled_by_reading_can_be_signed_for(signing_studio):
    http, _, _, stand = signing_studio
    saved = http.post(
        "/api/clone/save",
        data={"name": "Clip", "ref_text": "Reference."},
        files={"ref_audio": ("ref.wav", wav(4.0), "audio/wav")},
    ).json()
    assert "mandate" not in listed_voice(http, saved["id"])
    assert http.post(f"/api/voices/{saved['id']}/mandate").status_code == 409
    assert http.post("/api/voices/nobody/mandate").status_code == 404
    assert http.post("/api/voices/..%2F..%2Fkeys/mandate").status_code == 404
    assert stand.calls == []


def test_the_owner_signs_and_receipts_are_listed(signing_studio, tmp_path):
    http, model, data_dir, stand = signing_studio
    voice = enrol(http, model)
    assert listed_voice(http, voice["id"])["mandate"] == {"state": "none"}

    asked = http.post(f"/api/voices/{voice['id']}/mandate")
    assert asked.status_code == 200
    assert asked.json()["approve_url"].startswith(f"{stand.stem}/mandates/approve?request=")
    assert listed_voice(http, voice["id"])["mandate"]["state"] == "waiting"
    assert http.post(f"/api/voices/{voice['id']}/mandate/collect").json()["state"] == "waiting"

    # Before the owner signs, a file names no registry.
    early = http.post("/api/generate", data={"text": "Hello.", "voice_id": voice["id"]})
    assert "X-Receipt-Url" not in early.headers and stand.listed == {}

    claims = stand.approve()
    collected = http.post(f"/api/voices/{voice['id']}/mandate/collect").json()
    assert collected["state"] == "signed" and collected["answer"] == "approved"
    shown = listed_voice(http, voice["id"])
    assert shown["mandate"]["state"] == "signed"
    # The page never gets the key or the mandate itself.
    wallet = json.loads((data_dir / "voices" / voice["id"] / mandate.WALLET_FILE).read_text())
    assert wallet["signed"]["key"]["d"] not in json.dumps(shown)
    assert wallet["signed"]["mandate"] not in json.dumps(shown)

    response = http.post("/api/generate", data={"text": "Hello.", "voice_id": voice["id"]})
    receipt_id = response.headers["X-Generation-Id"]
    assert response.headers["X-Receipt-Url"] == f"{stand.registry}/r/{receipt_id}"
    clip = voice["enrolment"]["ref_sha256"]
    listed = stand.listed[f"/voices/{clip}/receipts/{receipt_id}"]
    assert listed["mandate"] == claims["jti"]
    assert listed["body"]["audio"]["sha256"] == hashlib.sha256(response.content).hexdigest()
    assert listed["body"]["enrolment"] == "read-aloud"
    assert "text_sha256" not in listed["body"]
    assert list((data_dir / "outbox").iterdir()) == []

    # The file says where its receipt is listed, and verify says so too.
    path = tmp_path / "out.wav"
    path.write_bytes(response.content)
    result = receipts.verify_file(path, data_dir, watermark=FakeWatermark(), registry=stand.registry)
    assert result["verdict"] == "intact"
    assert result["registry"] == {"origin": stand.registry, "url": f"{stand.registry}/r/{receipt_id}"}
    assert f"  registry   {stand.registry}/r/{receipt_id}" in receipts._describe(result)
    # Checked on an install that uses another registry, or none: named, not linked.
    for own in (None, "https://other.example.com"):
        result = receipts.verify_file(path, data_dir, watermark=FakeWatermark(), registry=own)
        assert result["registry"] == {"origin": stand.registry, "url": None}
        assert f"names {stand.registry}, which this install does not use" in receipts._describe(result)


def test_after_a_stop_files_name_no_registry_again(signing_studio):
    http, model, data_dir, stand = signing_studio
    voice = enrol(http, model)
    http.post(f"/api/voices/{voice['id']}/mandate")
    claims = stand.approve()
    http.post(f"/api/voices/{voice['id']}/mandate/collect")

    stand.stopped.add(claims["jti"])
    # This one still names the registry: the stop is only learnt when listing fails.
    first = http.post("/api/generate", data={"text": "Hello.", "voice_id": voice["id"]})
    assert "X-Receipt-Url" in first.headers and stand.listed == {}
    shown = listed_voice(http, voice["id"])["mandate"]
    assert shown["state"] == "ended" and shown["reason"] == "revoked"

    second = http.post("/api/generate", data={"text": "Hello.", "voice_id": voice["id"]})
    assert second.status_code == 200 and "X-Receipt-Url" not in second.headers


def test_a_registry_that_is_away_does_not_hold_up_a_generation(signing_studio):
    http, model, data_dir, stand = signing_studio
    voice = enrol(http, model)
    http.post(f"/api/voices/{voice['id']}/mandate")
    stand.approve()
    http.post(f"/api/voices/{voice['id']}/mandate/collect")

    stand.registry_down = True
    response = http.post("/api/generate", data={"text": "Hello.", "voice_id": voice["id"]})
    assert response.status_code == 200
    assert len(list((data_dir / "outbox").iterdir())) == 1
    stand.registry_down = False
    http.post("/api/generate", data={"text": "Hello again.", "voice_id": voice["id"]})
    assert list((data_dir / "outbox").iterdir()) == []
    assert len(stand.listed) == 2


def test_a_stem_server_that_is_away_is_said_plainly(signing_studio, monkeypatch):
    http, model, _, stand = signing_studio
    voice = enrol(http, model)
    monkeypatch.setattr(server, "services", mandate.Services("http://127.0.0.1:9", stand.registry))
    response = http.post(f"/api/voices/{voice['id']}/mandate")
    assert response.status_code == 502
    assert response.json() == {"error": "127.0.0.1:9 did not answer"}


def test_a_file_cannot_point_verify_at_any_address(marker, tmp_path):
    marker.load()
    audio = np.zeros(24000, dtype=np.float32)
    wav_bytes, receipt = marker.mark(audio, 24000, model="m", registry="https://list.example.com")
    assert receipt["registry"] == "https://list.example.com"
    path = tmp_path / "out.wav"
    path.write_bytes(wav_bytes)

    # On another install that uses the same registry, the link leads to that
    # registry and nowhere else. Whether the receipt is listed shows there.
    other = tmp_path / "other"
    result = receipts.verify_file(path, other, watermark=FakeWatermark(), registry="https://list.example.com")
    assert result["verdict"] == "untrusted"
    assert result["registry"]["url"] == f"https://list.example.com/r/{receipt['id']}"

    # A changed file is not believed about its registry at all.
    broken = bytearray(wav_bytes)
    broken[-10] ^= 0xFF
    path.write_bytes(bytes(broken))
    result = receipts.verify_file(path, marker.keys_dir.parent, watermark=FakeWatermark(), registry="https://list.example.com")
    assert result["verdict"] == "broken" and result["registry"] is None
