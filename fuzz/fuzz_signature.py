import importlib
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
TEST_WEBHOOK_SECRET = "synthetic-fuzz-key"  # nosec B105 - synthetic test-only key

sys.path.insert(0, str(ROOT))
with instrument_imports():
    runtime = importlib.import_module("webhook.server")
# This isolated module uses only a public synthetic HMAC fixture.
runtime.__dict__["WEBHOOK_SECRET"] = TEST_WEBHOOK_SECRET

verify_signature = cast(Callable[[bytes, str], bool], runtime.verify_signature)
# Atheris 3.1.0 leaves already-instrumented bytecode unchanged. Refuse to run
# if an import-hook regression would otherwise leave production code blind.
signature_code = verify_signature.__code__
instrument_func(verify_signature)
if verify_signature.__code__ is not signature_code:
    raise RuntimeError("Production signature verifier was not instrumented during import")
print(
    "Atheris production instrumentation verified: webhook.server.verify_signature",
    file=sys.stderr,
    flush=True,
)


def test_one_input(data: bytes) -> None:
    import hashlib
    import hmac

    expected = "sha256=" + hmac.new(TEST_WEBHOOK_SECRET.encode(), data, hashlib.sha256).hexdigest()
    assert verify_signature(data, expected)  # nosec B101 - intentional test oracle
    assert not verify_signature(data + b"x", expected)  # nosec B101 - intentional test oracle
    assert not verify_signature(data, data.decode("utf-8", errors="replace"))  # nosec B101 - intentional test oracle


if __name__ == "__main__":
    atheris.Setup(sys.argv, instrument_func(test_one_input))
    atheris.Fuzz()
