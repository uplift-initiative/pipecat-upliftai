"""UpliftAI plugin for Pipecat.

Public API:

- :class:`UpliftAITTSService` — WebSocket-based streaming TTS service
- :data:`OutputFormat` — supported audio output format literals
- :data:`DEFAULT_VOICE_ID`, :data:`DEFAULT_OUTPUT_FORMAT`, :data:`DEFAULT_URL`
- :data:`MIN_SPEED`, :data:`MAX_SPEED` — accepted speaking-rate bounds
"""

from pipecat_upliftai.tts import (
    DEFAULT_OUTPUT_FORMAT,
    DEFAULT_URL,
    DEFAULT_VOICE_ID,
    MAX_SPEED,
    MIN_SPEED,
    OutputFormat,
    UpliftAITTSService,
    UpliftAITTSSettings,
)

__version__ = "0.2.0"

__all__ = [
    "UpliftAITTSService",
    "UpliftAITTSSettings",
    "OutputFormat",
    "DEFAULT_VOICE_ID",
    "DEFAULT_OUTPUT_FORMAT",
    "DEFAULT_URL",
    "MIN_SPEED",
    "MAX_SPEED",
    "__version__",
]
