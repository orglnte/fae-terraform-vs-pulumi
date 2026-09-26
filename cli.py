#!/usr/bin/env python3
"""The operator's entry point: `python3 cli.py …` runs the fae engine for
this experiment. The engine is imported from its checkout — `$FAE_DIR`, else
the sibling `../fae` — not installed, and the checkout goes on PYTHONPATH so
every process the engine starts imports the same engine. The root is this
repo, whatever the working directory."""
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
ENGINE = Path(os.environ.get("FAE_DIR") or ROOT.parent / "fae").resolve()
if not (ENGINE / "fae" / "__init__.py").is_file():
    sys.exit(f"cli.py: no fae engine checkout at {ENGINE} — set FAE_DIR")
os.environ["REPO_ROOT"] = str(ROOT)
os.environ["PYTHONPATH"] = os.pathsep.join(
    [str(ENGINE)] + [p for p in os.environ.get("PYTHONPATH", "").split(os.pathsep) if p])
sys.path.insert(0, str(ENGINE))

from fae.cli import main  # noqa: E402

if __name__ == "__main__":
    main()
