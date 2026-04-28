# Quickstart — `pipecat-upliftai`

Five-minute guide to using the UpliftAI TTS plugin for Pipecat. For full
docs, see [README.md](README.md).

## Prerequisites

- Python **3.11+**
- An UpliftAI API key — get one at [platform.upliftai.org/studio](https://platform.upliftai.org/studio/home)

## 1. Install

The plugin isn't on PyPI yet. Install it straight from GitHub:

```bash
pip install "pipecat-upliftai @ git+https://github.com/uplift-initiative/pipecat-upliftai.git@main"
```

This also pulls in `pipecat-ai` and `websockets` automatically.

## 2. Synthesize text → audio (minimal sanity check)

Save this as `smoke.py`:

```python
import asyncio, os, wave

from pipecat.frames.frames import EndFrame, LLMFullResponseEndFrame, LLMTextFrame, TTSAudioRawFrame
from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.runner import PipelineRunner
from pipecat.pipeline.task import PipelineParams, PipelineTask
from pipecat.processors.frame_processor import FrameProcessor

from pipecat_upliftai import UpliftAITTSService


class WavSink(FrameProcessor):
    def __init__(self, path):
        super().__init__()
        self._wav = wave.open(path, "wb")
        self._wav.setnchannels(1); self._wav.setsampwidth(2); self._wav.setframerate(22050)

    async def process_frame(self, frame, direction):
        await super().process_frame(frame, direction)
        if isinstance(frame, TTSAudioRawFrame):
            self._wav.writeframes(frame.audio)
        await self.push_frame(frame, direction)


async def main():
    tts = UpliftAITTSService(api_key=os.environ["UPLIFTAI_API_KEY"])
    pipeline = Pipeline([tts, WavSink("out.wav")])
    task = PipelineTask(pipeline, params=PipelineParams(audio_out_sample_rate=22050))

    async def feed():
        await asyncio.sleep(0.1)
        await task.queue_frames([
            LLMTextFrame("Hello from UpliftAI through Pipecat."),
            LLMFullResponseEndFrame(),
        ])
        await asyncio.sleep(6.0)
        await task.queue_frame(EndFrame())

    runner = PipelineRunner(handle_sigint=False)
    await asyncio.gather(runner.run(task), feed())


if __name__ == "__main__":
    asyncio.run(main())
```

Run it:

```bash
export UPLIFTAI_API_KEY=your_key_here
python smoke.py
ls -lh out.wav            # should be ~80–120 KB of 22050 Hz PCM
afplay out.wav            # macOS; or `aplay out.wav` / `ffplay out.wav`
```

If you hear the line spoken, the plugin works.

## 3. Use it in a real voice agent

The full Pakistan-history Urdu voice agent example is in
[`examples/voice_agent.py`](examples/voice_agent.py) — drop the
`UpliftAITTSService` into a Pipecat pipeline alongside any STT and LLM
of your choice:

```python
pipeline = Pipeline([
    transport.input(),
    stt,                  # e.g. OpenAISTTService
    user_aggregator,
    llm,                  # e.g. OpenAILLMService
    tts,                  # ← UpliftAITTSService
    transport.output(),
    assistant_aggregator,
])
```

A complete runnable demo (browser UI, Daily, or Twilio transports) is at
**[uplift-initiative/pipecat-upliftai-demo](https://github.com/uplift-initiative/pipecat-upliftai-demo)** *(if/once published — otherwise ask Zaid)*.

## 4. Important: sample-rate constraint

UpliftAI's wire format hard-locks the audio rate. The pipeline's
`audio_out_sample_rate` (or the service's `sample_rate=` argument) must
match — `start()` raises `ValueError` on mismatch.

| `output_format` | Required pipeline rate |
| --- | --- |
| `PCM_22050_16` *(default)* | `22050` |
| `WAV_22050_*`, `MP3_22050_*`, `OGG_22050_16` | `22050` |
| `ULAW_8000_8` *(for telephony — Twilio/Plivo/etc.)* | `8000` |

## 5. Customising

```python
from pipecat_upliftai import UpliftAITTSService

tts = UpliftAITTSService(
    api_key=os.environ["UPLIFTAI_API_KEY"],
    settings=UpliftAITTSService.Settings(
        voice="v_meklc281",                 # browse: https://docs.upliftai.org/orator_voices
        output_format="PCM_22050_16",       # or MP3_22050_64 / ULAW_8000_8 / etc.
        phrase_replacement_config_id=None,  # optional server-side phrase replacement
    ),
)
```

## Troubleshooting

| Symptom | Cause | Fix |
| --- | --- | --- |
| `ValueError: sample_rate=… does not match output_format=…` | Pipeline rate ≠ format-implied rate | Set `audio_out_sample_rate` on `PipelineParams` to match (22050 for PCM/WAV/MP3/OGG, 8000 for ULAW). |
| `Unable to connect to UpliftAI TTS: 401` | Bad/missing API key | Verify `UPLIFTAI_API_KEY` env var is set and correct. |
| Audio sounds garbled / interleaved | (Should not happen — gate prevents it) | Update to latest plugin; file an issue. |
| `ModuleNotFoundError: No module named 'websockets'` | Old install missed the dep | `pip install -U "pipecat-upliftai @ git+https://github.com/uplift-initiative/pipecat-upliftai.git@main"` |

## Support

- Issues: https://github.com/uplift-initiative/pipecat-upliftai/issues
- UpliftAI docs: https://docs.upliftai.org
- Pipecat docs: https://docs.pipecat.ai
