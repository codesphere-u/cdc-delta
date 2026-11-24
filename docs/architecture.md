# Architecture — `cdc-delta`

- `cdc_delta.engine`: Normalized Gear-hash FastCDC (Xia et al., USENIX ATC '16) chunker, atomic SHA-256 content-addressed `ChunkStore`, resumable `plan_delta` diff planner, and whole-file verified `assemble_from_store`.
- `cdc_delta.cli`: Shift-invariant delta bandwidth demonstration CLI.
