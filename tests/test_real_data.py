"""Automated tests over checksum-pinned, publicly released benchmark records."""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from replayguard.compare import compare_runs
from replayguard.datasets import (load_agentdojo_vectors, load_bfcl, load_openai_preferences,
                                  load_tau_tasks, load_tau_voice_trace)
from replayguard.replay import ReplayMode, Replayer
from replayguard.schema import EventKind

DATA = Path(__file__).parent / "data" / "public"


def datasets():
    return {
        "bfcl": list(load_bfcl(DATA / "bfcl_cases.jsonl", DATA / "bfcl_answers.jsonl")),
        "tau2": list(load_tau_tasks(DATA / "tau_airline.json")),
        "agentdojo": list(load_agentdojo_vectors(DATA / "agentdojo_vectors.yaml")),
    }


def test_vendored_data_matches_manifest_checksums():
    manifest = json.loads((DATA / "manifest.json").read_text(encoding="utf-8"))
    assert {"bfcl_cases", "bfcl_answers", "tau_airline", "agentdojo_vectors",
            "openai_human_preferences", "tau_voice_trace_1", "tau_voice_trace_2", "tau_voice_trace_3",
            "openinference_otel_spans"} == set(manifest["sources"])
    for source in manifest["sources"].values():
        content = (DATA / source["file"]).read_bytes()
        assert hashlib.sha256(content).hexdigest() == source["curated_sha256"]
        assert source["commit"] and source["license"]


def test_real_data_has_broad_case_volume():
    corpus = datasets()
    assert len(corpus["bfcl"]) == 60
    assert len(corpus["tau2"]) == 30
    assert len(corpus["agentdojo"]) >= 10
    assert sum(map(len, corpus.values())) >= 100


@pytest.mark.parametrize("dataset_name", ["bfcl", "tau2", "agentdojo"])
def test_every_real_record_exactly_replays_without_live_calls(dataset_name):
    for source in datasets()[dataset_name]:
        result = Replayer().replay(source, mode=ReplayMode.EXACT, live={"danger": lambda _: 1}, live_names={"danger"})
        assert result.live_calls == 0
        assert compare_runs(source, result.run).equal


def test_bfcl_ground_truth_becomes_executable_tool_fixtures():
    grounded = 0
    for run in datasets()["bfcl"]:
        proposals = {event.name for event in run.events if event.kind == EventKind.TOOL_PROPOSAL}
        calls = [event for event in run.events if event.kind == EventKind.TOOL]
        grounded += len(calls)
        assert calls and all(call.name in proposals for call in calls)
        assert all(call.attributes["ground_truth"] and isinstance(call.request, dict) for call in calls)
    assert grounded >= 30


def test_tau2_preserves_policy_and_evaluation_requirements():
    runs = datasets()["tau2"]
    assert all(any(event.kind == EventKind.EVALUATION for event in run.events) for run in runs)
    assert all(any(event.kind == EventKind.CONVERSATION for event in run.events) for run in runs)
    assert any("refuse" in json.dumps(run.to_dict()).lower() for run in runs)
    assert any(any(event.kind == EventKind.TOOL for event in run.events) for run in runs)


def test_agentdojo_marks_retrieved_vectors_untrusted_and_policy_bound():
    for run in datasets()["agentdojo"]:
        retrieval = next(event for event in run.events if event.kind == EventKind.RETRIEVAL)
        decision = next(event for event in run.events if event.kind == EventKind.AUTHORIZATION)
        assert retrieval.attributes["trust"] == "untrusted"
        assert decision.response["decision"] == "requires_policy"


def test_real_human_preferences_preserve_candidates_choices_and_confidence():
    runs = list(load_openai_preferences(DATA / "openai_human_preferences.jsonl"))
    assert len(runs) == 100
    assert all(len([e for e in run.events if e.kind == EventKind.ARTIFACT]) == 2 for run in runs)
    assert all(run.attributes["human_choice"] in {0, 1} for run in runs)
    assert {run.attributes["split"] for run in runs} == {"valid1", "valid2"}
    assert len({run.attributes["worker"] for run in runs}) > 1
    assert any(run.attributes["confidence"] is not None for run in runs)


def test_recorded_tau_voice_trajectories_preserve_real_timing_and_turns():
    paths = sorted(DATA.glob("tau_voice_trace_*.json"))
    runs = [load_tau_voice_trace(path) for path in paths]
    assert len(runs) == 3
    assert sum(len(run.events) for run in runs) > 1000
    assert all(run.attributes["mode"] == "full_duplex" for run in runs)
    assert all(run.attributes["duration_seconds"] > 300 for run in runs)
    assert all({event.name for event in run.events} >= {"voice.user", "voice.assistant"} for run in runs)
    for run in runs:
        result = Replayer().replay(run, mode=ReplayMode.EXACT)
        assert result.live_calls == 0 and compare_runs(run, result.run).equal


@pytest.mark.network
@pytest.mark.skipif(os.getenv("REPLAYGUARD_VERIFY_PUBLIC_DATA") != "1", reason="explicit live network verification only")
def test_upstream_sources_still_match_pinned_checksums():
    subprocess.run([sys.executable, "tools/fetch_real_data.py"], check=True)
