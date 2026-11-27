"""Spoken receipts: mark every generated file and check the marks later.

Every file OmniSuite writes carries two marks:

* an inaudible AudioSeal watermark with a 16-bit tag, and
* a signed C2PA manifest that declares the audio as AI-generated and names its receipt.

The manifest is the strong mark, but it is metadata and goes away when a file is
converted. The watermark sits in the sound itself and stays. A copy of each receipt
is kept in ``data/receipts`` so a file that lost its manifest can still be traced on
the machine that made it.

Run ``python receipts.py verify <file>`` to read the marks back.
"""

from __future__ import annotations

import argparse
import datetime
import hashlib
import io
import json
import os
import sys
import threading
import uuid
from dataclasses import dataclass
from pathlib import Path

import c2pa
import numpy as np
import soundfile as sf
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID

DATA_DIR = Path(__file__).parent / "data"

WATERMARK_SCHEME = "audioseal_wm_16bits"
DETECTOR_SCHEME = "audioseal_detector_16bits"
WATERMARK_RATE = 16000  # AudioSeal works on 16 kHz audio
WATERMARK_BITS = 16
WATERMARK_CHUNK = 20 * WATERMARK_RATE  # long audio is marked in pieces to bound memory
WATERMARK_FADE = WATERMARK_RATE // 2  # pieces overlap and cross-fade over this much
DETECTION_THRESHOLD = 0.5

RECEIPT_LABEL = "studio.shiftbloom.omnisuite.receipt"
# IPTC digital source types that mean "a model made this", by their last path segment.
AI_SOURCE_TYPES = ("trainedAlgorithmicMedia", "compositeWithTrainedAlgorithmicMedia")

KEY_LIFETIME = datetime.timedelta(days=3650)

# Exit codes of ``verify``. 1 is a plain error, 2 is a usage error (argparse).
EXIT_CODES = {"intact": 0, "stripped": 3, "broken": 4, "unmarked": 5, "untrusted": 6}


# ── Signing keys ─────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class SigningKeys:
    """This install's signing identity."""

    root_pem: str  # trust anchor, safe to hand to others
    chain_pem: str  # signer certificate followed by the root
    key_pem: str
    name: str  # common name on the signer certificate
    serial: str  # signer certificate serial, decimal like C2PA reports it


def _pem(cert: x509.Certificate) -> str:
    return cert.public_bytes(serialization.Encoding.PEM).decode()


def _create_signing_keys(keys_dir: Path) -> None:
    """Create a root certificate and a signer certificate for this install.

    C2PA refuses self-signed signer certificates, so the signer hangs off a root
    made for it. The root's private key is used once and never stored.
    """
    now = datetime.datetime.now(datetime.timezone.utc)
    starts, ends = now - datetime.timedelta(minutes=5), now + KEY_LIFETIME

    root_key = ec.generate_private_key(ec.SECP256R1())
    signer_key = ec.generate_private_key(ec.SECP256R1())
    root_spki = root_key.public_key().public_bytes(
        serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo
    )
    install = hashlib.sha256(root_spki).hexdigest()[:8]

    def name(common_name: str) -> x509.Name:
        return x509.Name(
            [
                x509.NameAttribute(NameOID.COMMON_NAME, common_name),
                x509.NameAttribute(NameOID.ORGANIZATION_NAME, "OmniSuite"),
            ]
        )

    def key_usage(*, signs_files: bool) -> x509.KeyUsage:
        return x509.KeyUsage(
            digital_signature=signs_files,
            key_cert_sign=not signs_files,
            crl_sign=not signs_files,
            content_commitment=False,
            key_encipherment=False,
            data_encipherment=False,
            key_agreement=False,
            encipher_only=False,
            decipher_only=False,
        )

    root_name = name(f"OmniSuite root {install}")
    root = (
        x509.CertificateBuilder()
        .subject_name(root_name)
        .issuer_name(root_name)
        .public_key(root_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(starts)
        .not_valid_after(ends)
        .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
        .add_extension(key_usage(signs_files=False), critical=True)
        .add_extension(
            x509.SubjectKeyIdentifier.from_public_key(root_key.public_key()),
            critical=False,
        )
        .sign(root_key, hashes.SHA256())
    )
    signer = (
        x509.CertificateBuilder()
        .subject_name(name(f"OmniSuite install {install}"))
        .issuer_name(root_name)
        .public_key(signer_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(starts)
        .not_valid_after(ends)
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .add_extension(key_usage(signs_files=True), critical=True)
        .add_extension(
            x509.ExtendedKeyUsage([ExtendedKeyUsageOID.EMAIL_PROTECTION]),
            critical=False,
        )
        .add_extension(
            x509.SubjectKeyIdentifier.from_public_key(signer_key.public_key()),
            critical=False,
        )
        .add_extension(
            x509.AuthorityKeyIdentifier.from_issuer_public_key(root_key.public_key()),
            critical=False,
        )
        .sign(root_key, hashes.SHA256())
    )

    keys_dir.mkdir(parents=True, exist_ok=True)
    key_pem = signer_key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    )
    # Owner-only from the first byte, not chmod after the fact.
    fd = os.open(keys_dir / "signer.key", os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "wb") as key_file:
        key_file.write(key_pem)
    (keys_dir / "signer.pem").write_text(_pem(signer))
    (keys_dir / "root.pem").write_text(_pem(root))


def load_signing_keys(keys_dir: Path) -> SigningKeys:
    """Load this install's signing keys, creating them on first use."""
    paths = [keys_dir / n for n in ("root.pem", "signer.pem", "signer.key")]
    present = [p.exists() for p in paths]
    if not any(present):
        _create_signing_keys(keys_dir)
    elif not all(present):
        raise RuntimeError(
            f"The signing keys in {keys_dir} are incomplete. Restore the missing "
            "files. Removing the folder creates new keys, and files signed with "
            "the old ones will then show an unknown signer."
        )

    root_pem, signer_pem, key_pem = (p.read_text() for p in paths)
    signer = x509.load_pem_x509_certificate(signer_pem.encode())
    common_name = signer.subject.get_attributes_for_oid(NameOID.COMMON_NAME)[0].value
    return SigningKeys(
        root_pem=root_pem,
        chain_pem=signer_pem + root_pem,
        key_pem=key_pem,
        name=str(common_name),
        serial=str(signer.serial_number),
    )


# ── Watermark ────────────────────────────────────────────────────────────────


def tag_for(receipt_id: str) -> int:
    """The 16-bit watermark tag that belongs to a receipt."""
    return int.from_bytes(hashlib.sha256(receipt_id.encode()).digest()[:2], "big")


def format_tag(tag: int) -> str:
    return f"{tag:04x}"


class AudioSealWatermark:
    """AudioSeal generator and detector, loaded on first use.

    Both run on the CPU: they are small, and it keeps the mark identical across
    machines. The weights are downloaded once into the AudioSeal cache.
    """

    def __init__(self) -> None:
        self._generator = None
        self._detector = None
        # One call at a time: the oneDNN switch in _run is process-wide.
        self._lock = threading.RLock()

    @staticmethod
    def _audioseal():
        # AudioSeal wraps parts of its network in torch.compile, which needs a C
        # compiler on the machine. Plain execution is fast enough for this.
        os.environ.setdefault("NO_TORCH_COMPILE", "1")
        from audioseal import AudioSeal

        return AudioSeal

    def load(self) -> None:
        """Load the generator, downloading its weights on the first run."""
        with self._lock:
            if self._generator is None:
                generator = self._audioseal().load_generator(WATERMARK_SCHEME)
                generator.eval()
                self._generator = generator

    def _load_detector(self) -> None:
        with self._lock:
            if self._detector is None:
                detector = self._audioseal().load_detector(DETECTOR_SCHEME)
                detector.eval()
                self._detector = detector

    def _run(self, function):
        import torch

        # oneDNN can take most of a minute on AudioSeal's wide transposed
        # convolution for some input lengths. PyTorch's own kernels take milliseconds.
        with self._lock, torch.no_grad(), torch.backends.mkldnn.flags(enabled=False):
            return function()

    def embed(self, audio: np.ndarray, sample_rate: int, tag: int) -> np.ndarray:
        """Add the watermark to ``audio`` of shape (channels, samples)."""
        import torch
        import torchaudio.functional as F

        self.load()
        wav = torch.from_numpy(np.ascontiguousarray(audio, dtype=np.float32))
        bits = torch.tensor(
            [[(tag >> (WATERMARK_BITS - 1 - i)) & 1 for i in range(WATERMARK_BITS)]]
        ).repeat(wav.shape[0], 1)

        def make_mark():
            low = F.resample(wav, sample_rate, WATERMARK_RATE)
            mark = torch.zeros_like(low)
            for start in range(0, low.shape[-1], WATERMARK_CHUNK - WATERMARK_FADE):
                piece = low[:, None, start : start + WATERMARK_CHUNK]
                part = self._generator.get_watermark(piece, WATERMARK_RATE, message=bits)
                part = part.squeeze(1)
                if start > 0:
                    fade = torch.linspace(0.0, 1.0, WATERMARK_FADE)[: part.shape[-1]]
                    part[:, : fade.numel()] *= fade
                    mark[:, start : start + fade.numel()] *= 1.0 - fade
                mark[:, start : start + part.shape[-1]] += part
                if start + WATERMARK_CHUNK >= low.shape[-1]:
                    break
            return F.resample(mark, WATERMARK_RATE, sample_rate)

        mark = self._run(make_mark)
        # Resampling there and back can be off by a sample or two.
        samples = wav.shape[-1]
        mark = torch.nn.functional.pad(mark, (0, max(0, samples - mark.shape[-1])))
        return (wav + mark[..., :samples]).clamp(-1.0, 1.0).numpy()

    def detect(self, audio: np.ndarray, sample_rate: int) -> tuple[float, int]:
        """Return (share of the audio that carries the watermark, decoded tag)."""
        import torch
        import torchaudio.functional as F

        self._load_detector()
        mono = np.ascontiguousarray(audio, dtype=np.float32).mean(axis=0)

        def read_mark():
            low = F.resample(torch.from_numpy(mono), sample_rate, WATERMARK_RATE)
            marked_samples = 0.0
            bit_votes = torch.zeros(WATERMARK_BITS)
            for start in range(0, low.shape[-1], WATERMARK_CHUNK):
                piece = low[None, None, start : start + WATERMARK_CHUNK]
                # Per sample: probability of a watermark. Per piece: probability of each bit.
                presence, bit_probabilities = self._detector(piece, WATERMARK_RATE)
                marked_samples += float((presence[0, 1] > 0.5).sum())
                bit_votes += bit_probabilities[0] * piece.shape[-1]
            total = max(1, low.shape[-1])
            return marked_samples / total, bit_votes / total

        score, bit_probabilities = self._run(read_mark)
        tag = 0
        for probability in bit_probabilities.tolist():
            tag = (tag << 1) | int(probability > 0.5)
        return score, tag


# ── Marking ──────────────────────────────────────────────────────────────────


class Marker:
    """Marks generated audio and keeps the receipts."""

    def __init__(self, data_dir: Path, watermark=None) -> None:
        self.keys_dir = data_dir / "keys"
        self.receipts_dir = data_dir / "receipts"
        self._watermark = watermark or AudioSealWatermark()
        self._keys: SigningKeys | None = None
        self._lock = threading.Lock()

    def load(self) -> SigningKeys:
        """Load the watermark model and the signing keys. Safe to call twice."""
        with self._lock:
            if self._keys is None:
                self._watermark.load()
                self._keys = load_signing_keys(self.keys_dir)
            return self._keys

    def mark(
        self, audio: np.ndarray, sample_rate: int, *, model: str, text: str = ""
    ) -> tuple[bytes, dict]:
        """Watermark and sign ``audio``. Returns the WAV file and its receipt.

        ``audio`` is float audio of shape (samples,) or (channels, samples).
        There is no unmarked fallback: if a mark cannot be made, this raises.
        """
        keys = self.load()
        receipt_id = str(uuid.uuid4())
        tag = tag_for(receipt_id)
        created = datetime.datetime.now(datetime.timezone.utc).isoformat(
            timespec="seconds"
        )

        channels = np.atleast_2d(np.asarray(audio, dtype=np.float32))
        marked = self._watermark.embed(channels, sample_rate, tag)
        plain = io.BytesIO()
        sf.write(plain, marked.T, sample_rate, format="WAV", subtype="PCM_16")

        watermark = {"scheme": WATERMARK_SCHEME, "tag": format_tag(tag)}
        manifest = {
            "claim_generator_info": [{"name": "OmniSuite"}],
            "title": f"{receipt_id}.wav",
            "assertions": [
                {
                    # Travels with the file, so no text and no voice in here.
                    "label": RECEIPT_LABEL,
                    "data": {
                        "receipt_id": receipt_id,
                        "created": created,
                        "model": model,
                        "watermark": watermark,
                    },
                },
            ],
        }
        signer = c2pa.Signer.from_info(
            c2pa.C2paSignerInfo(
                alg=c2pa.C2paSigningAlg.ES256,
                sign_cert=keys.chain_pem.encode(),
                private_key=keys.key_pem.encode(),
                ta_url=None,  # no timestamp authority: signing stays offline
            )
        )
        signed = io.BytesIO()
        plain.seek(0)
        with signer, c2pa.Builder(manifest) as builder:
            # Adds the "created by a trained model" action that marks the file as AI-generated.
            builder.set_intent(
                c2pa.C2paBuilderIntent.CREATE,
                c2pa.C2paDigitalSourceType.TRAINED_ALGORITHMIC_MEDIA,
            )
            builder.sign(signer, "audio/wav", plain, signed)
        wav_bytes = signed.getvalue()

        receipt = {
            "version": 1,
            "id": receipt_id,
            "created": created,
            "model": model,
            "text_sha256": hashlib.sha256(text.encode()).hexdigest(),
            "audio": {
                "sample_rate": sample_rate,
                "seconds": round(marked.shape[-1] / sample_rate, 3),
                "sha256": hashlib.sha256(wav_bytes).hexdigest(),
            },
            "watermark": watermark,
            "signer": {"name": keys.name, "serial": keys.serial},
        }
        self.receipts_dir.mkdir(parents=True, exist_ok=True)
        (self.receipts_dir / f"{receipt_id}.json").write_text(
            json.dumps(receipt, indent=2)
        )
        return wav_bytes, receipt


# ── Verifying ────────────────────────────────────────────────────────────────


def _has_manifest_chunk(path: Path) -> bool:
    """True when a WAV file carries a C2PA chunk, whether it can be read or not."""
    try:
        with path.open("rb") as handle:
            header = handle.read(12)
            if header[:4] != b"RIFF" or header[8:] != b"WAVE":
                return False
            while len(chunk := handle.read(8)) == 8:
                if chunk[:4] == b"C2PA":
                    return True
                size = int.from_bytes(chunk[4:], "little")
                handle.seek(size + size % 2, os.SEEK_CUR)
    except OSError:
        pass
    return False


def _read_manifest(path: Path, anchors: list[str], own_serial: str | None) -> dict | None:
    """Read and validate the C2PA manifest of a file. None when there is none."""
    settings: dict = {
        # Reading a file must never make it phone anywhere.
        "verify": {"verify_trust": True, "remote_manifest_fetch": False, "ocsp_fetch": False}
    }
    if anchors:
        settings["trust"] = {"user_anchors": "\n".join(anchors)}
    unreadable = {
        "state": "invalid",
        "id": None,
        "created": None,
        "model": None,
        "tag": None,
        "ai_generated": False,
        "signer": None,
        "signed_here": False,
    }
    try:
        with c2pa.Context.from_dict(settings) as context:
            reader = c2pa.Reader.try_create(str(path), None, None, context=context)
            if reader is None:
                return None
            with reader:
                store = json.loads(reader.json())
    except (c2pa.C2paError.NotSupported, c2pa.C2paError.Io, c2pa.C2paError.Other) as error:
        if _has_manifest_chunk(path):
            # The manifest is still in the file, but cut short or damaged at its start.
            return {**unreadable, "problems": [str(error)]}
        # Not a format C2PA can carry, or a file without a manifest.
        return None
    except c2pa.C2paError as error:
        # There is a manifest, but it is damaged beyond reading.
        return {**unreadable, "problems": [str(error)]}

    manifest = store.get("manifests", {}).get(store.get("active_manifest"), {})
    signature = manifest.get("signature_info", {})
    assertions = manifest.get("assertions", [])
    receipt = next(
        (a.get("data", {}) for a in assertions if a.get("label") == RECEIPT_LABEL), {}
    )
    source_types = [
        str(action.get("digitalSourceType")).rsplit("/", 1)[-1]
        for a in assertions
        if a.get("label", "").startswith("c2pa.actions")
        for action in a.get("data", {}).get("actions", [])
    ]
    failures = store.get("validation_results", {}).get("activeManifest", {}).get("failure", [])
    state = str(store.get("validation_state", "Invalid")).lower()
    return {
        "state": state,
        "id": receipt.get("receipt_id"),
        "created": receipt.get("created"),
        "model": receipt.get("model"),
        "tag": receipt.get("watermark", {}).get("tag"),
        "ai_generated": any(s in AI_SOURCE_TYPES for s in source_types),
        "signer": signature.get("common_name"),
        # A serial number is easy to copy, so the chain has to lead to our root too.
        "signed_here": state == "trusted"
        and own_serial is not None
        and signature.get("cert_serial_number") == own_serial,
        "problems": [str(f.get("code")) for f in failures],
    }


def _read_watermark(path: Path, watermark, receipts_dir: Path) -> dict:
    """Look for the watermark in a file and for receipts here that carry its tag."""
    try:
        audio, sample_rate = sf.read(str(path), dtype="float32", always_2d=True)
        score, tag = watermark.detect(audio.T, sample_rate)
    except Exception as error:  # decoding and model loading fail in many ways
        return {"found": None, "error": f"{type(error).__name__}: {error}"}

    result: dict = {"found": score >= DETECTION_THRESHOLD, "score": round(score, 3)}
    if result["found"]:
        result["tag"] = format_tag(tag)
        result["receipts_here"] = _receipts_with_tag(receipts_dir, result["tag"])
    return result


def _receipts_with_tag(receipts_dir: Path, tag: str) -> list[dict]:
    matches = []
    for receipt_path in sorted(receipts_dir.glob("*.json")):
        try:
            receipt = json.loads(receipt_path.read_text())
        except (OSError, ValueError):
            continue
        if receipt.get("watermark", {}).get("tag") == tag:
            matches.append({"id": receipt.get("id"), "created": receipt.get("created")})
    return matches


def verify_file(
    path: Path, data_dir: Path = DATA_DIR, *, trust: list[Path] | None = None, watermark=None
) -> dict:
    """Check a file for a receipt and a watermark.

    ``verdict`` is one of:

    * ``intact``: the manifest is there, the file is unchanged since signing, and
      it was signed by this install or by one passed in ``trust``
    * ``untrusted``: the same, but signed with a key nobody vouched for. Anyone
      can make such a file.
    * ``broken``: the manifest is there but the file changed after signing
    * ``stripped``: no manifest, but the watermark is still in the audio
    * ``unmarked``: neither was found
    """
    keys_dir = data_dir / "keys"
    anchors = [p.read_text() for p in (trust or [])]
    own_serial = None
    if (keys_dir / "root.pem").exists() and (keys_dir / "signer.pem").exists():
        anchors.append((keys_dir / "root.pem").read_text())
        own = x509.load_pem_x509_certificate((keys_dir / "signer.pem").read_bytes())
        own_serial = str(own.serial_number)

    receipt = _read_manifest(path, anchors, own_serial)
    mark = _read_watermark(path, watermark or AudioSealWatermark(), data_dir / "receipts")
    if receipt is not None and receipt["tag"] and mark.get("found"):
        mark["matches_receipt"] = receipt["tag"] == mark["tag"]

    if receipt is None:
        verdict = "stripped" if mark.get("found") else "unmarked"
    elif receipt["state"] == "trusted":
        verdict = "intact"
    elif receipt["state"] == "valid":
        verdict = "untrusted"
    else:
        verdict = "broken"
    return {"file": str(path), "verdict": verdict, "receipt": receipt, "watermark": mark}


HEADLINES = {
    "intact": "receipt intact",
    "untrusted": "receipt intact, but its signer is unknown to this install",
    "broken": "receipt broken, the file changed after it was signed",
    "stripped": "watermarked as AI-generated, no receipt in the file",
    "unmarked": "no mark found",
}


def _printable(value) -> str:
    """Text that came out of a file, safe to print: no control characters."""
    return "".join(ch for ch in str(value) if ch.isprintable())


def _receipt_lines(receipt: dict | None, verdict: str) -> list[str]:
    if receipt is None:
        return ["  receipt    none in the file"]
    signer = _printable(receipt["signer"])
    if receipt["signer"] is None:
        lines = ["  receipt    damaged, could not be read"]
    elif receipt["signed_here"]:
        lines = [f"  receipt    signed by this install ({signer})"]
    elif receipt["state"] == "trusted":
        lines = [f"  receipt    signed by {signer}, which you trust"]
    else:
        lines = [
            f"  receipt    signed by {signer}, unknown to this install",
            "             to accept it, pass that install's root.pem with --trust",
        ]
    if receipt["id"]:
        made = ", ".join(_printable(receipt[key]) for key in ("id", "created", "model"))
        lines.append(f"             {made}")
    if verdict == "broken":
        lines.append(f"             failed: {_printable(', '.join(receipt['problems']))}")
    return lines


def _watermark_lines(mark: dict, has_receipt: bool) -> list[str]:
    if mark["found"] is None:
        return [f"  watermark  not checked ({_printable(mark['error'])})"]
    if not mark["found"]:
        return ["  watermark  not found"]
    note = ""
    if "matches_receipt" in mark:
        note = ", matches the receipt" if mark["matches_receipt"] else ", does NOT match the receipt"
    lines = [f"  watermark  found, tag {mark['tag']}{note}"]
    if not has_receipt:
        lines += [
            f"             made here: {match['id']}, {match['created']}"
            for match in mark["receipts_here"]
        ] or ["             no receipt with this tag on this machine"]
    return lines


def _describe(result: dict) -> str:
    """Plain-text report for the terminal."""
    receipt, verdict = result["receipt"], result["verdict"]
    headline = HEADLINES[verdict]
    if verdict == "intact" and receipt["ai_generated"]:
        headline = "AI-generated, receipt intact"
    if verdict == "untrusted" and receipt["ai_generated"]:
        headline = "marked as AI-generated, by a signer unknown to this install"
    lines = [f"{result['file']}: {headline}"]
    lines += _receipt_lines(receipt, verdict)
    lines += _watermark_lines(result["watermark"], receipt is not None)
    if verdict == "unmarked":
        lines.append("  This does not prove a person spoke it. Marks can be removed.")
    return "\n".join(lines)


# ── Command line ─────────────────────────────────────────────────────────────


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="omnisuite", description="Check the marks OmniSuite puts on its audio."
    )
    commands = parser.add_subparsers(dest="command", required=True)
    verify = commands.add_parser(
        "verify",
        help="check a file for a receipt and a watermark",
        description="Exit code: 0 receipt intact, 3 no receipt but watermark "
        "found, 4 receipt broken, 5 no mark found, 6 receipt intact but from "
        "an unknown signer, 1 error.",
    )
    verify.add_argument("file", type=Path)
    verify.add_argument(
        "--trust",
        action="append",
        type=Path,
        default=[],
        metavar="ROOT_PEM",
        help="data/keys/root.pem of another install whose files you trust (repeatable)",
    )
    verify.add_argument("--json", action="store_true", help="print the result as JSON")
    args = parser.parse_args(argv)

    for needed in [args.file, *args.trust]:
        if not needed.is_file():
            print(f"omnisuite: no such file: {needed}", file=sys.stderr)
            return 1
    result = verify_file(args.file, DATA_DIR, trust=args.trust)
    print(json.dumps(result, indent=2) if args.json else _describe(result))
    return EXIT_CODES[result["verdict"]]


if __name__ == "__main__":
    sys.exit(main())
