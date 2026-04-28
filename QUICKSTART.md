# Quickstart — `pipecat-upliftai`

Get a real voice agent talking in your browser in five minutes.

## Prerequisites

- Python **3.11+**
- An **UpliftAI API key** — [platform.upliftai.org/studio](https://platform.upliftai.org/studio/home)
- An **OpenAI API key** (used in the example for STT + LLM) — [platform.openai.com/api-keys](https://platform.openai.com/account/api-keys)

You can swap OpenAI for any STT/LLM Pipecat supports later — Deepgram, Anthropic, Gemini, etc. Using OpenAI here just because it's the shortest path to a working bot.

## 1. Set up the project

```bash
mkdir uplift-agent && cd uplift-agent
python -m venv .venv
source .venv/bin/activate

pip install \
  "pipecat-upliftai @ git+https://github.com/uplift-initiative/pipecat-upliftai.git@main" \
  "pipecat-ai[openai,silero,webrtc,runner]>=1.1.0" \
  python-dotenv
```

The `pipecat-ai` extras pull in OpenAI (STT + LLM), Silero VAD, Pipecat's small-WebRTC transport (browser UI), and the runner CLI.

## 2. Add your keys

```bash
cat > .env <<EOF
OPENAI_API_KEY=sk-...
UPLIFTAI_API_KEY=...
EOF
```

## 3. Save this as `agent.py`

A complete voice agent — it speaks Urdu and answers questions about Pakistan's history. Edit the `SYSTEM_INSTRUCTION` and voice if you want a different persona.

```python
import os
from pathlib import Path

from dotenv import load_dotenv
from loguru import logger

from pipecat.audio.vad.silero import SileroVADAnalyzer
from pipecat.frames.frames import LLMRunFrame
from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.runner import PipelineRunner
from pipecat.pipeline.task import PipelineParams, PipelineTask
from pipecat.processors.aggregators.llm_context import LLMContext
from pipecat.processors.aggregators.llm_response_universal import (
    LLMContextAggregatorPair,
    LLMUserAggregatorParams,
)
from pipecat.runner.types import RunnerArguments
from pipecat.runner.utils import create_transport
from pipecat.services.openai.llm import OpenAILLMService
from pipecat.services.openai.stt import OpenAISTTService
from pipecat.transports.base_transport import BaseTransport, TransportParams

from pipecat_upliftai import UpliftAITTSService

load_dotenv(dotenv_path=Path(__file__).parent / ".env", override=True)

SYSTEM_INSTRUCTION = (
    "You are a friendly Urdu-speaking assistant. Keep replies short and "
    "conversational, suitable for being spoken aloud — no emojis or markdown."
)

transport_params = {
    "webrtc": lambda: TransportParams(audio_in_enabled=True, audio_out_enabled=True),
}


async def run_bot(transport: BaseTransport, runner_args: RunnerArguments) -> None:
    stt = OpenAISTTService(
        api_key=os.environ["OPENAI_API_KEY"],
        settings=OpenAISTTService.Settings(model="gpt-4o-transcribe", language="ur"),
    )
    llm = OpenAILLMService(
        api_key=os.environ["OPENAI_API_KEY"],
        settings=OpenAILLMService.Settings(
            model="gpt-4o-mini",
            system_instruction=SYSTEM_INSTRUCTION,
        ),
    )
    tts = UpliftAITTSService(
        api_key=os.environ["UPLIFTAI_API_KEY"],
        settings=UpliftAITTSService.Settings(
            voice="v_meklc281",          # browse voices: https://docs.upliftai.org/orator_voices
            output_format="PCM_22050_16",
        ),
    )

    context = LLMContext()
    user_agg, assistant_agg = LLMContextAggregatorPair(
        context,
        user_params=LLMUserAggregatorParams(vad_analyzer=SileroVADAnalyzer()),
    )

    pipeline = Pipeline([
        transport.input(),
        stt,
        user_agg,
        llm,
        tts,
        transport.output(),
        assistant_agg,
    ])

    task = PipelineTask(
        pipeline,
        params=PipelineParams(
            audio_out_sample_rate=22050,    # MUST match the UpliftAI output_format above
            enable_metrics=True,
        ),
        idle_timeout_secs=runner_args.pipeline_idle_timeout_secs,
    )

    @transport.event_handler("on_client_connected")
    async def on_client_connected(transport, client):
        logger.info("Client connected — kicking off greeting")
        context.add_message({"role": "developer", "content": "Greet the user briefly in Urdu."})
        await task.queue_frames([LLMRunFrame()])

    @transport.event_handler("on_client_disconnected")
    async def on_client_disconnected(transport, client):
        await task.cancel()

    runner = PipelineRunner(handle_sigint=runner_args.handle_sigint)
    await runner.run(task)


async def bot(runner_args: RunnerArguments) -> None:
    transport = await create_transport(runner_args, transport_params)
    await run_bot(transport, runner_args)


if __name__ == "__main__":
    from pipecat.runner.run import main
    main()
```

## 4. Run it

```bash
python agent.py -t webrtc
```

Open **http://localhost:7860** in a browser, click "Connect", and talk to the bot. The first time you'll see a mic-permission prompt.

## What's in the pipeline?

```
[mic ► browser] ─► transport.input
                  └─► STT      (OpenAI gpt-4o-transcribe — Urdu)
                  └─► user aggregator   (Silero VAD detects end of utterance)
                  └─► LLM      (OpenAI gpt-4o-mini)
                  └─► TTS      ← UpliftAITTSService
                  └─► transport.output ─► [speaker]
                  └─► assistant aggregator
```

You can replace any block — keep `UpliftAITTSService` and swap STT/LLM/transport however you like.

## Customising the voice

```python
tts = UpliftAITTSService(
    api_key=os.environ["UPLIFTAI_API_KEY"],
    settings=UpliftAITTSService.Settings(
        voice="v_meklc281",                  # see https://docs.upliftai.org/orator_voices
        output_format="MP3_22050_64",        # or PCM_22050_16, ULAW_8000_8, etc.
        phrase_replacement_config_id=None,   # optional, server-side phrase replacement
    ),
)
```

If you change `output_format`, **also update** `audio_out_sample_rate` on `PipelineParams`:
- All `*_22050_*` formats → `22050`
- `ULAW_8000_8` (telephony) → `8000`

`start()` will raise a clear `ValueError` if they don't match — fail-fast, no silent garbled audio.

## Going to production transports

The example uses Pipecat's small-WebRTC server (good for dev). To run on Daily, Twilio, etc., add to `transport_params` and run with the matching `-t` flag:

```python
from pipecat.transports.daily.transport import DailyParams
from pipecat.transports.websocket.fastapi import FastAPIWebsocketParams

transport_params = {
    "webrtc": lambda: TransportParams(audio_in_enabled=True, audio_out_enabled=True),
    "daily":  lambda: DailyParams(audio_in_enabled=True, audio_out_enabled=True),
    "twilio": lambda: FastAPIWebsocketParams(audio_in_enabled=True, audio_out_enabled=True),
}
```

```bash
python agent.py -t daily       # needs DAILY_API_KEY
python agent.py -t twilio -x your.ngrok.io
```

## Troubleshooting

| Symptom | Fix |
| --- | --- |
| `ValueError: sample_rate=… does not match output_format=…` | Set `audio_out_sample_rate` on `PipelineParams` to match the format (22050 for PCM/WAV/MP3/OGG, 8000 for ULAW). |
| `Unable to connect to UpliftAI TTS: 401` | Check `UPLIFTAI_API_KEY` is set and valid. |
| `KeyError: 'OPENAI_API_KEY'` | Your `.env` isn't being loaded — confirm `.env` lives next to `agent.py` and contains the key. |
| Bot greets but never replies after you talk | Likely STT issue — confirm `OPENAI_API_KEY` and your mic is producing audio (most browsers show a mic indicator on the tab). |
| Audio sounds garbled / interleaved | Should not happen with the gate fix; if it does, please file an issue with the agent log. |

## Support

- **Issues**: https://github.com/uplift-initiative/pipecat-upliftai/issues
- **UpliftAI docs**: https://docs.upliftai.org
- **Pipecat docs**: https://docs.pipecat.ai
