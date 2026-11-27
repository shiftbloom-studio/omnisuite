"""Enrolment by reading: a voice is enrolled by reading a fresh sentence aloud.

The sentence is made up on the spot, so a clip taken from a video or a voice
message cannot contain it. Whisper checks the words. The take itself becomes
the reference clip, with the sentence as its exact transcript.

This shows that the sentence was spoken on request. It does not show that a
person spoke it and not another voice model.
"""

from __future__ import annotations

import io
import secrets
import threading
import time
import unicodedata
from dataclasses import dataclass

import numpy as np
import soundfile as sf

CHALLENGE_SECONDS = 300
MAX_ATTEMPTS = 5
MAX_OPEN_CHALLENGES = 100
# Whisper mishears a word now and then. Three in twenty may differ.
MAX_WORD_ERROR_RATE = 0.15
MIN_TAKE_SECONDS = 3.0
# Whisper takes at most 30 seconds in one piece.
MAX_TAKE_SECONDS = 25.0
MAX_TAKE_BYTES = 16 * 1024 * 1024
# Quiet is what stays this far under the loudest moment of a take (-40 dB).
QUIET_BELOW_PEAK = 0.01
KEPT_BEFORE_SECONDS = 0.1
KEPT_AFTER_SECONDS = 0.2

LANGUAGES = {"en": "English", "de": "German"}

# Plain words that are written one way only: no numbers, no names, no
# contractions, nothing spelled differently in British and American English.
# Whisper has to give back the same letters the person was shown.
ENGLISH = {
    "opening": [
        "Early this morning",
        "Late last night",
        "On a windy Tuesday",
        "Just before lunch",
        "After the long meeting",
        "During the summer storm",
        "Right after breakfast",
        "In the middle of winter",
        "Shortly before midnight",
        "On a quiet Sunday",
        "After the last train left",
        "While the rain was falling",
        "Before the shops opened",
        "At the end of the week",
        "During the short break",
        "On the way to work",
    ],
    "subject": [
        "the tired baker",
        "my older sister",
        "the young doctor",
        "our new teacher",
        "the local farmer",
        "a careful pilot",
        "the quiet librarian",
        "my best friend",
        "the old sailor",
        "a nervous student",
        "the village carpenter",
        "our kind landlord",
        "the busy waiter",
        "a clever engineer",
        "the patient nurse",
        "my little cousin",
    ],
    "action": [
        "carried a heavy basket",
        "painted the wooden fence",
        "found a silver key",
        "repaired the broken clock",
        "planted a small apple tree",
        "wrote a very long letter",
        "opened the dusty window",
        "cooked a large pot of soup",
        "borrowed a yellow umbrella",
        "counted the empty bottles",
        "washed the muddy boots",
        "folded the paper map",
        "locked the garden gate",
        "sold a pair of gloves",
        "lost a leather wallet",
        "built a round table",
    ],
    "place": [
        "behind the old station",
        "near the river",
        "in the kitchen downstairs",
        "next to the post office",
        "under the stone bridge",
        "at the corner bakery",
        "outside the public library",
        "across the empty square",
        "beside the garden wall",
        "inside the little shop",
        "above the bicycle shed",
        "along the narrow street",
        "in front of the school",
        "at the edge of the forest",
        "on the top floor",
        "down in the cellar",
    ],
    "closing": [
        "and nobody asked why",
        "and then went home happy",
        "while the dog was sleeping",
        "before the bell rang twice",
        "and the cat watched closely",
        "although it was getting dark",
        "because the weather was fine",
        "and everyone clapped loudly",
        "while the kettle was boiling",
        "and nothing else happened that day",
        "before the bus arrived",
        "and the children laughed",
        "as the lights went out",
        "until the music stopped",
        "and it only took a moment",
        "when the phone started ringing",
    ],
}

# German keeps each phrase in one piece, so that case and gender always agree.
GERMAN = {
    "subject": [
        "Der müde Bäcker",
        "Meine ältere Schwester",
        "Die junge Ärztin",
        "Unser neuer Lehrer",
        "Der alte Seemann",
        "Eine nervöse Studentin",
        "Der freundliche Nachbar",
        "Die geduldige Krankenschwester",
        "Mein bester Freund",
        "Die stille Bibliothekarin",
        "Der kluge Ingenieur",
        "Unsere nette Vermieterin",
        "Der fleißige Kellner",
        "Die vorsichtige Pilotin",
        "Der junge Tischler",
        "Meine kleine Cousine",
    ],
    "action": [
        ("reparierte", "die kaputte Uhr"),
        ("trug", "einen schweren Korb"),
        ("fand", "einen silbernen Schlüssel"),
        ("strich", "den alten Zaun"),
        ("pflanzte", "einen kleinen Apfelbaum"),
        ("schrieb", "einen sehr langen Brief"),
        ("öffnete", "das staubige Fenster"),
        ("kochte", "einen großen Topf Suppe"),
        ("zählte", "die leeren Flaschen"),
        ("putzte", "die schmutzigen Stiefel"),
        ("faltete", "die alte Landkarte"),
        ("verkaufte", "ein Paar Handschuhe"),
        ("verlor", "eine braune Geldbörse"),
        ("baute", "einen runden Tisch"),
        ("suchte", "den gelben Regenschirm"),
        ("las", "ein dickes Buch"),
    ],
    "time": [
        "heute Morgen",
        "gestern Abend",
        "am frühen Nachmittag",
        "kurz vor Mitternacht",
        "nach dem Frühstück",
        "an einem ruhigen Sonntag",
        "mitten im Winter",
        "nach der langen Sitzung",
        "während des Gewitters",
        "kurz vor dem Mittagessen",
        "am Ende der Woche",
        "in der kurzen Pause",
        "an einem windigen Dienstag",
        "noch vor Sonnenaufgang",
        "spät in der Nacht",
        "gleich nach der Arbeit",
    ],
    "place": [
        "hinter dem alten Bahnhof",
        "neben der Post",
        "unter der steinernen Brücke",
        "in der Küche",
        "vor der Schule",
        "am Rand des Waldes",
        "auf dem leeren Marktplatz",
        "neben der Gartenmauer",
        "in dem kleinen Laden",
        "an der Ecke beim Bäcker",
        "vor der Bibliothek",
        "in der schmalen Gasse",
        "am Ufer des Flusses",
        "hinter dem Fahrradschuppen",
        "auf dem Dachboden",
        "unten im Keller",
    ],
    "closing": [
        "und niemand fragte warum",
        "während der Hund schlief",
        "bevor der Bus kam",
        "obwohl es schon dunkel wurde",
        "weil das Wetter schön war",
        "und alle klatschten laut",
        "während das Wasser kochte",
        "und die Kinder lachten",
        "als das Licht ausging",
        "bis die Musik aufhörte",
        "und es dauerte nur einen Augenblick",
        "als das Telefon klingelte",
        "und die Katze sah genau zu",
        "bevor die Glocke läutete",
        "und danach war alles still",
        "während draußen der Regen fiel",
    ],
}


def make_sentence(language: str) -> str:
    """A sentence nobody has said before: one of about a million per language."""
    if language == "en":
        pick = {slot: secrets.choice(options) for slot, options in ENGLISH.items()}
        return "{opening}, {subject} {action} {place}, {closing}.".format(**pick)
    if language == "de":
        pick = {slot: secrets.choice(options) for slot, options in GERMAN.items()}
        verb, thing = pick["action"]
        return (
            f"{pick['subject']} {verb} {pick['time']} {thing} {pick['place']}, "
            f"{pick['closing']}."
        )
    raise ValueError(f"No sentences for language {language!r}")


# ── Challenges ───────────────────────────────────────────────────────────────


@dataclass
class Challenge:
    id: str
    sentence: str
    language: str
    expires: float
    attempts_left: int = MAX_ATTEMPTS


class Challenges:
    """The sentences that are waiting to be read. Kept in memory only."""

    def __init__(self, clock=time.monotonic) -> None:
        self._clock = clock
        self._open: dict[str, Challenge] = {}
        self._lock = threading.Lock()

    def start(self, language: str) -> Challenge:
        challenge = Challenge(
            id=secrets.token_urlsafe(16),
            sentence=make_sentence(language),
            language=language,
            expires=self._clock() + CHALLENGE_SECONDS,
        )
        with self._lock:
            self._drop_expired()
            while len(self._open) >= MAX_OPEN_CHALLENGES:
                del self._open[next(iter(self._open))]  # the oldest one
            self._open[challenge.id] = challenge
        return challenge

    def claim(self, challenge_id: str) -> Challenge | None:
        """Take a sentence out for one check. None when it is unknown or expired.

        While a take is being checked nobody else can use the sentence, so one
        sentence never enrols two voices.
        """
        with self._lock:
            self._drop_expired()
            return self._open.pop(challenge_id, None)

    def give_back(self, challenge: Challenge, *, used_a_try: bool = True) -> int:
        """Keep a sentence for another try after a failed check. Returns the tries left."""
        with self._lock:
            if used_a_try:
                challenge.attempts_left -= 1
            if challenge.attempts_left > 0:
                self._open[challenge.id] = challenge
            return max(challenge.attempts_left, 0)

    def _drop_expired(self) -> None:
        now = self._clock()
        for challenge_id in [c.id for c in self._open.values() if c.expires <= now]:
            del self._open[challenge_id]


# ── Checking a take ──────────────────────────────────────────────────────────


def words(text: str) -> list[str]:
    """Letters only, in one case, so that punctuation and capitals do not count."""
    text = unicodedata.normalize("NFKC", text).casefold()
    return "".join(
        ch if ch.isalpha() else "" if ch in "'’" else " " for ch in text
    ).split()


def word_errors(reference: list[str], heard: list[str]) -> int:
    """Fewest word substitutions, deletions and insertions between the two."""
    row = list(range(len(heard) + 1))
    for i, reference_word in enumerate(reference, start=1):
        previous, row[0] = row[0], i
        for j, heard_word in enumerate(heard, start=1):
            previous, row[j] = row[j], min(
                row[j] + 1, row[j - 1] + 1, previous + (reference_word != heard_word)
            )
    return row[-1]


def matches(sentence: str, heard: str) -> tuple[bool, float]:
    """Whether ``heard`` is the sentence, and the share of its words that fit."""
    reference = words(sentence)
    rate = word_errors(reference, words(heard)) / max(len(reference), 1)
    return rate <= MAX_WORD_ERROR_RATE, round(max(0.0, 1.0 - rate), 2)


class TakeError(ValueError):
    """The recording cannot be used. The message is meant for the person."""


def trim_quiet_ends(audio: np.ndarray, sample_rate: int) -> np.ndarray:
    """Cut the quiet before the first word and after the last one.

    The speech model reads the pace of a voice from the length of its clip and
    the words in it. The wait between pressing record and speaking must not
    count, or everything the voice says later comes out slower.
    """
    frame = max(1, sample_rate // 100)
    frames = len(audio) // frame
    if frames == 0:
        return audio[:0]
    loudness = np.sqrt(np.mean(audio[: frames * frame].reshape(frames, frame) ** 2, axis=1))
    if loudness.max() <= 0:
        return audio[:0]
    loud = np.flatnonzero(loudness > loudness.max() * QUIET_BELOW_PEAK)
    start = loud[0] * frame - int(KEPT_BEFORE_SECONDS * sample_rate)
    end = (loud[-1] + 1) * frame + int(KEPT_AFTER_SECONDS * sample_rate)
    return audio[max(start, 0) : end]


def read_take(content: bytes) -> tuple[np.ndarray, int]:
    """Decode a recording to mono float audio, without its quiet ends."""
    if len(content) > MAX_TAKE_BYTES:
        raise TakeError("That recording is too large.")
    try:
        audio, sample_rate = sf.read(io.BytesIO(content), dtype="float32", always_2d=True)
    except Exception as error:  # soundfile raises its own error types
        raise TakeError("That recording could not be read.") from error
    if len(audio) > MAX_TAKE_SECONDS * sample_rate:
        raise TakeError("That was too long. Read just the one sentence.")
    audio = trim_quiet_ends(audio.mean(axis=1), sample_rate)
    if len(audio) == 0:
        raise TakeError("There is nothing to hear in that recording. Check the microphone.")
    if len(audio) < MIN_TAKE_SECONDS * sample_rate:
        raise TakeError("That was too short. Read the whole sentence.")
    return audio, sample_rate


def reference_wav(audio: np.ndarray, sample_rate: int) -> bytes:
    """The take as the WAV file that becomes the voice's reference clip."""
    buffer = io.BytesIO()
    sf.write(buffer, audio, sample_rate, format="WAV", subtype="PCM_16")
    return buffer.getvalue()
