"""Executable entry point for the packaged local companion."""

from __future__ import annotations

import os
import sys
from pathlib import Path

from quant_recruiting import __version__
from quant_recruiting.local_server import serve_companion


def main() -> None:
    if "--version" in sys.argv:
        print(__version__)
        return
    if getattr(sys, "frozen", False):
        os.chdir(Path(sys.executable).resolve().parent)
    serve_companion()


if __name__ == "__main__":
    main()
