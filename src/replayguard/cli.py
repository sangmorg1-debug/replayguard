from __future__ import annotations

import argparse
import json
import sys
from importlib import resources
from pathlib import Path


def _packaged_schema(name: str) -> str:
    """Resolve a bundled schema/contract file's path regardless of install method.

    Editable installs and wheel installs both expose this correctly via importlib.resources,
    unlike a __file__-relative walk up to a sibling schemas/ directory, which only exists
    next to the package in an editable/source-tree install.
    """
    return str(resources.files("replayguard.schemas").joinpath(name))

from .assertions import Assertion
from .compare import compare_runs
from .redaction import Redactor
from .replay import ReplayMode, Replayer
from .storage import LocalStore
from .flakiness import analyze_flakiness
from .suites import RegressionSuite, SuiteRunner
from .ci import run_ci
from .mcp_scanner import MCPScanner, SEVERITY, render_scan_markdown
from .mcp_registry import DEFAULT_ENDPOINT, RegistryClient, aggregate_registry, render_registry_markdown
from .gateway import ActionRequest, PolicySet, RuntimeGateway
from .rag import compare_rag, evaluate_file
from .aibom import generate_aibom, validate_aibom
from .costing import PriceCatalog, analyze_costs, check_budget, load_records, recommend, reconcile_billing
from .operations import OperationsStore, check_api_compatibility
from .otel import coverage as otel_coverage, export_otlp, import_traces, normalized
from .diagnosis import diagnose, load_ground_truth, score_diagnosis
from .threat_mapping import coverage_matrix, write_coverage
from .compliance import build_pack
from .scale import ingest as scale_ingest, iter_swe_bench, iter_tau2
from .tap import TapConfig, create_tap_app
from .registry_monitor import RegistryMonitor, monitor_loop


def _json(value) -> None:
    print(json.dumps(value, indent=2, default=lambda item: item.__dict__))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="verify", description="Local capture and safe replay for AI applications")
    parser.add_argument("--store", default=".verify", help="local store directory")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("init", help="initialize a local store")
    record = sub.add_parser("record", help="run a Python script under a recorder")
    record.add_argument("script")
    record.add_argument("--capture-content", action="store_true")
    replay = sub.add_parser("replay", help="perform exact fixture replay")
    replay.add_argument("run_id")
    compare = sub.add_parser("compare", help="compare two recorded runs")
    compare.add_argument("left")
    compare.add_argument("right")
    test = sub.add_parser("test", help="evaluate a deterministic assertion")
    test.add_argument("run_id")
    test.add_argument("kind", choices=["contains", "excludes", "tool_called", "tool_not_called", "tool_count", "max_latency_ms", "max_cost_usd", "no_unhandled_error"])
    test.add_argument("expected", nargs="?")
    inspect = sub.add_parser("inspect", help="list runs or inspect one")
    inspect.add_argument("run_id", nargs="?")
    redact = sub.add_parser("redact-check", help="scan a file or stdin for secrets")
    redact.add_argument("path", nargs="?")
    prune = sub.add_parser("prune", help="apply local retention policy")
    prune.add_argument("--keep", type=int, required=True)
    suite = sub.add_parser("suite", help="create, add to, or run a regression suite")
    suite_sub = suite.add_subparsers(dest="suite_command", required=True)
    suite_create = suite_sub.add_parser("create")
    suite_create.add_argument("path")
    suite_create.add_argument("--name", required=True)
    suite_add = suite_sub.add_parser("add")
    suite_add.add_argument("path")
    suite_add.add_argument("run_id")
    suite_add.add_argument("--negative", action="store_true")
    suite_run = suite_sub.add_parser("run")
    suite_run.add_argument("path")
    flaky = sub.add_parser("flaky", help="analyze repeated recorded runs")
    flaky.add_argument("run_ids", nargs="+")
    ci = sub.add_parser("ci", help="run a merge gate and emit an evidence bundle")
    ci.add_argument("--suite", required=True)
    ci.add_argument("--candidate-map")
    ci.add_argument("--changed-files", help="newline-delimited changed paths")
    ci.add_argument("--output", default=".verify/report")
    ci.add_argument("--commit-sha")
    serve = sub.add_parser("serve", help="run the self-hosted private-beta API")
    serve.add_argument("--database", default=".verify/hosted.sqlite3")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8787)
    serve.add_argument("--allow-bootstrap", action="store_true")
    scan = sub.add_parser("mcp-scan", help="non-destructively scan MCP tools and protocol evidence")
    scan.add_argument("--tools", help="JSON tool manifest or tools/list result")
    scan.add_argument("--stdio-command", help="JSON array command; probes only initialize and tools/list")
    scan.add_argument("--registry", action="store_true", help="statically sweep official registry distribution manifests")
    scan.add_argument("--registry-url", default=DEFAULT_ENDPOINT)
    scan.add_argument("--registry-page-limit", type=int, default=100)
    scan.add_argument("--registry-max-pages", type=int, help="testing/preview limit; omit for a full sweep")
    scan.add_argument("--outputs", help="optional JSON map of recorded tool outputs")
    scan.add_argument("--transcript", help="optional JSON array of protocol responses")
    scan.add_argument("--suppressions", help="optional JSON suppression list")
    scan.add_argument("--output", default=".verify/mcp-scan")
    scan.add_argument("--fail-on", choices=["low", "medium", "high", "critical"], default="high")
    gateway = sub.add_parser("gateway", help="evaluate and administer runtime authorization")
    gateway_sub = gateway.add_subparsers(dest="gateway_command", required=True)
    gate_check = gateway_sub.add_parser("check")
    gate_check.add_argument("--policy", required=True); gate_check.add_argument("--request", required=True)
    gate_check.add_argument("--database", default=".verify/gateway.sqlite3"); gate_check.add_argument("--approval-token")
    gate_approve = gateway_sub.add_parser("approve")
    gate_approve.add_argument("--policy", required=True); gate_approve.add_argument("--decision", required=True)
    gate_approve.add_argument("--database", default=".verify/gateway.sqlite3"); gate_approve.add_argument("--ttl", type=int, default=300)
    gate_revoke = gateway_sub.add_parser("revoke")
    gate_revoke.add_argument("--policy", required=True); gate_revoke.add_argument("--kind", choices=["agent","tool","user"], required=True)
    gate_revoke.add_argument("--value", required=True); gate_revoke.add_argument("--database", default=".verify/gateway.sqlite3")
    gate_audit = gateway_sub.add_parser("audit")
    gate_audit.add_argument("--policy", required=True); gate_audit.add_argument("--database", default=".verify/gateway.sqlite3")
    rag = sub.add_parser("rag", help="evaluate RAG reliability, provenance, and AIBOMs")
    rag_sub = rag.add_subparsers(dest="rag_command", required=True)
    rag_eval = rag_sub.add_parser("evaluate")
    rag_eval.add_argument("--suite", required=True); rag_eval.add_argument("--output", default=".verify/rag-report.json")
    rag_eval.add_argument("--semantic", action="store_true", help="run the optional revision-pinned LettuceDetect judge")
    rag_eval.add_argument("--semantic-threshold", type=float, default=.63)
    rag_eval.add_argument("--semantic-gate", action="store_true", help="allow probabilistic semantic findings to fail the suite")
    rag_compare = rag_sub.add_parser("compare")
    rag_compare.add_argument("left"); rag_compare.add_argument("right")
    rag_bom = rag_sub.add_parser("aibom")
    rag_bom.add_argument("--manifest", required=True); rag_bom.add_argument("--output", default=".verify/aibom.json")
    rag_bom.add_argument("--schema", default=_packaged_schema("aibom-v1.schema.json"))
    cost = sub.add_parser("cost", help="analyze verified cost per successful task")
    cost_sub = cost.add_subparsers(dest="cost_command", required=True)
    cost_analyze = cost_sub.add_parser("analyze")
    cost_analyze.add_argument("--records", required=True); cost_analyze.add_argument("--catalog", required=True)
    cost_analyze.add_argument("--output", default=".verify/cost-report.json")
    cost_analyze.add_argument("--max-total", type=float); cost_analyze.add_argument("--max-cost-per-success", type=float)
    cost_recommend = cost_sub.add_parser("recommend")
    cost_recommend.add_argument("--report", required=True); cost_recommend.add_argument("--baseline", required=True)
    cost_recommend.add_argument("--min-quality", type=float, required=True); cost_recommend.add_argument("--min-security", type=float, default=1.0)
    cost_recommend.add_argument("--max-latency-ms", type=float)
    cost_reconcile = cost_sub.add_parser("reconcile")
    cost_reconcile.add_argument("--records", required=True); cost_reconcile.add_argument("--catalog", required=True)
    cost_reconcile.add_argument("--tolerance", type=float, default=.05)
    ga = sub.add_parser("ga", help="general-availability operations and readiness")
    ga_sub = ga.add_subparsers(dest="ga_command", required=True)
    ga_backup = ga_sub.add_parser("backup"); ga_backup.add_argument("--database", required=True); ga_backup.add_argument("--output", required=True)
    ga_restore = ga_sub.add_parser("restore-copy"); ga_restore.add_argument("--backup", required=True); ga_restore.add_argument("--output", required=True)
    ga_ready = ga_sub.add_parser("readiness"); ga_ready.add_argument("--database", required=True)
    ga_ready.add_argument("--contract", default=_packaged_schema("public-api-v1.contract.json"))
    otel = sub.add_parser("otel", help="import and export OTLP/OpenInference traces")
    otel_sub = otel.add_subparsers(dest="otel_command", required=True)
    otel_import = otel_sub.add_parser("import"); otel_import.add_argument("path")
    otel_export = otel_sub.add_parser("export"); otel_export.add_argument("run_ids", nargs="+"); otel_export.add_argument("--output", required=True)
    otel_cov = otel_sub.add_parser("coverage"); otel_cov.add_argument("path")
    otel_round = otel_sub.add_parser("roundtrip"); otel_round.add_argument("path"); otel_round.add_argument("--output")
    diagnosis = sub.add_parser("diagnose", help="rank suspect spans in a recorded run")
    diagnosis.add_argument("run_id")
    diagnosis.add_argument("--max-candidates", type=int, default=3,
                           help="maximum ranked suspects (default: calibrated TRAIL precision setting of 3)")
    diagnosis.add_argument("--ground-truth", help="optional TRAIL processed-annotation JSON")
    diagnosis.add_argument("--experimental-claim-graph", action="store_true",
                           help="augment suspects with an experimental, non-gating local claim/evidence graph signal (see docs/DIAGNOSE_CLAIM_GRAPH.md)")
    threats = sub.add_parser("threat-map", help="publish pinned ATLAS/OWASP control coverage")
    threats.add_argument("--output", default=".verify/threat-mapping")
    compliance = sub.add_parser("compliance-pack", help="assemble an EU AI Act evidence inventory and coverage table")
    compliance.add_argument("--workspace", default=".")
    compliance.add_argument("--output", default=".verify/compliance-pack")
    compliance.add_argument("--profile", choices=["all", "gpai", "provider", "deployer"], default="all")
    scale = sub.add_parser("scale-ingest", help="stream large SWE-bench Verified or tau2 corpora into the local store")
    scale.add_argument("--format", choices=["swe-bench-verified", "tau2"], required=True)
    scale.add_argument("--input", required=True)
    scale.add_argument("--manifest", default=".verify/scale-ingest.json")
    scale.add_argument("--max-runs", type=int)
    scale.add_argument("--replay-sample", type=int, default=25)
    tap = sub.add_parser("tap", help="run the bounded local OTLP/HTTP JSON engineering preview")
    tap.add_argument("--host", default="127.0.0.1"); tap.add_argument("--port", type=int, default=4318)
    tap.add_argument("--tap-store", default=".verify/tap"); tap.add_argument("--suite")
    tap.add_argument("--sample-rate", type=float, default=.01); tap.add_argument("--always-sample-errors", action=argparse.BooleanOptionalAction, default=True)
    tap.add_argument("--token"); tap.add_argument("--max-body-bytes", type=int, default=2_000_000)
    tap.add_argument("--max-spans", type=int, default=2_000); tap.add_argument("--max-traces", type=int, default=100)
    tap.add_argument("--max-concurrent", type=int, default=4)
    monitor = sub.add_parser("mcp-monitor", help="snapshot and diff official MCP Registry manifests")
    monitor.add_argument("--history", default=".verify/mcp-registry-monitor")
    monitor.add_argument("--registry-url", default=DEFAULT_ENDPOINT); monitor.add_argument("--page-limit", type=int, default=100)
    monitor.add_argument("--max-pages", type=int); monitor.add_argument("--interval-seconds", type=float)
    monitor.add_argument("--seed-snapshot", help="initialize history from a prior full static snapshot without fetching")
    monitor.add_argument("--fail-on", choices=["none", "low", "medium", "high", "critical"], default="high")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    store = LocalStore(args.store)
    try:
        if args.command == "init":
            store.init()
            Path(args.store, "config.json").write_text(json.dumps({"capture_content": False, "schema_version": "1.0.0"}, indent=2))
            print(f"initialized {Path(args.store).resolve()}")
        elif args.command == "record":
            import runpy
            from .recorder import Recorder
            with Recorder(Path(args.script).stem, store=store, capture_content=args.capture_content) as recorder:
                runpy.run_path(args.script, run_name="__main__")
            print(recorder.run.id)
        elif args.command == "replay":
            result = Replayer().replay(store.load_run(args.run_id), mode=ReplayMode.EXACT)
            store.save_run(result.run)
            _json({"run_id": result.run.id, "fixture_hits": result.fixture_hits, "live_calls": result.live_calls})
        elif args.command == "compare":
            _json(compare_runs(store.load_run(args.left), store.load_run(args.right)).to_dict())
        elif args.command == "test":
            expected = args.expected
            if args.kind in {"tool_count"}: expected = int(expected)
            if args.kind in {"max_latency_ms", "max_cost_usd"}: expected = float(expected)
            target = expected if args.kind in {"tool_called", "tool_not_called"} else None
            result = Assertion(args.kind, expected=expected, target=target).evaluate(store.load_run(args.run_id))
            _json(result.__dict__)
            return 0 if result.passed else 1
        elif args.command == "inspect":
            _json(store.load_run(args.run_id).to_dict() if args.run_id else store.list_runs())
        elif args.command == "redact-check":
            text = Path(args.path).read_text(encoding="utf-8") if args.path else sys.stdin.read()
            findings = Redactor().findings(text)
            _json({"safe": not findings, "findings": findings})
            return 1 if findings else 0
        elif args.command == "prune":
            _json({"removed_index_entries": store.prune(args.keep)})
        elif args.command == "suite":
            if args.suite_command == "create":
                RegressionSuite(args.name).save(args.path)
                _json({"created": str(Path(args.path).resolve())})
            elif args.suite_command == "add":
                suite = RegressionSuite.load(args.path)
                case = suite.add_run(store.load_run(args.run_id), negative=args.negative)
                suite.save(args.path)
                _json({"case_id": case.id, "cases": len(suite.cases)})
            elif args.suite_command == "run":
                result = SuiteRunner().run(RegressionSuite.load(args.path))
                _json(result.to_dict())
                return 0 if result.passed == result.total else 1
        elif args.command == "flaky":
            _json(analyze_flakiness([store.load_run(item) for item in args.run_ids]).to_dict())
        elif args.command == "ci":
            changed = Path(args.changed_files).read_text(encoding="utf-8").splitlines() if args.changed_files else []
            result = run_ci(args.suite, candidate_map=args.candidate_map, changed_files=changed,
                            output_dir=args.output, commit_sha=args.commit_sha)
            _json({"passed": result.passed, "report": str(result.report_path),
                   "results": str(result.results_path), "evidence": str(result.bundle_path),
                   "bundle_sha256": result.bundle_sha256, "selected_cases": result.selected_cases})
            return 0 if result.passed else 1
        elif args.command == "serve":
            import uvicorn
            from .server import create_app
            uvicorn.run(create_app(args.database, allow_bootstrap=args.allow_bootstrap), host=args.host, port=args.port)
        elif args.command == "mcp-scan":
            scanner = MCPScanner()
            transcript = json.loads(Path(args.transcript).read_text()) if args.transcript else []
            selected_sources = sum(bool(item) for item in (args.registry, args.stdio_command, args.tools))
            if selected_sources != 1:
                raise ValueError("select exactly one of --registry, --tools, or --stdio-command")
            if args.registry:
                def registry_progress(pages, records):
                    if pages % 50 == 0: print(f"registry sweep: {pages} pages, {records} records", file=sys.stderr, flush=True)
                snapshot = RegistryClient(args.registry_url, progress=registry_progress).snapshot(limit=args.registry_page_limit,
                                                                        max_pages=args.registry_max_pages)
                report = aggregate_registry(snapshot); out = Path(args.output); out.mkdir(parents=True, exist_ok=True)
                (out / "snapshot.json").write_text(json.dumps(snapshot.to_dict(), indent=2) + "\n", encoding="utf-8")
                (out / "report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
                (out / "report.md").write_text(render_registry_markdown(report), encoding="utf-8")
                _json({"records": report["records"], "unique_servers": report["unique_servers"],
                       "findings": report["findings_total"], "snapshot_sha256": report["snapshot_sha256"],
                       "report": str((out / "report.md").resolve())})
                threshold = SEVERITY[args.fail_on]
                return 1 if any(count and SEVERITY[severity] >= threshold
                                for severity, count in report["finding_counts_by_severity"].items()) else 0
            if args.stdio_command:
                tools, active_transcript = scanner.scan_stdio(json.loads(args.stdio_command))
                transcript.extend(active_transcript)
                target = "stdio"
            elif args.tools:
                body = json.loads(Path(args.tools).read_text(encoding="utf-8"))
                tools = body.get("tools", body.get("result", {}).get("tools", [])) if isinstance(body, dict) else body
                target = str(Path(args.tools))
            outputs = json.loads(Path(args.outputs).read_text()) if args.outputs else {}
            suppressions = json.loads(Path(args.suppressions).read_text()) if args.suppressions else []
            report = scanner.scan(tools, target=target, outputs=outputs, transcript=transcript, suppressions=suppressions)
            out = Path(args.output); out.mkdir(parents=True, exist_ok=True)
            (out / "report.json").write_text(json.dumps(report.to_dict(), indent=2) + "\n", encoding="utf-8")
            (out / "report.md").write_text(render_scan_markdown(report), encoding="utf-8")
            _json({"max_severity": report.max_severity, "findings": len(report.findings), "suppressed": report.suppressed,
                   "report": str(out / "report.md")})
            return 1 if any(SEVERITY[item.severity] >= SEVERITY[args.fail_on] for item in report.findings) else 0
        elif args.command == "gateway":
            engine = RuntimeGateway(PolicySet.load(args.policy), args.database)
            if args.gateway_command == "check":
                request = ActionRequest(**json.loads(Path(args.request).read_text(encoding="utf-8")))
                decision = engine.authorize(request, args.approval_token)
                _json(decision.to_dict()); return 0 if decision.allowed else 1
            if args.gateway_command == "approve":
                _json({"approval_token": engine.issue_approval(args.decision, args.ttl), "expires_in_seconds": args.ttl})
            elif args.gateway_command == "revoke":
                engine.revoke(args.kind, args.value); _json({"revoked": True, "kind": args.kind, "value": args.value})
            elif args.gateway_command == "audit":
                _json({"valid_hash_chain": engine.verify_audit_chain(), "decisions": engine.decisions()})
        elif args.command == "threat-map":
            json_path, markdown_path = write_coverage(args.output)
            report = coverage_matrix()
            _json({"controls": report["summary"]["controls"], "unmapped_controls": report["summary"]["unmapped_controls"],
                   "json": str(json_path.resolve()), "markdown": str(markdown_path.resolve())})
        elif args.command == "compliance-pack":
            pack = build_pack(args.workspace, args.output, profile=args.profile)
            _json({"pack": str(Path(args.output).resolve() / "pack.json"),
                   "coverage": str(Path(args.output).resolve() / "coverage.md"), **pack["summary"]})
        elif args.command == "scale-ingest":
            runs = iter_swe_bench(args.input) if args.format == "swe-bench-verified" else iter_tau2(args.input)
            report = scale_ingest(runs, store, dataset=args.format, manifest_path=args.manifest,
                                  max_runs=args.max_runs, replay_sample=args.replay_sample)
            _json({key: report[key] for key in ("dataset", "runs", "events", "logical_bytes", "ingest_seconds",
                                                  "runs_per_second", "replay_sample_runs", "replay_seconds", "report_sha256")})
        elif args.command == "tap":
            if args.host not in {"127.0.0.1", "::1", "localhost"} and not args.token:
                raise ValueError("a bearer --token is required when the tap binds beyond loopback")
            import uvicorn
            config = TapConfig(args.sample_rate, args.always_sample_errors, args.max_body_bytes, args.max_spans,
                               args.max_traces, args.max_concurrent)
            uvicorn.run(create_tap_app(args.tap_store, config=config, token=args.token, suite_path=args.suite),
                        host=args.host, port=args.port)
        elif args.command == "mcp-monitor":
            monitor = RegistryMonitor(args.history, RegistryClient(args.registry_url))
            if args.seed_snapshot:
                _, report = monitor.seed(args.seed_snapshot)
                _json({"initialized": True, "servers": report["servers_after"], "records_source": args.seed_snapshot,
                       "snapshot_sha256": report["current_snapshot_sha256"], "report_sha256": report["report_sha256"]})
            elif args.interval_seconds:
                if args.interval_seconds < 60: raise ValueError("monitor intervals below 60 seconds are not allowed")
                monitor_loop(monitor, interval_seconds=args.interval_seconds,
                             on_report=lambda report: _json({"retrieved_at": report["current_retrieved_at"], "alerts": len(report["alerts"]),
                                                              "report_sha256": report["report_sha256"]}),
                             limit=args.page_limit, max_pages=args.max_pages)
            else:
                _, report = monitor.run(limit=args.page_limit, max_pages=args.max_pages)
                _json({"initialized": report["initialized"], "servers": report["servers_after"], "added": len(report["added_servers"]),
                       "removed": len(report["removed_servers"]), "updated": len(report["updated_servers"]),
                       "alerts": len(report["alerts"]), "report_sha256": report["report_sha256"]})
                if args.fail_on != "none":
                    return 1 if any(SEVERITY[item["severity"]] >= SEVERITY[args.fail_on] for item in report["alerts"]) else 0
        elif args.command == "rag":
            if args.rag_command == "evaluate":
                semantic_judge = None
                if args.semantic:
                    from .semantic import LettuceDetectJudge
                    semantic_judge = LettuceDetectJudge(threshold=args.semantic_threshold)
                elif args.semantic_gate:
                    raise ValueError("--semantic-gate requires --semantic")
                report = evaluate_file(args.suite, semantic_judge=semantic_judge, semantic_gate=args.semantic_gate)
                target = Path(args.output); target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
                _json({"report": str(target.resolve()), **report["summary"]})
                return 0 if not report["summary"]["failed"] else 1
            if args.rag_command == "compare":
                _json(compare_rag(json.loads(Path(args.left).read_text(encoding="utf-8")),
                                  json.loads(Path(args.right).read_text(encoding="utf-8"))))
            elif args.rag_command == "aibom":
                bom = generate_aibom(json.loads(Path(args.manifest).read_text(encoding="utf-8")))
                validate_aibom(bom, args.schema)
                target = Path(args.output); target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(json.dumps(bom, indent=2) + "\n", encoding="utf-8")
                _json({"valid": True, "components": len(bom["components"]), "output": str(target.resolve()), "digest": bom["digest"]})
        elif args.command == "cost":
            if args.cost_command == "analyze":
                report = analyze_costs(load_records(args.records), PriceCatalog.load(args.catalog))
                report["budget"] = check_budget(report, max_total_usd=args.max_total,
                                                 max_cost_per_success_usd=args.max_cost_per_success)
                target = Path(args.output); target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
                _json({"report": str(target.resolve()), "records": report["records"], "budget": report["budget"]})
                return 0 if report["budget"]["passed"] else 1
            if args.cost_command == "recommend":
                report = json.loads(Path(args.report).read_text(encoding="utf-8"))
                _json(recommend(report, args.baseline, min_quality=args.min_quality,
                                min_security=args.min_security, max_latency_ms=args.max_latency_ms))
            elif args.cost_command == "reconcile":
                result = reconcile_billing(load_records(args.records), PriceCatalog.load(args.catalog), args.tolerance)
                _json(result); return 0 if result["passed"] else 1
        elif args.command == "ga":
            if args.ga_command == "backup": _json(OperationsStore(args.database).backup(args.output))
            elif args.ga_command == "restore-copy": _json(OperationsStore.restore_copy(args.backup, args.output))
            elif args.ga_command == "readiness":
                from .server import create_app
                operations = OperationsStore(args.database)
                contract = json.loads(Path(args.contract).read_text(encoding="utf-8"))
                compatibility = check_api_compatibility(contract, create_app(args.database).openapi())
                result = {"ready": operations.health()["status"] == "ready" and compatibility["compatible"],
                          "health": operations.health(), "api_compatibility": compatibility}
                _json(result); return 0 if result["ready"] else 1
        elif args.command == "otel":
            if args.otel_command in {"import", "coverage", "roundtrip"}:
                document = json.loads(Path(args.path).read_text(encoding="utf-8"))
                runs = import_traces(document)
            if args.otel_command == "import":
                store.init()
                for run in runs: store.save_run(run)
                _json({"imported_runs": [run.id for run in runs], **otel_coverage(runs)})
            elif args.otel_command == "export":
                document = export_otlp([store.load_run(item) for item in args.run_ids])
                target = Path(args.output); target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")
                _json({"output": str(target.resolve()), "runs": len(args.run_ids)})
            elif args.otel_command == "coverage": _json(otel_coverage(runs))
            elif args.otel_command == "roundtrip":
                exported = export_otlp(runs); equivalent = normalized(document) == normalized(exported)
                if args.output:
                    target = Path(args.output); target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_text(json.dumps(exported, indent=2) + "\n", encoding="utf-8")
                _json({"equivalent": equivalent, **otel_coverage(runs)})
                return 0 if equivalent else 1
        elif args.command == "diagnose":
            if args.max_candidates < 1:
                raise ValueError("--max-candidates must be at least 1")
            result = diagnose(store.load_run(args.run_id), max_candidates=args.max_candidates,
                              experimental_claim_graph=args.experimental_claim_graph)
            payload = result.to_dict()
            if args.ground_truth:
                payload["benchmark"] = score_diagnosis(result, load_ground_truth(args.ground_truth))
            _json(payload)
        return 0
    except (KeyError, OSError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
