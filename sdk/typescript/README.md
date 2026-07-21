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
