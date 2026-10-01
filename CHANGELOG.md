# Changelog

All notable changes to `pipecat-upliftai` are documented here. The format
follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the
project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.2.0] — 2026-10-01

### Added

- `speed` setting for speaking-rate control (0.5–2.0, 1.0 is the normal rate).
  Sent on each synthesize request and updatable at runtime; omitted entirely
  when unset so the server default applies.

### Changed

- Require Pipecat 1.8.0+ (`pipecat.utils.types.NotGiven` replaced the private
  `pipecat.services.settings._NotGiven`). Verified against Pipecat 1.12.0.

### Fixed

- Reject non-PCM output formats at configuration time instead of emitting
  unplayable audio. Pipecat's `TTSAudioRawFrame` carries raw 16-bit PCM and
  this service forwards UpliftAI's bytes unchanged, so MP3/OGG/WAV/ULAW were
  being interpreted as PCM samples and played back as noise. Telephony
  pipelines are unaffected: Pipecat's serializers convert PCM to u-law at the
  transport edge.

## [0.1.0] — 2026-04-28

### Added

- Initial release of `UpliftAITTSService`, a streaming WebSocket TTS service
  for [Pipecat](https://github.com/pipecat-ai/pipecat) backed by UpliftAI's
  multi-stream endpoint.
- Supported output formats: PCM, WAV, MP3, OGG, ULAW (narrowed to PCM in 0.2.0).
- Concurrent request multiplexing on a single WebSocket connection.
- Server-side cancellation on bot interruption.
- Per-request `audio_end` gate ensures in-order audio across sentence
  boundaries (avoids interleaving on UpliftAI's one-shot wire protocol).
- Optional server-side phrase replacement via `phrase_replacement_config_id`.
