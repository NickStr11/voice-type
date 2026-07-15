# VoiceType Resident Whisper Warmup Design

Date: 2026-07-15

## Goal

Remove the 11-17 second cold-start delay from ordinary dictation while keeping
the protections added after the accidental 3.5-hour recording and preserving
safe recovery from invalid Vulkan contexts after sleep.

## Chosen approach

Keep the managed `whisper-server` resident during ordinary idle time. Start its
warmup when VoiceType starts. After a real suspend/resume gap, stop the old
server and immediately start a fresh server in the background.

Rejected alternatives:

- Increasing the 120-second idle timeout only postpones the same cold start.
- Keeping lazy warmup at recording start still makes short dictations wait for
  model and Vulkan initialization.

## Runtime behavior

1. Local STT initialization starts `whisper-server` warmup in the background.
2. Ordinary idle time does not stop a healthy managed server.
3. A detected suspend/resume wall-clock gap discards the old Vulkan process and
   immediately starts a replacement.
4. A recording may request warmup again; the existing lock/thread guard keeps
   this idempotent.
5. Shutdown still stops the managed server.

## Preserved protections

- Keep the 15-minute maximum recording duration.
- Keep stale temporary audio/output cleanup.
- Keep server retry, Vulkan CLI retry, and final CPU fallback behavior.

## Error handling

- Resume restart remains best-effort and must not kill the watcher thread.
- If server startup fails, the existing CLI GPU and CPU fallback chain remains
  responsible for delivering a transcript.
- No idle watcher may terminate a server during warmup, recording, or inference.

## Tests

- A new client begins server warmup when local binaries/model are available.
- Ordinary watcher ticks do not stop a healthy idle server.
- A resume gap stops the stale server and starts a replacement.
- Existing recording-limit, temp-cleanup, server retry, and fallback tests stay
  green.

## Success criteria

- After normal startup, the health endpoint becomes ready before the first
  dictation whenever startup time permits.
- Waiting more than two minutes does not remove the resident server.
- After simulated resume, a fresh server is warmed without waiting for the next
  transcription request.
- Focused tests, the full test suite, Ruff, and Pyright pass.
