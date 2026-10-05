# pipecat-upliftai

[UpliftAI](https://upliftai.org) text-to-speech plugin for [Pipecat](https://github.com/pipecat-ai/pipecat) — streaming WebSocket TTS for real-time voice agents, with native support for Urdu, Sindhi, Balochi, and other South-Asian voices.

> Maintained by **UpliftAI**.

## Features

- Streaming 22.05 kHz raw-PCM output
- Multiple synthesize requests multiplexed on a single WebSocket
- Server-side cancellation on bot interruption
- Optional server-side phrase replacement
- Per-request `audio_end` gate guarantees in-order audio across sentence boundaries

## Install

> **PyPI publishing is in progress.** The PyPI organization request is submitted
> and awaiting approval. Until it lands, install straight from GitHub:

```bash
pip install "pipecat-upliftai @ git+https://github.com/uplift-initiative/pipecat-upliftai.git@main"
```

Once published, this becomes:

```bash
pip install pipecat-upliftai   # not available yet
```

## Quick start

```python
import os

from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.runner import PipelineRunner
from pipecat.pipeline.task import PipelineParams, PipelineTask
from pipecat_upliftai import UpliftAITTSService

tts = UpliftAITTSService(
    api_key=os.environ["UPLIFTAI_API_KEY"],
    settings=UpliftAITTSService.Settings(
        voice="v_meklc281",          # default Urdu voice
        output_format="PCM_22050_16",
        speed=1.0,                   # 0.5–2.0, 1.0 is the normal rate
    ),
)

# Drop `tts` into your Pipecat pipeline:
#   transport.input → STT → user_aggregator → LLM → tts → transport.output → assistant_aggregator
```

For a complete voice-agent example see [`examples/voice_agent.py`](examples/voice_agent.py).

## Output format and sample rate

`PCM_22050_16` is the only usable `output_format`, and the pipeline must run at **22050 Hz**.

Pipecat carries TTS audio on `TTSAudioRawFrame`, which is defined as raw 16-bit PCM, and this service hands UpliftAI's bytes straight to that frame. UpliftAI's other wire formats (MP3, OGG, WAV, ULAW) are encoded or 8-bit, so they would be interpreted as PCM samples and played back as noise. They are rejected at configuration time rather than producing broken audio.

Set the rate with the pipeline's `audio_out_sample_rate`, or the service's `sample_rate=` argument. `start()` raises `ValueError` on a mismatch — fail-fast at configuration time rather than silently producing audio at the wrong rate.

**Telephony transports still want PCM here.** Pipecat's serializers (Twilio, Plivo, Telnyx, Vonage, Exotel, Genesys) call `pcm_to_ulaw()` on outgoing audio themselves, so they convert at the transport edge; sending μ-law from the TTS would double-encode it.

## Voice IDs

Common UpliftAI voices:

| Voice ID | Language | Gender |
| --- | --- | --- |
| `v_meklc281` *(default)* | Urdu | Female |

Browse the full catalog at [docs.upliftai.org/orator_voices](https://docs.upliftai.org/orator_voices).

## Runtime settings updates

`UpliftAITTSSettings` supports runtime updates via Pipecat's standard `TTSUpdateSettingsFrame` mechanism:

- `voice`, `phrase_replacement_config_id` — apply on the next synthesize request
- `speed` — applies on the next synthesize request, if within UpliftAI's 0.5–2.0 range; otherwise the change is rolled back and an error is pushed
- `output_format` — applies on the next synthesize request **only if** it remains usable (raw PCM at the pipeline's rate); otherwise the change is rolled back and an error is pushed

## Compatibility

- Requires **Pipecat 1.8.0+**; tested with **Pipecat 1.12.0**
- Python 3.11+

## License

BSD-2-Clause. See [LICENSE](LICENSE).
