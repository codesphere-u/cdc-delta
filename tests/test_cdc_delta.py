"""Tests for Gear-hash FastCDC shift invariance, resumable chunk store, corruption check & CLI."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from cdc_delta import (
    ChunkStore,
    assemble_from_store,
    build_manifest,
    fastcdc_chunk_bytes,
    manifest_to_json,
    plan_delta,
)
from cdc_delta.cli import main as cli_main


def _pseudo_random_bytes(size: int, seed: bytes = b"seed") -> bytes:
    out = bytearray()
    counter = 0
    while len(out) < size:
        out.extend(hashlib.sha256(seed + counter.to_bytes(4, "big")).digest())
        counter += 1
    return bytes(out[:size])


def test_fastcdc_preserves_chunks_after_front_insertion_and_resumes_cleanly(tmp_path: Path) -> None:
    v1 = _pseudo_random_bytes(100_000, b"dataset-v1")
    # Prepend 333 bytes (breaks 100% of fixed-size block hashes, but FastCDC resyncs cleanly!)
    v2 = _pseudo_random_bytes(333, b"prepend") + v1

    client = ChunkStore(tmp_path / "client")
    server = ChunkStore(tmp_path / "server")
    build_manifest(v1, file_name="v1.bin", store=client, min_chunk=1024, avg_chunk=4096, max_chunk=16384)
    m2 = build_manifest(v2, file_name="v2.bin", store=server, min_chunk=1024, avg_chunk=4096, max_chunk=16384)
    assert json.loads(manifest_to_json(m2))["file_sha256"] == m2.file_sha256

    plan = plan_delta(m2, client)
    assert plan.bandwidth_savings_pct > 75.0
    assert plan.reused_chunks > 0

    # Simulate intermittent 2G drop halfway through transfer, then resume
    half = max(1, len(plan.missing_chunks) // 2)
    for d in plan.missing_chunks[:half]:
        client.put(server.get(d))
    resumed_plan = plan_delta(m2, client)
    assert len(resumed_plan.missing_chunks) == len(plan.missing_chunks) - half

    for d in resumed_plan.missing_chunks:
        client.put(server.get(d))
    assert assemble_from_store(m2, client) == v2


def test_corrupted_disk_chunk_detected_and_cli_demo(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    store = ChunkStore(tmp_path / "store")
    digest = store.put(b"hello-world-chunk")
    # Corrupt stored chunk on disk
    chunk_file = tmp_path / "store" / digest[:2] / digest
    chunk_file.write_bytes(b"corrupted-bytes!!")
    with pytest.raises(ValueError, match="Corrupted chunk"):
        store.get(digest)

    assert fastcdc_chunk_bytes(b"") == []
    assert cli_main(["demo"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["verified_exact_match"] is True
    assert out["bandwidth_savings_pct"] > 70.0
