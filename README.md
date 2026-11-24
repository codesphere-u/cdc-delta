# cdc-delta

**Bandwidth-miserly pure-Python Gear-hash FastCDC content-defined chunker, SHA-256 resumable chunk store, and delta-patch sync engine for intermittent 2G/3G links.**

Zero runtime dependencies. Pure Python 3.11+. Enables rural schools, clinics, and field gateways to sync updated offline datasets and software packs over slow, drop-prone cellular links while reusing >75–95% of already-downloaded chunks even after mid-file insertions.

## Quick Start

```bash
uv sync --extra dev
cdc-delta demo
```

## License

MIT License — see [LICENSE](LICENSE).
