"""A tiny untrained OmniVoice with a stand-in codec, shared by the tests here."""

from types import SimpleNamespace

import pytest
import torch
from omnivoice.models.omnivoice import OmniVoice, OmniVoiceConfig
from omnivoice.utils.duration import RuleDurationEstimator

HOP = 960
RATE = 24000


class TextTokenizer:
    def __call__(self, text, return_tensors=None, add_special_tokens=True):
        ids = [3 + ord(char) % 250 for char in text]
        if return_tensors == "pt":
            return SimpleNamespace(input_ids=torch.tensor([ids], dtype=torch.long))
        return SimpleNamespace(input_ids=ids)


class Codec:
    """One token per frame: the frame's mean level in thousandths."""

    config = SimpleNamespace(hop_length=HOP)
    device = torch.device("cpu")

    def encode(self, wav):
        level = wav.reshape(-1, HOP).mean(dim=1)
        codes = (level * 1000).round().long().clamp(0, 1023)
        return SimpleNamespace(audio_codes=codes.repeat(8, 1).unsqueeze(0))

    def decode(self, tokens):
        level = tokens[0, 0].float() / 1000
        return SimpleNamespace(audio_values=level.repeat_interleave(HOP)[None, None])


@pytest.fixture(scope="module")
def model():
    torch.manual_seed(0)
    config = OmniVoiceConfig(
        llm_config={
            "model_type": "qwen3",
            # Audio ids pass through the text embedding too, so it has to hold them.
            "vocab_size": 1100,
            "hidden_size": 32,
            "intermediate_size": 64,
            "num_hidden_layers": 2,
            "num_attention_heads": 2,
            "num_key_value_heads": 2,
            "head_dim": 16,
        }
    )
    model = OmniVoice(config).eval()
    model.text_tokenizer = TextTokenizer()
    model.audio_tokenizer = Codec()
    model.duration_estimator = RuleDurationEstimator()
    model.sampling_rate = RATE
    return model
