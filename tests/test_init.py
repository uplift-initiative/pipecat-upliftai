"""Construction smoke tests for :class:`UpliftAITTSService`.

These tests don't open any network connection — they exercise the
constructor surface and the pyproject-side wiring to catch import,
settings, and signature regressions.
"""

import pytest

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
