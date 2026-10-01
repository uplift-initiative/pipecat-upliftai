"""Construction smoke tests for :class:`UpliftAITTSService`.

These tests don't open any network connection — they exercise the
constructor surface and the pyproject-side wiring to catch import,
settings, and signature regressions.
"""

import asyncio

import pytest
from websockets.protocol import State

from pipecat_upliftai import (
    DEFAULT_OUTPUT_FORMAT,
    DEFAULT_VOICE_ID,
    UpliftAITTSService,
    UpliftAITTSSettings,
)


def test_constructs_with_minimal_args():
    """Service can be constructed with just an API key."""
    svc = UpliftAITTSService(api_key="dummy")
    assert svc._settings.voice == DEFAULT_VOICE_ID
    assert svc._settings.output_format == DEFAULT_OUTPUT_FORMAT


def test_settings_override_wins():
    """Caller-provided Settings fields override the defaults."""
    svc = UpliftAITTSService(
        api_key="dummy",
        settings=UpliftAITTSService.Settings(voice="some-other-voice"),
    )
    assert svc._settings.voice == "some-other-voice"
    # Unspecified fields keep defaults.
    assert svc._settings.output_format == DEFAULT_OUTPUT_FORMAT


def test_settings_class_attribute_matches_module_export():
    """``MyService.Settings`` and ``UpliftAITTSSettings`` are the same type."""
    assert UpliftAITTSService.Settings is UpliftAITTSSettings


def test_delta_settings_default_to_not_given():
    """An empty Settings() is sparse — no field is populated."""
    delta = UpliftAITTSSettings()
    given = delta.given_fields()
    assert given == {}


@pytest.mark.parametrize(
    "fmt,expected_rate",
    [
        ("PCM_22050_16", 22050),
        ("MP3_22050_32", 22050),
        ("WAV_22050_16", 22050),
        ("OGG_22050_16", 22050),
        ("ULAW_8000_8", 8000),
    ],
)
def test_output_format_implies_correct_rate(fmt, expected_rate):
    """The format → rate mapping table is consistent."""
    from pipecat_upliftai.tts import _FORMAT_SAMPLE_RATES

    assert _FORMAT_SAMPLE_RATES[fmt] == expected_rate


def _ready_service(**kwargs) -> UpliftAITTSService:
    """Build a service with the sample rate the pipeline would resolve in start().

    ``sample_rate`` stays 0 until ``start()`` negotiates it with the
    pipeline, so validation helpers need it set to be meaningful here.
    """
    svc = UpliftAITTSService(api_key="dummy", **kwargs)
    svc._sample_rate = 22050
    return svc


def test_speed_defaults_to_server_default():
    """``speed`` is unset by default so the server applies its own rate."""
    svc = UpliftAITTSService(api_key="dummy")
    assert svc._settings.speed is None


@pytest.mark.parametrize("speed", [0.5, 1.0, 1.5, 2.0])
def test_speed_accepts_supported_range(speed):
    """Speeds within UpliftAI's documented bounds validate cleanly."""
    assert _ready_service()._speed_error(speed) is None


@pytest.mark.parametrize("speed", [0.49, 2.01, 0, -1, "fast", True])
def test_speed_rejects_out_of_range(speed):
    """Out-of-range or non-numeric speeds are reported, not sent upstream."""
    assert _ready_service()._speed_error(speed) is not None


@pytest.mark.parametrize(
    "fmt", ["MP3_22050_32", "MP3_22050_128", "OGG_22050_16", "WAV_22050_16", "ULAW_8000_8"]
)
def test_non_pcm_output_formats_rejected(fmt):
    """Encoded/8-bit formats can't ride on TTSAudioRawFrame, so they're refused.

    Pipecat's raw audio frame carries 16-bit PCM; forwarding encoded bytes
    would play back as noise rather than failing loudly.
    """
    error = _ready_service()._output_format_error(fmt)
    assert error is not None and "PCM_22050_16" in error


def test_pcm_output_format_accepted():
    """The supported raw-PCM format passes validation at its native rate."""
    assert _ready_service()._output_format_error("PCM_22050_16") is None


def test_unknown_output_format_rejected():
    """A format outside UpliftAI's catalogue is refused by name."""
    assert _ready_service()._output_format_error("FLAC_44100_16") is not None


def test_sample_rate_mismatch_rejected():
    """A pipeline rate that disagrees with the wire format is refused."""
    svc = UpliftAITTSService(api_key="dummy")
    svc._sample_rate = 16000
    error = svc._output_format_error("PCM_22050_16")
    assert error is not None and "22050" in error


async def test_speed_sent_on_wire_only_when_set():
    """``speed`` rides on the synthesize message when configured, else is omitted."""
    import json

    sent: list[dict] = []

    class FakeWebsocket:
        state = State.OPEN

        async def send(self, message: str) -> None:
            sent.append(json.loads(message))

    async def drive(svc: UpliftAITTSService) -> None:
        svc._websocket = FakeWebsocket()
        # metrics need live pipeline plumbing we don't have here
        svc.start_tts_usage_metrics = lambda text: asyncio.sleep(0)
        agen = svc.run_tts("salaam", "ctx-1")
        await agen.__anext__()  # sends the request, then yields None
        await agen.aclose()  # don't block on the audio_end gate

    configured = _ready_service(settings=UpliftAITTSService.Settings(speed=1.5))
    await drive(configured)
    assert sent[-1]["speed"] == 1.5

    default = _ready_service()
    await drive(default)
    assert "speed" not in sent[-1]
    assert sent[-1]["text"] == "salaam"
