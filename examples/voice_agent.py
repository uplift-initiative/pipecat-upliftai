"""Pipecat voice agent example using UpliftAI TTS.

A Pakistan-history teacher who speaks conversational Urdu. Run with::

    python voice_agent.py -t webrtc      # browser UI on http://localhost:7860
    python voice_agent.py -t daily       # Daily room (needs DAILY_API_KEY)
    python voice_agent.py -t twilio -x your.ngrok.io  # Twilio telephony

Required environment variables:

- ``OPENAI_API_KEY``    — for STT and LLM
- ``UPLIFTAI_API_KEY``  — for TTS
"""

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
from pipecat.transports.daily.transport import DailyParams
from pipecat.transports.websocket.fastapi import FastAPIWebsocketParams

from pipecat_upliftai import UpliftAITTSService

load_dotenv(dotenv_path=Path(__file__).parent / ".env", override=True)


AUDIO_OUT_SAMPLE_RATE = 22050  # matches PCM_22050_16

SYSTEM_INSTRUCTION = """
# Pakistan History Voice Assistant

## Core Identity
You are a knowledgeable Pakistani who answers questions about Pakistan's history.
You are a teacher who speaks in conversational Urdu.

## Language Rules
- Use Pakistani Urdu only (proper Urdu script, no Roman Urdu)
- Female perspective (میں بتاتی ہوں، سناتی ہوں، میری رائے میں)
- Gender-neutral for user (آپ جانتے ہوں گے، آپ کو یاد ہوگا)
- Simple, conversational language
- Avoid English except for widely known terms (Congress, etc.)

## Response Style
- Tell history like stories, not dry facts
- Keep responses concise (2-3 sentences unless asked for detail)
- Be balanced and factual about sensitive topics
- Write as continuous oral narration - no symbols or bullet points
- For dates: "انیس سو سینتالیس" not "1947"
"""


transport_params = {
    "daily": lambda: DailyParams(audio_in_enabled=True, audio_out_enabled=True),
    "twilio": lambda: FastAPIWebsocketParams(audio_in_enabled=True, audio_out_enabled=True),
    "webrtc": lambda: TransportParams(audio_in_enabled=True, audio_out_enabled=True),
}


async def run_bot(transport: BaseTransport, runner_args: RunnerArguments) -> None:
    logger.info("Starting Pipecat × UpliftAI voice bot")

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
            voice="v_meklc281",
            output_format="PCM_22050_16",
        ),
    )

    context = LLMContext()
    user_aggregator, assistant_aggregator = LLMContextAggregatorPair(
        context,
        user_params=LLMUserAggregatorParams(vad_analyzer=SileroVADAnalyzer()),
    )

    pipeline = Pipeline(
        [
            transport.input(),
            stt,
            user_aggregator,
            llm,
            tts,
            transport.output(),
            assistant_aggregator,
        ]
    )
    task = PipelineTask(
        pipeline,
        params=PipelineParams(
            audio_out_sample_rate=AUDIO_OUT_SAMPLE_RATE,
            enable_metrics=True,
            enable_usage_metrics=True,
        ),
        idle_timeout_secs=runner_args.pipeline_idle_timeout_secs,
    )

    @transport.event_handler("on_client_connected")
    async def on_client_connected(transport, client):
        logger.info("Client connected")
        context.add_message(
            {
                "role": "developer",
                "content": (
                    "Greet the user briefly in Urdu and offer to discuss any chapter "
                    "of Pakistan's history they're curious about."
                ),
            }
        )
        await task.queue_frames([LLMRunFrame()])

    @transport.event_handler("on_client_disconnected")
    async def on_client_disconnected(transport, client):
        logger.info("Client disconnected")
        await task.cancel()

    runner = PipelineRunner(handle_sigint=runner_args.handle_sigint)
    await runner.run(task)


async def bot(runner_args: RunnerArguments) -> None:
    """Pipecat Cloud / runner entry point."""
    transport = await create_transport(runner_args, transport_params)
    await run_bot(transport, runner_args)


if __name__ == "__main__":
    from pipecat.runner.run import main

    main()
