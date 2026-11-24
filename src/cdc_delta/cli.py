"""CLI for cdc-delta."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import tempfile
from collections.abc import Sequence

from cdc_delta.engine import ChunkStore, assemble_from_store, build_manifest, plan_delta


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="cdc-delta",
        description="Bandwidth-miserly FastCDC Gear-hash content-defined chunking & delta sync CLI.",
    )
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("demo", help="Demonstrate shift-invariant FastCDC delta bandwidth savings")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "demo":
        # High-entropy 128 KB binary archive; prepend 512 bytes at offset 0
        base = b"".join(hashlib.sha256(f"blk-{i}".encode()).digest() for i in range(4096))
        updated = (b"NEW-HEADER-UPDATE!" * 28) + base
        with tempfile.TemporaryDirectory() as tmp:
            client_store = ChunkStore(f"{tmp}/client")
            server_store = ChunkStore(f"{tmp}/server")
            build_manifest(base, file_name="v1.bin", store=client_store)
            v2_manifest = build_manifest(updated, file_name="v2.bin", store=server_store)
            plan = plan_delta(v2_manifest, client_store)
            for digest in plan.missing_chunks:
                client_store.put(server_store.get(digest))
            rebuilt = assemble_from_store(v2_manifest, client_store)
            assert rebuilt == updated
            print(
                json.dumps(
                    {
                        "v2_total_bytes": v2_manifest.total_bytes,
                        "total_chunks": plan.total_chunks,
                        "reused_chunks": plan.reused_chunks,
                        "missing_chunks": len(plan.missing_chunks),
                        "bytes_to_transfer": plan.bytes_to_transfer,
                        "bandwidth_savings_pct": plan.bandwidth_savings_pct,
                        "verified_exact_match": rebuilt == updated,
                    },
                    indent=2,
                )
            )
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(main())
