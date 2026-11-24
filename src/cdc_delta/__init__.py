"""cdc-delta — Pure-Python FastCDC content-defined chunker & resumable delta sync engine."""

from cdc_delta.engine import (
    GEAR_TABLE,
    ChunkRef,
    ChunkStore,
    DeltaPlan,
    FileManifest,
    assemble_from_store,
    build_manifest,
    fastcdc_chunk_bytes,
    manifest_to_json,
    plan_delta,
)

__version__ = "0.1.0"

__all__ = [
    "GEAR_TABLE",
    "ChunkRef",
    "ChunkStore",
    "DeltaPlan",
    "FileManifest",
    "__version__",
    "assemble_from_store",
    "build_manifest",
    "fastcdc_chunk_bytes",
    "manifest_to_json",
    "plan_delta",
]
