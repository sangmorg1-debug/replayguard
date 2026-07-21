export const SCHEMA_VERSION = "1.0.0" as const;

export const EVENT_KINDS = ["run", "conversation", "agent_step", "model", "retrieval", "tool_proposal",
  "authorization", "tool", "artifact", "evaluation", "error"] as const;
export type EventKind = typeof EVENT_KINDS[number];
export type JsonValue = null | boolean | number | string | JsonValue[] | {[key: string]: JsonValue};

export interface TraceEvent {
  id: string; kind: EventKind; name: string; parent_id: string | null; started_at: string;
  ended_at: string | null; status: string; attributes: Record<string, JsonValue>;
  request?: JsonValue; response?: JsonValue; request_hash?: string | null; response_hash?: string | null;
  latency_ms?: number | null; cost_usd?: number | null; usage: Record<string, number>;
  error?: Record<string, JsonValue> | null;
}

export interface TraceRun {
  id: string; name: string; schema_version: typeof SCHEMA_VERSION; created_at: string;
  ended_at: string | null; status: string; attributes: Record<string, JsonValue>; events: TraceEvent[];
}

export type EventInput = Pick<TraceEvent, "kind" | "name"> & Partial<Omit<TraceEvent, "kind" | "name">>;
export type Clock = () => string;

const now: Clock = () => new Date().toISOString();
const identifier = () => globalThis.crypto.randomUUID().replaceAll("-", "");
const object = (value: unknown): value is Record<string, unknown> => value !== null && typeof value === "object" && !Array.isArray(value);
const date = (value: unknown): value is string => typeof value === "string" && !Number.isNaN(Date.parse(value));

const REDACTED = "[REDACTED]";
const SENSITIVE_KEYS = new Set(["authorization", "api_key", "apikey", "password", "passwd", "secret",
  "token", "access_token", "refresh_token"]);
const SECRET_PATTERNS: RegExp[] = [
  /\bsk-[A-Za-z0-9_-]{16,}\b/g,
  /\bgh[pousr]_[A-Za-z0-9]{20,}\b/g,
  /\b(?:AKIA|ASIA)[A-Z0-9]{16}\b/g,
  /\bBearer\s+[A-Za-z0-9._~+/=-]{12,}/gi,
];

function redact(value: JsonValue | undefined): JsonValue | undefined {
  if (value === undefined) return undefined;
  if (Array.isArray(value)) return value.map(item => redact(item) as JsonValue);
  if (object(value)) {
    const result: Record<string, JsonValue> = {};
    for (const [key, item] of Object.entries(value))
      result[key] = SENSITIVE_KEYS.has(key.toLowerCase()) ? REDACTED : (redact(item as JsonValue) as JsonValue);
    return result;
  }
  if (typeof value !== "string") return value;
  return SECRET_PATTERNS.reduce((text, pattern) => text.replace(pattern, REDACTED), value);
}

async function digest(value: JsonValue): Promise<string> {
  const bytes = new TextEncoder().encode(JSON.stringify(value));
  const hash = await globalThis.crypto.subtle.digest("SHA-256", bytes);
  return Array.from(new Uint8Array(hash)).map(byte => byte.toString(16).padStart(2, "0")).join("");
}

export class TraceValidationError extends Error {}

export function validateTrace(value: unknown): asserts value is TraceRun {
  if (!object(value)) throw new TraceValidationError("trace must be an object");
  for (const key of ["id", "name", "schema_version", "created_at", "status", "events"])
    if (!(key in value)) throw new TraceValidationError(`trace missing ${key}`);
  if (typeof value.id !== "string" || typeof value.name !== "string" || value.schema_version !== SCHEMA_VERSION)
    throw new TraceValidationError("invalid trace identity or schema_version");
  if (!date(value.created_at) || !(value.ended_at === null || value.ended_at === undefined || date(value.ended_at)))
    throw new TraceValidationError("invalid trace timestamp");
  if (typeof value.status !== "string" || (value.attributes !== undefined && !object(value.attributes)) || !Array.isArray(value.events))
    throw new TraceValidationError("invalid trace status, attributes, or events");
  for (const [index, event] of value.events.entries()) {
    if (!object(event)) throw new TraceValidationError(`event ${index} must be an object`);
    if (typeof event.id !== "string" || typeof event.name !== "string" || !EVENT_KINDS.includes(event.kind as EventKind))
      throw new TraceValidationError(`event ${index} has invalid identity or kind`);
    if (!date(event.started_at) || !(event.ended_at === null || event.ended_at === undefined || date(event.ended_at)))
      throw new TraceValidationError(`event ${index} has invalid timestamp`);
    if (typeof event.status !== "string" || !object(event.attributes) || !object(event.usage))
      throw new TraceValidationError(`event ${index} has invalid status, attributes, or usage`);
    if (Object.values(event.usage).some(item => !Number.isInteger(item)))
      throw new TraceValidationError(`event ${index} usage must contain integers`);
  }
}

export interface RecorderOptions {
  /** Persist real request/response content on captured events. Off by default: only
   *  redacted-then-hashed content is kept, matching the Python SDK's privacy-by-default posture. */
  captureContent?: boolean;
}

export class Recorder {
  readonly run: TraceRun;
  private readonly captureContent: boolean;
  constructor(name: string, attributes: Record<string, JsonValue> = {}, private readonly clock: Clock = now,
              id: string = identifier(), options: RecorderOptions = {}) {
    this.run = {id, name, schema_version: SCHEMA_VERSION, created_at: clock(), ended_at: null,
      status: "running", attributes: structuredClone(attributes), events: []};
    this.captureContent = options.captureContent ?? false;
  }
  event(input: EventInput): TraceEvent {
    const started = input.started_at ?? this.clock();
    const event: TraceEvent = {
      id: input.id ?? identifier(), kind: input.kind, name: input.name, parent_id: input.parent_id ?? null,
      started_at: started, ended_at: input.ended_at ?? started, status: input.status ?? "ok",
      attributes: structuredClone(input.attributes ?? {}), usage: structuredClone(input.usage ?? {})
    };
    for (const key of ["request", "response", "request_hash", "response_hash", "latency_ms", "cost_usd", "error"] as const)
      if (input[key] !== undefined) Object.assign(event, {[key]: structuredClone(input[key])});
    this.run.events.push(event); return event;
  }
  async capture<T extends JsonValue>(kind: EventKind, name: string, request: JsonValue,
                                     operation: () => Promise<T> | T): Promise<T> {
    const started = this.clock();
    const safeRequest = redact(request) as JsonValue;
    const request_hash = await digest(safeRequest);
    try {
      const response = await operation();
      const safeResponse = redact(response) as JsonValue;
      this.event({kind, name, started_at: started, ended_at: this.clock(), status: "ok",
        request_hash, response_hash: await digest(safeResponse),
        ...(this.captureContent ? {request: safeRequest, response: safeResponse} : {})});
      return response;
    } catch (cause) {
      this.event({kind, name, started_at: started, ended_at: this.clock(), status: "error", request_hash,
        ...(this.captureContent ? {request: safeRequest} : {}),
        error: {type: cause instanceof Error ? cause.name : "Error", message: String(redact(String(cause)))}});
      throw cause;
    }
  }
  finish(status = "ok"): TraceRun { this.run.status = status; this.run.ended_at = this.clock(); validateTrace(this.run); return this.run; }
}

export interface ReplayResult {run: TraceRun; fixture_hits: number; live_calls: 0}

export function exactReplay(source: TraceRun, clock: Clock = now): ReplayResult {
  validateTrace(source);
  const replay: TraceRun = {id: identifier(), name: `replay:${source.name}`, schema_version: SCHEMA_VERSION,
    created_at: clock(), ended_at: null, status: "running", attributes: {source_run_id: source.id, mode: "exact"}, events: []};
  for (const original of source.events) {
    const event = structuredClone(original); event.id = `replay-${original.id}`;
    event.started_at = clock(); event.ended_at = clock(); replay.events.push(event);
  }
  replay.status = "ok"; replay.ended_at = clock(); validateTrace(replay);
  return {run: replay, fixture_hits: source.events.length, live_calls: 0};
}
