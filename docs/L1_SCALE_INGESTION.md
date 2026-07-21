# L1 large-corpus ingestion

Download the full checksum-pinned SWE-bench Verified dataset and stream it into ReplayGuard:

```console
python tools/fetch_swe_bench_verified.py --output .verify/upstream/swe-bench-verified.parquet
verify --store .verify/scale-store scale-ingest \
  --format swe-bench-verified \
  --input .verify/upstream/swe-bench-verified.parquet \
  --manifest .verify/scale-swe-bench.json \
  --replay-sample 50
```

For existing tau2 exports, point the same command at one JSON file or an experiment directory:

```console
verify --store .verify/tau-store scale-ingest --format tau2 \
  --input data/simulations --manifest .verify/scale-tau2.json
```

SWE-bench parquet ingestion uses Arrow record batches rather than loading the whole table.
Install `replayguard[scale]` for parquet support; JSONL remains standard-library-only. The
manifest records run/event counts, logical bytes, ingest throughput, a fixture-only replay
sample, and its own SHA-256.

On the development workstation, the complete 500-run snapshot ingested in 5.68 seconds and all
2,000 events replayed exactly in 5.48 seconds with zero live calls. The three pinned public tau2
voice recordings contain 6,908 retained speech/turn-taking events and replay in under one second.

The pinned source is `princeton-nlp/SWE-bench_Verified` revision
`c104f840cc67f8b6eec6f759ebc8b2693d585d4a`: 500 records, 2,096,679 bytes, SHA-256
`a45b1fe4e2f0c8390b2b2938ac83e92ed5979000856808f3679c07812e9e6dcd`. Gold patches are
explicitly labeled reference-only and must never be exposed to candidate agents.
