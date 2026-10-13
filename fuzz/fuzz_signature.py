import sys
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING, cast

import atheris

# Typeshed exposes the instrumentation APIs through their implementation modules.
if TYPE_CHECKING:
    from atheris.import_hook import instrument_imports
    from atheris.instrument_bytecode import instrument_func
else:
    instrument_imports = atheris.instrument_imports
    instrument_func = atheris.instrument_func

ROOT = Path(__file__).resolve().parents[1]
import importlib.util

spec = importlib.util.spec_from_file_location("fuzz_webhook_runtime", ROOT / "webhook/server.py")
if spec is None or spec.loader is None:
    raise RuntimeError("Cannot load the local webhook module")
runtime = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = runtime
with instrument_imports():
    spec.loader.exec_module(runtime)
# This isolated module uses only a public synthetic HMAC fixture.
runtime.__dict__["WEBHOOK_SECRET"] = "synthetic-fuzz-key"  # nosec B105

verify_signature = cast(Callable[[bytes, str], bool], runtime.verify_signature)


def test_one_input(data: bytes) -> None:
    import hashlib
    import hmac

    expected = "sha256=" + hmac.new(b"synthetic-fuzz-key", data, hashlib.sha256).hexdigest()
    assert verify_signature(data, expected)  # nosec B101 - intentional test oracle
    assert not verify_signature(data + b"x", expected)  # nosec B101 - intentional test oracle
    assert not verify_signature(data, data.decode("utf-8", errors="replace"))  # nosec B101 - intentional test oracle


if __name__ == "__main__":
    atheris.Setup(sys.argv, instrument_func(test_one_input))
    atheris.Fuzz()
