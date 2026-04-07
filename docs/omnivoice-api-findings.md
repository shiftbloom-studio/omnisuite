# OmniVoice API Findings

## Core API

```python
from omnivoice import OmniVoice
import torch, torchaudio

model = OmniVoice.from_pretrained("k2-fsa/OmniVoice", device_map="cuda:0", dtype=torch.float16)
```

## generate() Signature

```python
audio = model.generate(
    text="Hello world",           # Required: text to synthesize
    ref_audio="ref.wav",          # Optional: path to reference audio for voice cloning
    ref_text="Transcript...",     # Optional: transcript of reference audio
    instruct="female, low pitch", # Optional: voice design via free-form text instruction
    num_step=32,                  # Optional: diffusion steps (32 default, 16 for faster)
    speed=1.0,                    # Optional: speed factor (>1 faster, <1 slower)
    duration=10.0,                # Optional: fixed output duration in seconds
)
# Returns: list of torch.Tensor with shape (1, T) at 24kHz
torchaudio.save("out.wav", audio[0], 24000)
```

## Voice Design

Supported via `instruct` parameter — free-form text, NOT individual sliders.
Examples: "female, low pitch, british accent", "male, elderly, whisper"

Supported attributes in instruct text:
- Gender: male, female
- Age: child, young, elderly
- Pitch: very low, low, high, very high
- Style: whisper
- Accents: American, British, etc.
- Chinese dialects: 四川话, 陕西话, etc.

**Decision: Voice Design page WILL be implemented** but with a text instruction input instead of individual sliders. This is simpler and more flexible.

## Non-Verbal Symbols

Inline tags in text: `[laughter]`, `[sigh]`, `[confirmation-en]`, `[question-en]`, `[surprise-ah]`, etc.

## Pronunciation Control

- Chinese: pinyin with tone numbers inline
- English: CMU dictionary format in brackets `[IH1 T]`

## Output

- Format: list of torch.Tensor, shape (1, T)
- Sample rate: 24000 Hz
- Save: `torchaudio.save("out.wav", audio[0], 24000)`
