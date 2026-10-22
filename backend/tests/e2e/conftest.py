"""E2E de backend (``-m e2e``; ``tests/e2e/`` recebe o marcador pelo conftest raiz).

Coloca ``tests/e2e``, ``tests/dyno`` e ``tests/telemetry`` no ``sys.path`` para os ajudantes
(``e2e_support``, ``dyno_helpers``, ``tel_helpers``); os processos ``spawn`` herdam o caminho.
"""

from __future__ import annotations

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
for path in (HERE, HERE.parent / "dyno", HERE.parent / "telemetry"):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))
