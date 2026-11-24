"""Pure-Python Gear-hash FastCDC content-defined chunking, delta-diff & resumable assembly."""

from __future__ import annotations

import hashlib
import json
import struct
from dataclasses import dataclass
from pathlib import Path
from typing import Any

# Deterministic 256-entry 32-bit Gear hash lookup table generated via SHA-256(b"cdc-delta-gear" || byte)
GEAR_TABLE: tuple[int, ...] = tuple(
    struct.unpack("<I", hashlib.sha256(b"cdc-delta-gear" + bytes([i])).digest()[:4])[0]
    for i in range(256)
)
_MASK32 = 0xFFFFFFFF


@dataclass(frozen=True)
class ChunkRef:
    offset: int
    length: int
    sha256: str


@dataclass(frozen=True)
class FileManifest:
    file_name: str
    total_bytes: int
    file_sha256: str
    min_chunk: int
    avg_chunk: int
    max_chunk: int
    chunks: tuple[ChunkRef, ...]


@dataclass(frozen=True)
class DeltaPlan:
    total_chunks: int
    reused_chunks: int
    missing_chunks: tuple[str, ...]
    bytes_to_transfer: int
    bytes_saved: int
    bandwidth_savings_pct: float


def fastcdc_chunk_bytes(
    data: bytes,
    *,
    min_chunk: int = 2048,
    avg_chunk: int = 8192,
    max_chunk: int = 32768,
) -> list[tuple[int, bytes, str]]:
    """Split `data` using normalized Gear-hash FastCDC into (offset, raw_chunk, sha256) tuples."""
    if not (64 <= min_chunk < avg_chunk < max_chunk):
        raise ValueError("Require 64 <= min_chunk < avg_chunk < max_chunk")
    n = len(data)
    if n == 0:
        return []

    bits = max(6, (avg_chunk.bit_length() - 1))
    # Normalized chunking (Xia et al., USENIX ATC '16): stricter mask before avg, looser after avg
    mask_s = (1 << (bits + 1)) - 1
    mask_l = (1 << max(4, bits - 1)) - 1
    table = GEAR_TABLE

    chunks: list[tuple[int, bytes, str]] = []
    pos = 0
    while pos < n:
        remaining = n - pos
        if remaining <= min_chunk:
            raw = data[pos:n]
            chunks.append((pos, raw, hashlib.sha256(raw).hexdigest()))
            break

        normal_end = min(pos + avg_chunk, n)
        hard_end = min(pos + max_chunk, n)
        fp = 0
        cut = hard_end

        i = pos + min_chunk
        while i < normal_end:
            fp = ((fp << 1) + table[data[i]]) & _MASK32
            if (fp & mask_s) == 0:
                cut = i + 1
                break
            i += 1
        else:
            while i < hard_end:
                fp = ((fp << 1) + table[data[i]]) & _MASK32
                if (fp & mask_l) == 0:
                    cut = i + 1
                    break
                i += 1

        raw = data[pos:cut]
        chunks.append((pos, raw, hashlib.sha256(raw).hexdigest()))
        pos = cut
    return chunks


class ChunkStore:
    """Content-addressed local disk/memory chunk store with SHA-256 verification on read & write."""

    def __init__(self, root_dir: str | Path) -> None:
        self.root = Path(root_dir)
        self.root.mkdir(parents=True, exist_ok=True)

    def _chunk_path(self, digest: str) -> Path:
        if len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest):
            raise ValueError(f"Invalid SHA-256 digest: {digest!r}")
        return self.root / digest[:2] / digest

    def put(self, raw: bytes) -> str:
        digest = hashlib.sha256(raw).hexdigest()
        dest = self._chunk_path(digest)
        if not dest.exists():
            dest.parent.mkdir(parents=True, exist_ok=True)
            tmp = dest.with_suffix(".tmp")
            tmp.write_bytes(raw)
            tmp.replace(dest)
        return digest

    def has(self, digest: str) -> bool:
        return self._chunk_path(digest).exists()

    def get(self, digest: str) -> bytes:
        path = self._chunk_path(digest)
        raw = path.read_bytes()
        if hashlib.sha256(raw).hexdigest() != digest:
            raise ValueError(f"Corrupted chunk detected on disk for {digest}")
        return raw


def build_manifest(
    data: bytes,
    *,
    file_name: str = "payload.bin",
    store: ChunkStore | None = None,
    min_chunk: int = 2048,
    avg_chunk: int = 8192,
    max_chunk: int = 32768,
) -> FileManifest:
    """Chunk a payload with FastCDC, optionally populate a `ChunkStore`, and return its manifest."""
    raw_chunks = fastcdc_chunk_bytes(data, min_chunk=min_chunk, avg_chunk=avg_chunk, max_chunk=max_chunk)
    refs: list[ChunkRef] = []
    for offset, raw, digest in raw_chunks:
        if store is not None:
            store.put(raw)
        refs.append(ChunkRef(offset=offset, length=len(raw), sha256=digest))
    return FileManifest(
        file_name=file_name,
        total_bytes=len(data),
        file_sha256=hashlib.sha256(data).hexdigest(),
        min_chunk=min_chunk,
        avg_chunk=avg_chunk,
        max_chunk=max_chunk,
        chunks=tuple(refs),
    )


def plan_delta(target_manifest: FileManifest, local_store: ChunkStore) -> DeltaPlan:
    """Determine exact missing chunks and bandwidth savings for a resumable delta transfer."""
    missing: list[str] = []
    missing_seen: set[str] = set()
    bytes_to_send = 0
    reused = 0
    for ref in target_manifest.chunks:
        if local_store.has(ref.sha256):
            reused += 1
        elif ref.sha256 not in missing_seen:
            missing_seen.add(ref.sha256)
            missing.append(ref.sha256)
            bytes_to_send += ref.length
    saved = max(0, target_manifest.total_bytes - bytes_to_send)
    pct = round((saved / target_manifest.total_bytes) * 100.0, 2) if target_manifest.total_bytes else 100.0
    return DeltaPlan(
        total_chunks=len(target_manifest.chunks),
        reused_chunks=reused,
        missing_chunks=tuple(missing),
        bytes_to_transfer=bytes_to_send,
        bytes_saved=saved,
        bandwidth_savings_pct=pct,
    )


def assemble_from_store(manifest: FileManifest, store: ChunkStore) -> bytes:
    """Reassemble the target file from verified chunks and check whole-file SHA-256."""
    buf = bytearray()
    for ref in manifest.chunks:
        chunk = store.get(ref.sha256)
        if len(chunk) != ref.length:
            raise ValueError(f"Chunk length mismatch for {ref.sha256}")
        buf.extend(chunk)
    result = bytes(buf)
    if hashlib.sha256(result).hexdigest() != manifest.file_sha256:
        raise ValueError("Assembled file SHA-256 does not match manifest.file_sha256")
    return result


def manifest_to_json(manifest: FileManifest) -> str:
    payload: dict[str, Any] = {
        "file_name": manifest.file_name,
        "total_bytes": manifest.total_bytes,
        "file_sha256": manifest.file_sha256,
        "min_chunk": manifest.min_chunk,
        "avg_chunk": manifest.avg_chunk,
        "max_chunk": manifest.max_chunk,
        "chunks": [{"offset": c.offset, "length": c.length, "sha256": c.sha256} for c in manifest.chunks],
    }
    return json.dumps(payload, indent=2)
