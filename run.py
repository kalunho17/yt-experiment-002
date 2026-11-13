#!/usr/bin/env python3
"""Entry point that needs no installation: ``python run.py <command>``. Python 3.11+.

The harness uses the standard library only; the optional smart-plug logger needs ``pip install tapo``.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from gpu_break_even.cli import main  # noqa: E402

if __name__ == "__main__":
    main()
