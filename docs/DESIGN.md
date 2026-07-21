# Architecture decisions

## Privacy and trust boundaries

- Request/response bodies are absent by default; users must opt in.
- Values are redacted before hashing or persistence, so known secrets do not enter blobs or identity hashes.
- Exact replay accepts no path that invokes a live adapter. Selective/comparative replay requires explicit adapters and operation allowlists.
- SQLite contains only searchable run metadata. Immutable JSON payloads are addressed by SHA-256.
- `prune` removes retained index entries. Blob garbage collection and optional encryption are intentionally deferred and must land before production-sensitive use.

## Interoperability

The canonical artifact is versioned JSON, described by JSON Schema rather than Python class layout. Event operations use stable, low-cardinality names, payload capture is opt-in, and errors have a typed structure. This allows a TypeScript producer to target the same schema without a language-specific fork.

## Known Phase 1 limitations

- Instrumentation currently targets synchronous Python functions; async wrappers are next.
- Comparative replay primitives exist, but the CLI currently exposes safe exact replay only.
- JSON-schema assertion is reserved but not yet implemented without adding a runtime dependency.
- Optional encryption is not implemented; use filesystem protections and private local storage.
- Content-addressed blobs are immutable but do not yet have garbage collection.
- The SDK emits an OpenTelemetry-compatible conceptual hierarchy, not OTLP wire export.

