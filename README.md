# pipecat-upliftai

[UpliftAI](https://upliftai.org) text-to-speech plugin for [Pipecat](https://github.com/pipecat-ai/pipecat) — streaming WebSocket TTS for real-time voice agents, with native support for Urdu, Sindhi, Balochi, and other South-Asian voices.

> Maintained by **UpliftAI**.

## Features

- Streaming PCM, WAV, MP3, OGG, or μ-law (ULAW) output
- Multiple synthesize requests multiplexed on a single WebSocket
- Server-side cancellation on bot interruption
- Optional server-side phrase replacement
- Per-request `audio_end` gate guarantees in-order audio across sentence boundaries

## Install

```bash
pip install pipecat-upliftai
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
    ),
)

# Drop `tts` into your Pipecat pipeline:
#   transport.input → STT → user_aggregator → LLM → tts → transport.output → assistant_aggregator
```

For a complete voice-agent example see [`examples/voice_agent.py`](examples/voice_agent.py).

## Sample-rate constraint

UpliftAI's wire format hard-locks the audio rate:

| `output_format` | Rate |
| --- | --- |
| `PCM_22050_16`, `WAV_22050_16`, `WAV_22050_32`, `MP3_22050_32`, `MP3_22050_64`, `MP3_22050_128`, `OGG_22050_16` | 22050 Hz |
| `ULAW_8000_8` | 8000 Hz |

The pipeline's `audio_out_sample_rate` (or the service's `sample_rate=` argument) must match. `start()` raises `ValueError` on mismatch — fail-fast at configuration time rather than silently producing audio at the wrong rate.

## When to pick which format

- **`PCM_22050_16` (default)** — best for WebRTC transports (Daily, LiveKit, Pipecat WebRTC). Pipecat's audio pipeline is PCM-native; downstream processors resample as needed.
- **`MP3_22050_*`** — smaller payloads if your transport doesn't decode raw PCM.
- **`ULAW_8000_8`** — for telephony serializers (Twilio, Plivo, Telnyx, Vonage, Exotel, Genesys). Skips a μ-law encode + downsample on every frame.

## Voice IDs

Common UpliftAI voices:

| Voice ID | Language | Gender |
| --- | --- | --- |
| `v_meklc281` *(default)* | Urdu | Female |

Browse the full catalog at [studio.upliftai.org](https://platform.upliftai.org/studio/home).

## Runtime settings updates

`UpliftAITTSSettings` supports runtime updates via Pipecat's standard `TTSUpdateSettingsFrame` mechanism:

- `voice`, `phrase_replacement_config_id` — apply on the next synthesize request
- `output_format` — applies on the next synthesize request **only if** the implied rate still matches the pipeline rate; otherwise the change is rejected and an error is pushed

## Compatibility

- Tested with **Pipecat 1.1.0**
- Python 3.11+

## License

BSD-2-Clause. See [LICENSE](LICENSE).
