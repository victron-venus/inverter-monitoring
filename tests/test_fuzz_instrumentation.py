"""Guard the production import route without running a mutation campaign."""

import json

# A fixed child program isolates imports from pytest's cached webhook module.
import subprocess  # nosec B404
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
IMPORT_PROBE = r"""
import contextlib
import importlib.abc
import importlib.machinery
import json
from pathlib import Path
import runpy
import sys
import types
from unittest.mock import patch

root = Path(sys.argv[1])
instrument = sys.argv[2] == "instrument"
instrumented = set()
loaded = []

def remember(code):
    instrumented.add(code)
    for constant in code.co_consts:
        if isinstance(constant, types.CodeType):
            remember(constant)

class ProductionLoader(importlib.machinery.SourceFileLoader):
    def get_code(self, fullname):
        code = super().get_code(fullname)
        remember(code)
        loaded.append(fullname)
        return code

class ProductionFinder(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path, target=None):
        if fullname != "webhook.server":
            return None
        spec = importlib.machinery.PathFinder.find_spec(fullname, path)
        spec.loader = ProductionLoader(fullname, spec.origin)
        return spec

@contextlib.contextmanager
def instrument_imports():
    finder = ProductionFinder()
    if instrument:
        sys.meta_path.insert(0, finder)
    try:
        yield
    finally:
        if instrument:
            sys.meta_path.remove(finder)

def instrument_func(function):
    if function.__code__ not in instrumented:
        # Model Atheris's code-object replacement when first instrumenting a
        # function, while leaving previously instrumented functions unchanged.
        function.__code__ = function.__code__.replace()
    return function

atheris = types.ModuleType("atheris")
atheris.instrument_imports = instrument_imports
atheris.instrument_func = instrument_func
sys.modules["atheris"] = atheris
with patch("subprocess.Popen", side_effect=AssertionError("Harness started a subprocess")):
    harness = runpy.run_path(str(root / "fuzz/fuzz_signature.py"), run_name="fuzz_import_probe")
    for seed in sorted((root / "fuzz/corpus/signature").iterdir()):
        if seed.is_file():
            harness["test_one_input"](seed.read_bytes())
assert loaded == ["webhook.server"], loaded
assert harness["verify_signature"].__module__ == "webhook.server"
print(json.dumps({"instrumented_modules": loaded}))
"""


def run_import_probe(mode):
    """Replay fixed seeds in a fresh process, with or without import hooks."""
    return subprocess.run(  # nosec B603 - fixed local test program and arguments
        [sys.executable, "-c", IMPORT_PROBE, str(ROOT), mode],
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )


def test_production_verifier_is_loaded_through_the_instrumentation_hook():
    result = run_import_probe("instrument")
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == {"instrumented_modules": ["webhook.server"]}
    assert (
        "Atheris production instrumentation verified: webhook.server.verify_signature"
        in result.stderr
    )


def test_fuzz_target_refuses_uninstrumented_production_code():
    result = run_import_probe("skip")
    assert result.returncode != 0
    assert "Production signature verifier was not instrumented during import" in result.stderr
    assert "Atheris production instrumentation verified" not in result.stderr
