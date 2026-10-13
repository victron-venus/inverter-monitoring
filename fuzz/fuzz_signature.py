import sys
from pathlib import Path

import atheris

ROOT = Path(__file__).resolve().parents[1]
import importlib.util

spec = importlib.util.spec_from_file_location("fuzz_webhook_runtime", ROOT / "webhook/server.py")
runtime = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = runtime
with atheris.instrument_imports():
    spec.loader.exec_module(runtime)
runtime.WEBHOOK_SECRET = "synthetic-fuzz-key"

with atheris.instrument_imports():
    from fuzz_webhook_runtime import verify_signature


def test_one_input(data: bytes) -> None:
    import hashlib
    import hmac

    expected = "sha256=" + hmac.new(b"synthetic-fuzz-key", data, hashlib.sha256).hexdigest()
    assert verify_signature(data, expected)  # nosec B101 - intentional test oracle
    assert not verify_signature(data + b"x", expected)  # nosec B101 - intentional test oracle
    assert not verify_signature(data, data.decode("utf-8", errors="replace"))  # nosec B101 - intentional test oracle


if __name__ == "__main__":
    atheris.Setup(sys.argv, atheris.instrument_func(test_one_input))
    atheris.Fuzz()
