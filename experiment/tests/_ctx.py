"""The experiment's tests share the engine's test context (the engine
checkout's tests/_ctx.py): the `runs` facade, OrchTmpCase. Loaded by path
under another name so this module can re-export it whatever directory the
suite is discovered from.

Two roots: ROOT is this experiment's repo (fae.toml, experiment/,
workspaces), ENGINE_TREE the fae checkout it imports (`$FAE_DIR`, else the
sibling `../fae`) — the same rule as the repo's cli.py.
"""
import importlib.util
import os
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
_ENGINE = Path(os.environ.get("FAE_DIR") or _ROOT.parent / "fae").resolve()
if not (_ENGINE / "fae" / "__init__.py").is_file():
    raise ImportError(f"no fae engine checkout at {_ENGINE} — set FAE_DIR")
os.environ["FAE_TEST_EXPERIMENT"] = str(_ROOT / "experiment")
os.environ["REPO_ROOT"] = str(_ROOT)
os.environ["PYTHONPATH"] = os.pathsep.join(
    [str(_ENGINE)] + [p for p in os.environ.get("PYTHONPATH", "").split(os.pathsep) if p])
for _p in (str(_ROOT), str(_ENGINE / "tests"), str(_ENGINE)):
    if _p not in sys.path:
        sys.path.insert(0, _p)
_spec = importlib.util.spec_from_file_location("_engine_ctx", _ENGINE / "tests" / "_ctx.py")
_engine = importlib.util.module_from_spec(_spec)
sys.modules["_engine_ctx"] = _engine
_spec.loader.exec_module(_engine)
globals().update({k: v for k, v in vars(_engine).items() if not k.startswith("__")})
ROOT = _ROOT
ENGINE_TREE = _ENGINE
