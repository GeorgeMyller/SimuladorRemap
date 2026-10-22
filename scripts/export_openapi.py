#!/usr/bin/env python3
"""Exporta o ``openapi.json`` de ``create_app`` sem servidor (entrada do ``orval``, D-24).

Uso (de ``backend/``): ``uv run python ../scripts/export_openapi.py ../frontend/openapi.json``.
Não abre o banco nem inicia o worker (o lifespan não corre).
"""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

from simremap.api.main import create_app
from simremap.core.config import Settings


def main(argv: list[str]) -> int:
    target = Path(argv[1]) if len(argv) > 1 else Path("openapi.json")
    with tempfile.TemporaryDirectory() as tmp:
        settings = Settings(
            _env_file=None, env="dev", data_dir=Path(tmp), static_dir=None, worker_mode="thread"
        )
        spec = create_app(settings).openapi()
    target.write_text(json.dumps(spec, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"openapi: {len(spec.get('paths', {}))} caminhos -> {target}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
