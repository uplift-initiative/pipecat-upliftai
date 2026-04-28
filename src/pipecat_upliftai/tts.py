#
# Copyright (c) 2026, UpliftAI
#
# SPDX-License-Identifier: BSD-2-Clause
#

"""UpliftAI text-to-speech service for Pipecat.

A WebSocket-based TTS service against UpliftAI's plain-WebSocket
multi-stream endpoint. Each ``synthesize`` request is one-shot — the
server responds with ``audio_start``, a stream of ``audio`` chunks, and
a final ``audio_end`` per request. Multiple requests can be in flight
concurrently and are routed back to the right audio context by
``requestId``.

UpliftAI API reference: https://docs.upliftai.org
"""

import asyncio
import base64
import json
import uuid
from collections.abc import AsyncGenerator
from dataclasses import dataclass, field
from typing import Any, Literal

from loguru import logger
from pipecat.frames.frames import (
    CancelFrame,
    EndFrame,
    ErrorFrame,
    Frame,
    StartFrame,
    TTSAudioRawFrame,
    TTSStoppedFrame,
)
from pipecat.services.settings import NOT_GIVEN, TTSSettings, _NotGiven
from pipecat.services.tts_service import TextAggregationMode, WebsocketTTSService
from pipecat.transcriptions.language import Language
from pipecat.utils.tracing.service_decorators import traced_tts

try:
    from websockets.asyncio.client import connect as websocket_connect
    from websockets.protocol import State
except ModuleNotFoundError as e:
    logger.error(f"Exception: {e}")
    logger.error("In order to use UpliftAI, you need to `pip install pipecat-upliftai`.")
    raise Exception(f"Missing module: {e}")


OutputFormat = Literal[
    "PCM_22050_16",
    "WAV_22050_16",
    "WAV_22050_32",
    "MP3_22050_32",
    "MP3_22050_64",
    "MP3_22050_128",
    "OGG_22050_16",
    "ULAW_8000_8",
]

DEFAULT_URL = "wss://api.upliftai.org/v1/text-to-speech/multi-stream"
DEFAULT_VOICE_ID = "v_meklc281"
DEFAULT_OUTPUT_FORMAT: OutputFormat = "PCM_22050_16"

# UpliftAI's wire formats hard-lock to specific sample rates. The pipeline
# rate must match — we fail fast in start() rather than silently overriding,
# because most output transports trust the rate carried on TTSAudioRawFrame.
_FORMAT_SAMPLE_RATES: dict[str, int] = {
    "PCM_22050_16": 22050,
    "WAV_22050_16": 22050,
    "WAV_22050_32": 22050,
    "MP3_22050_32": 22050,
    "MP3_22050_64": 22050,
    "MP3_22050_128": 22050,
    "OGG_22050_16": 22050,
    "ULAW_8000_8": 8000,
}


@dataclass
class UpliftAITTSSettings(TTSSettings):
    """Runtime-updatable settings for UpliftAITTSService.

    Parameters:
        output_format: Audio wire format. The implied sample rate is
            22050 Hz for PCM/WAV/MP3/OGG and 8000 Hz for ULAW; it must
            match the pipeline's ``audio_out_sample_rate``.
        phrase_replacement_config_id: Optional ID of a server-side
            phrase-replacement configuration to apply during synthesis.
    """

    output_format: OutputFormat | None | _NotGiven = field(default_factory=lambda: NOT_GIVEN)
    phrase_replacement_config_id: str | None | _NotGiven = field(default_factory=lambda: NOT_GIVEN)


class UpliftAITTSService(WebsocketTTSService):
    """UpliftAI TTS service over a streaming WebSocket connection.

    Sends each synthesis turn as a one-shot ``synthesize`` request and
    streams the resulting audio chunks back through a single multiplexed
    WebSocket. Multiple concurrent requests are routed to the correct
    Pipecat audio context by tracking ``requestId``.

    Supported features:

    - Streaming PCM, WAV, MP3, OGG, or ULAW output
    - Concurrent requests multiplexed on a single connection
    - Server-side cancellation on bot interruption
    - Optional server-side phrase replacement

    Event handlers (inherited from ``WebsocketTTSService``):

    - on_connected: Called when the WebSocket has connected.
    - on_disconnected: Called when the WebSocket has disconnected.
    - on_connection_error: Called when a WebSocket connection error occurs.
    """

    Settings = UpliftAITTSSettings
    _settings: Settings

    def __init__(
        self,
        *,
        api_key: str,
        url: str = DEFAULT_URL,
        sample_rate: int | None = None,
        settings: Settings | None = None,
        text_aggregation_mode: TextAggregationMode | None = None,
        **kwargs,
    ) -> None:
        """Initialize the UpliftAI TTS service.

        Args:
            api_key: UpliftAI API key. Sent as a Bearer token on the
                WebSocket upgrade request.
            url: WebSocket URL for the UpliftAI multi-stream endpoint.
            sample_rate: Output sample rate in Hz. If ``None``, inherits
                from the pipeline. Must match the rate implied by
                ``output_format`` (22050 for PCM/WAV/MP3/OGG, 8000 for
                ULAW); ``start()`` raises ``ValueError`` on mismatch.
            settings: Runtime-updatable settings. Caller-provided fields
                override the defaults; unspecified fields keep their
                defaults.
            text_aggregation_mode: How to aggregate incoming text before
                synthesis. Defaults to ``TextAggregationMode.SENTENCE``.
            **kwargs: Additional arguments passed to the parent service.
        """
        # UpliftAI has no notion of an LLM-style "model" and its voice
        # IDs are language-locked, so model/language stay as None in
        # store mode (see ServiceSettings docs).
        default_settings = self.Settings(
            model=None,
            voice=DEFAULT_VOICE_ID,
            language=None,
            output_format=DEFAULT_OUTPUT_FORMAT,
            phrase_replacement_config_id=None,
        )

        if settings is not None:
            default_settings.apply_update(settings)

        super().__init__(
            text_aggregation_mode=text_aggregation_mode,
            # UpliftAI doesn't expose word alignment, so the base class
            # can push TTSTextFrames immediately.
            push_text_frames=True,
            # We push TTSStoppedFrame ourselves once a context is fully
            # drained (see _maybe_close_context).
            push_stop_frames=False,
            # Let the base class create audio contexts and push
            # TTSStartedFrame on first text.
            push_start_frame=True,
            pause_frame_processing=False,
            sample_rate=sample_rate,
            settings=default_settings,
            **kwargs,
        )

        self._api_key = api_key
        self._url = url

        # Routing: each in-flight UpliftAI request maps to a single
        # Pipecat audio context. Multiple requests can share a context
        # (one synthesize per sentence within a turn).
        self._request_to_context: dict[str, str] = {}
        # Active request_ids per context. A context is "fully drained"
        # only when this set goes empty *and* the base class has marked
        # the context done via flush_audio / on_turn_context_completed.
        self._context_inflight: dict[str, set[str]] = {}
        # Contexts the base class has signalled as done. We hold off on
        # TTSStoppedFrame until the corresponding inflight set drains.
        self._context_done: set[str] = set()
        # Per-request "audio fully delivered" gate. ``run_tts`` blocks on
        # this before returning so subsequent calls within the same
        # context can't interleave audio. UpliftAI is one-shot per
        # request — sending two synthesize messages concurrently would
        # produce two server-side streams whose chunks arrive
        # interleaved on the wire, which would garble the audio context
        # queue. Serializing on audio_end keeps order intact.
        self._request_done_events: dict[str, asyncio.Event] = {}

        self._receive_task: asyncio.Task | None = None

    def can_generate_metrics(self) -> bool:
        """Whether this service emits processing metrics.

        Returns:
            ``True`` — UpliftAI TTS supports metrics generation.
        """
        return True

    def language_to_service_language(self, language: Language) -> str | None:
        """Convert a ``Language`` enum to UpliftAI's representation.

        UpliftAI voices are language-locked at the voice level, so
        explicit language selection is not part of the synthesize
        request.

        Args:
            language: The language to convert.

        Returns:
            ``None`` — language is encoded in the voice ID, not as a
            separate field.
        """
        return None

    async def start(self, frame: StartFrame) -> None:
        """Start the UpliftAI TTS service.

        Args:
            frame: The start frame carrying pipeline-level audio params.

        Raises:
            ValueError: If the pipeline's sample rate doesn't match the
                rate implied by ``output_format``. UpliftAI's wire
                format hard-locks the rate, so mismatches must be
                resolved at configuration time.
        """
        await super().start(frame)
        self._validate_sample_rate(self._settings.output_format)
        await self._connect()

    async def stop(self, frame: EndFrame) -> None:
        """Stop the UpliftAI TTS service.

        Args:
            frame: The end frame.
        """
        await super().stop(frame)
        await self._disconnect()

    async def cancel(self, frame: CancelFrame) -> None:
        """Cancel the UpliftAI TTS service.

        Args:
            frame: The cancel frame.
        """
        await super().cancel(frame)
        await self._disconnect()

    async def flush_audio(self, context_id: str | None = None) -> None:
        """Mark a context as receiving no more text.

        UpliftAI completes its own per-request stream on ``audio_end``,
        so there's no flush message to send. This override only
        bookkeeps: once the base class signals end-of-text for a
        context and all in-flight requests for that context have drained,
        we push ``TTSStoppedFrame`` and remove the audio context.

        Args:
            context_id: The context to mark done. If ``None``, falls
                back to the active context.
        """
        ctx_id = context_id or self.get_active_audio_context_id()
        if not ctx_id:
            return
        self._context_done.add(ctx_id)
        await self._maybe_close_context(ctx_id)

    async def on_audio_context_interrupted(self, context_id: str) -> None:
        """Cancel all in-flight UpliftAI requests for an interrupted context.

        Args:
            context_id: The interrupted audio context.
        """
        await self.stop_all_metrics()
        cancelled = list(self._context_inflight.get(context_id, ()))
        for request_id in cancelled:
            await self._send_cancel(request_id)
        # Release any run_tts calls blocked on these requests' gates so
        # the pipeline doesn't hang waiting for an audio_end that won't
        # arrive (we cancelled it).
        for request_id in cancelled:
            self._signal_request_done(request_id)
        self._context_inflight.pop(context_id, None)
        self._context_done.discard(context_id)
        # Drop any lingering request → context mappings for this context.
        self._request_to_context = {
            rid: cid for rid, cid in self._request_to_context.items() if cid != context_id
        }
        await super().on_audio_context_interrupted(context_id)

    async def _update_settings(self, update: TTSSettings) -> dict[str, Any]:
        """Apply a settings delta.

        Most UpliftAI knobs (voice, output_format, phrase_replacement_config_id)
        take effect on the next ``synthesize`` request — no reconnect
        needed. ``output_format`` changes are gated: if the new format
        implies a sample rate that doesn't match the current pipeline
        rate, the change is rolled back and an error is pushed.

        Args:
            update: A TTS settings delta.

        Returns:
            Dict mapping changed field names to their pre-update values.
        """
        changed = await super()._update_settings(update)
        if not changed:
            return changed

        if "output_format" in changed:
            new_format = self._settings.output_format
            expected = _FORMAT_SAMPLE_RATES.get(new_format)
            if expected is None or expected != self.sample_rate:
                # Roll back to the pre-update value.
                self._settings.output_format = changed["output_format"]
                await self.push_error(
                    error_msg=(
                        f"{self}: refusing to switch output_format to "
                        f"{new_format!r} — implied rate {expected} does not "
                        f"match pipeline sample_rate {self.sample_rate}."
                    )
                )
                changed.pop("output_format", None)

        return changed

    async def _connect(self) -> None:
        await super()._connect()
        await self._connect_websocket()
        if self._websocket and not self._receive_task:
            self._receive_task = self.create_task(self._receive_task_handler(self._report_error))

    async def _disconnect(self) -> None:
        await super()._disconnect()
        if self._receive_task:
            await self.cancel_task(self._receive_task)
            self._receive_task = None
        await self._disconnect_websocket()

    async def _connect_websocket(self) -> None:
        try:
            if self._websocket and self._websocket.state is State.OPEN:
                return
            logger.debug("Connecting to UpliftAI TTS")
            self._websocket = await websocket_connect(
                self._url,
                additional_headers={"Authorization": f"Bearer {self._api_key}"},
            )
            await self._call_event_handler("on_connected")
        except Exception as e:
            self._websocket = None
            await self.push_error(error_msg=f"Unable to connect to UpliftAI TTS: {e}", exception=e)
            await self._call_event_handler("on_connection_error", f"{e}")

    async def _disconnect_websocket(self) -> None:
        try:
            await self.stop_all_metrics()
            if self._websocket:
                logger.debug("Disconnecting from UpliftAI TTS")
                await self._websocket.close()
        except Exception as e:
            await self.push_error(error_msg=f"Error closing UpliftAI websocket: {e}", exception=e)
        finally:
            await self.remove_active_audio_context()
            self._request_to_context.clear()
            self._context_inflight.clear()
            self._context_done.clear()
            # Unblock any run_tts calls waiting on a gate so they can
            # return cleanly rather than hanging until cancellation.
            self._release_all_pending_requests()
            self._websocket = None
            await self._call_event_handler("on_disconnected")

    def _get_websocket(self):
        if self._websocket:
            return self._websocket
        raise Exception("Websocket not connected")

    def _validate_sample_rate(self, output_format: str | None) -> None:
        """Hard-error if the pipeline rate doesn't match the format.

        Args:
            output_format: The configured UpliftAI output format.

        Raises:
            ValueError: On any mismatch (including unknown formats).
        """
        expected = _FORMAT_SAMPLE_RATES.get(output_format) if output_format else None
        if expected is None:
            raise ValueError(
                f"{self}: unsupported output_format={output_format!r}. "
                f"Supported: {sorted(_FORMAT_SAMPLE_RATES.keys())}."
            )
        if self.sample_rate != expected:
            raise ValueError(
                f"{self}: sample_rate={self.sample_rate} does not match "
                f"output_format={output_format!r} (UpliftAI emits audio at "
                f"{expected} Hz). Either set audio_out_sample_rate={expected} "
                f"on PipelineParams, pass sample_rate={expected} to "
                f"{type(self).__name__}(...), or pick an output_format whose "
                f"rate matches your pipeline."
            )

    async def _send_cancel(self, request_id: str) -> None:
        """Send a cancel message for a single in-flight request."""
        if not self._websocket or self._websocket.state is not State.OPEN:
            return
        try:
            await self._websocket.send(json.dumps({"type": "cancel", "requestId": request_id}))
        except Exception as e:
            logger.warning(f"{self}: failed to cancel request {request_id}: {e}")

    async def _maybe_close_context(self, context_id: str) -> None:
        """Push TTSStoppedFrame and drop the context once fully drained.

        A context is fully drained when (a) ``flush_audio`` /
        ``on_turn_context_completed`` has marked it done, and (b) every
        in-flight UpliftAI request bound to it has received its
        ``audio_end`` (or errored).
        """
        if context_id not in self._context_done:
            return
        if self._context_inflight.get(context_id):
            return
        if self.audio_context_available(context_id):
            await self.append_to_audio_context(context_id, TTSStoppedFrame(context_id=context_id))
            await self.remove_audio_context(context_id)
        self._context_inflight.pop(context_id, None)
        self._context_done.discard(context_id)

    def _retire_request(self, request_id: str) -> str | None:
        """Drop request → context bookkeeping; return the context_id (if any)."""
        ctx_id = self._request_to_context.pop(request_id, None)
        if ctx_id is not None:
            inflight = self._context_inflight.get(ctx_id)
            if inflight is not None:
                inflight.discard(request_id)
                if not inflight:
                    self._context_inflight.pop(ctx_id, None)
        return ctx_id

    def _signal_request_done(self, request_id: str) -> None:
        """Release any ``run_tts`` call blocked on this request's gate."""
        event = self._request_done_events.pop(request_id, None)
        if event is not None:
            event.set()
            logger.trace(f"{self}: gate released for request {request_id}")

    def _release_all_pending_requests(self) -> None:
        """Set every pending request gate; used on disconnect/teardown."""
        for event in self._request_done_events.values():
            event.set()
        self._request_done_events.clear()

    async def _receive_messages(self) -> None:
        """Demultiplex UpliftAI WebSocket messages by ``requestId``.

        Audio chunks are appended to the matching audio context. Errors
        push an ``ErrorFrame`` and hard-close the context. ``audio_end``
        retires the request and (if no other in-flight requests remain
        for the context and the base class has marked the context done)
        closes it.
        """
        async for message in self._get_websocket():
            try:
                msg = json.loads(message)
            except json.JSONDecodeError:
                logger.warning(f"{self}: received non-JSON UpliftAI message: {message!r}")
                continue

            msg_type = msg.get("type")
            request_id = msg.get("requestId")

            if msg_type == "audio":
                ctx_id = self._request_to_context.get(request_id)
                audio_b64 = msg.get("audio")
                if audio_b64 and ctx_id and self.audio_context_available(ctx_id):
                    await self.stop_ttfb_metrics()
                    audio = base64.b64decode(audio_b64)
                    frame = TTSAudioRawFrame(audio, self.sample_rate, 1, context_id=ctx_id)
                    await self.append_to_audio_context(ctx_id, frame)

            elif msg_type == "audio_end":
                ctx_id = self._retire_request(request_id)
                self._signal_request_done(request_id)
                if ctx_id is not None:
                    await self._maybe_close_context(ctx_id)

            elif msg_type == "error":
                code = msg.get("code", "unknown")
                err_msg = msg.get("message", "")
                await self.push_error(
                    error_msg=f"UpliftAI TTS error {code} (request {request_id}): {err_msg}"
                )
                ctx_id = self._retire_request(request_id)
                self._signal_request_done(request_id)
                if ctx_id is not None and self.audio_context_available(ctx_id):
                    await self.append_to_audio_context(ctx_id, TTSStoppedFrame(context_id=ctx_id))
                    await self.remove_audio_context(ctx_id)
                    self._context_inflight.pop(ctx_id, None)
                    self._context_done.discard(ctx_id)

            elif msg_type in ("ready", "audio_start"):
                # `ready` is purely informational; `audio_start` arrives
                # before the first audio chunk and the base class has
                # already pushed TTSStartedFrame on first text.
                continue

    @traced_tts
    async def run_tts(self, text: str, context_id: str) -> AsyncGenerator[Frame | None, None]:
        """Send one synthesize request and route the audio back asynchronously.

        Each call generates a fresh ``requestId`` and registers it
        against ``context_id`` so the receive loop can deliver audio to
        the right place. Audio frames are produced out-of-band by the
        receive task; this generator yields ``None``.

        Args:
            text: The text to synthesize.
            context_id: The Pipecat audio context this synthesis belongs to.

        Yields:
            ``None`` — audio is appended to the audio context by the
            receive task. ``ErrorFrame`` on send failure.
        """
        if self._is_streaming_tokens:
            logger.trace(f"{self}: Generating TTS [{text}]")
        else:
            logger.debug(f"{self}: Generating TTS [{text}]")

        try:
            if not self._websocket or self._websocket.state is State.CLOSED:
                await self._connect()

            request_id = uuid.uuid4().hex
            done_event = asyncio.Event()
            self._request_done_events[request_id] = done_event
            self._request_to_context[request_id] = context_id
            self._context_inflight.setdefault(context_id, set()).add(request_id)
            # New text means the context is no longer "done" — clear any
            # stale marker from a prior flush within the same context.
            self._context_done.discard(context_id)

            msg: dict[str, Any] = {
                "type": "synthesize",
                "requestId": request_id,
                "text": text,
                "voiceId": self._settings.voice,
                "outputFormat": self._settings.output_format,
            }
            if self._settings.phrase_replacement_config_id:
                msg["phraseReplacementConfigId"] = self._settings.phrase_replacement_config_id

            try:
                await self._get_websocket().send(json.dumps(msg))
                await self.start_tts_usage_metrics(text)
            except Exception as e:
                # Roll back bookkeeping for this request before reconnecting.
                self._request_done_events.pop(request_id, None)
                self._retire_request(request_id)
                yield ErrorFrame(error=f"UpliftAI send failed: {e}")
                yield TTSStoppedFrame(context_id=context_id)
                await self._disconnect()
                await self._connect()
                return
            yield None

            # Block until this request's audio has fully streamed back
            # (audio_end, error, interrupt, or disconnect). Without this
            # gate, the next run_tts call within the same context would
            # send a second synthesize message immediately; UpliftAI runs
            # both server-side streams concurrently and their audio
            # chunks would interleave in this context's queue, garbling
            # playback.
            await done_event.wait()
        except Exception as e:
            yield ErrorFrame(error=f"UpliftAI TTS error: {e}")
