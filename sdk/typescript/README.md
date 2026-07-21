# ReplayGuard TypeScript SDK

The SDK records and exactly replays ReplayGuard trace schema `1.0.0` in Node.js 20+ and modern
browsers. It has no runtime dependencies.

```ts
import {Recorder, exactReplay} from "@replayguard/sdk";

const recorder = new Recorder("agent-run");
const result = await recorder.capture("tool", "weather.lookup", {city: "Paris"}, callWeather);
const trace = recorder.finish();
const replay = exactReplay(trace); // fixture-only: live_calls is always 0
```

`validateTrace` checks the cross-language v1 contract before replay. Python and TypeScript
conformance tests use checksum-pinned BFCL v4 and tau2-bench records from the repository's
public-data corpus.

## Privacy by default

`Recorder.capture()` never persists real request/response content unless you opt in. By
default only a redacted-then-hashed `request_hash`/`response_hash` is kept on each event, and
known secret patterns (API keys, bearer tokens) plus sensitive keys (`authorization`,
`password`, `token`, etc.) are stripped from anything captured — matching the Python SDK's
`capture_content` convention.

```ts
const recorder = new Recorder("agent-run", {}, undefined, undefined, {captureContent: true});
```

Redaction is best-effort: it recognizes a fixed set of key names and secret-string patterns,
not arbitrary sensitive content. `Recorder.event()` is the lower-level fixture-building
primitive (used by the conformance tooling to construct known-good traces) and always stores
what you pass it verbatim — use `capture()` for live instrumentation of real agent traffic.
