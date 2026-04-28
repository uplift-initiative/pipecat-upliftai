# Changelog

All notable changes to `pipecat-upliftai` are documented here. The format
follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the
project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.1.0] — 2026-04-28

### Added

- Initial release of `UpliftAITTSService`, a streaming WebSocket TTS service
  for [Pipecat](https://github.com/pipecat-ai/pipecat) backed by UpliftAI's
  multi-stream endpoint.
- Supported output formats: PCM, WAV, MP3, OGG, ULAW.
- Concurrent request multiplexing on a single WebSocket connection.
- Server-side cancellation on bot interruption.
- Per-request `audio_end` gate ensures in-order audio across sentence
  boundaries (avoids interleaving on UpliftAI's one-shot wire protocol).
- Optional server-side phrase replacement via `phrase_replacement_config_id`.
