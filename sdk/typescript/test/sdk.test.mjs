import assert from "node:assert/strict";
import test from "node:test";
import {Recorder, TraceValidationError, exactReplay, validateTrace} from "../dist/src/index.js";

const clock = () => "2026-07-20T00:00:00.000Z";

test("records and exactly replays without a live path", async () => {
  const recorder = new Recorder("test", {dataset: "real"}, clock, "run-id");
  const response = await recorder.capture("tool", "lookup", {id: 7}, () => ({name: "Ada"}));
  assert.deepEqual(response, {name: "Ada"});
  const source = recorder.finish(); const replayed = exactReplay(source, clock);
  assert.equal(replayed.live_calls, 0); assert.equal(replayed.fixture_hits, 1);
  assert.deepEqual(replayed.run.events[0].request, source.events[0].request);
  assert.deepEqual(replayed.run.events[0].response, source.events[0].response);
});

test("rejects schema drift", () => {
  assert.throws(() => validateTrace({schema_version: "2.0.0"}), TraceValidationError);
});

test("does not capture request/response content by default", async () => {
  const recorder = new Recorder("test", {}, clock, "run-id");
  await recorder.capture("tool", "lookup", {token: "sk-abcdefghijklmnopqrstuvwxyz"}, () => ({authorization: "sk-abcdefghijklmnopqrstuvwxyz"}));
  const event = recorder.finish().events[0];
  assert.equal(event.request, undefined);
  assert.equal(event.response, undefined);
  assert.ok(event.request_hash && event.response_hash);
});

test("captureContent stores content but still redacts known secret patterns", async () => {
  const recorder = new Recorder("test", {}, clock, "run-id", {captureContent: true});
  await recorder.capture("tool", "lookup", {token: "sk-abcdefghijklmnopqrstuvwxyz"}, () => ({ok: true}));
  const event = recorder.finish().events[0];
  assert.equal(JSON.stringify(event.request).includes("sk-abcdefghijklmnopqrstuvwxyz"), false);
  assert.deepEqual(event.response, {ok: true});
});

test("captureContent redacts sensitive keys outright", async () => {
  const recorder = new Recorder("test", {}, clock, "run-id", {captureContent: true});
  await recorder.capture("tool", "auth", {authorization: "plain-bearer-value"}, () => ({password: "hunter2"}));
  const event = recorder.finish().events[0];
  assert.equal(event.request.authorization, "[REDACTED]");
  assert.equal(event.response.password, "[REDACTED]");
});
