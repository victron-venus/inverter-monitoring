import importlib.util
import sys
from pathlib import Path

import atheris  # type: ignore[import-not-found, import-untyped]  # Atheris ships no type stubs.

ROOT = Path(__file__).resolve().parents[1]
TEST_WEBHOOK_SECRET = "synthetic-fuzz-key"  # nosec B105 - synthetic test-only key

spec = importlib.util.spec_from_file_location("fuzz_webhook_runtime", ROOT / "webhook/server.py")
if spec is None or spec.loader is None:
    raise RuntimeError("Unable to load webhook runtime for signature fuzzing")
runtime = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = runtime
with atheris.instrument_imports():
    spec.loader.exec_module(runtime)
setattr(runtime, "WEBHOOK_SECRET", TEST_WEBHOOK_SECRET)  # noqa: B010 - configure a dynamic module

verify_signature = runtime.verify_signature


def test_one_input(data: bytes) -> None:
    import hashlib
    import hmac

    expected = "sha256=" + hmac.new(TEST_WEBHOOK_SECRET.encode(), data, hashlib.sha256).hexdigest()
    assert verify_signature(data, expected)  # nosec B101 - intentional test oracle
    assert not verify_signature(data + b"x", expected)  # nosec B101 - intentional test oracle
    assert not verify_signature(data, data.decode("utf-8", errors="replace"))  # nosec B101 - intentional test oracle


if __name__ == "__main__":
    atheris.Setup(sys.argv, atheris.instrument_func(test_one_input))
    atheris.Fuzz()
