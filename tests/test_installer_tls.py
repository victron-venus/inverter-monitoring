"""Exercise the optional strong installer profile with local TLS and fake devices."""

import contextlib
import gzip
import http.server
import io
import os
import shutil
import ssl

# Test-only commands and paths are fixed or generated in private temporary directories.
import subprocess  # nosec B404
import tarfile
import threading
from pathlib import Path

import pytest

from webhook import server


def command(*args, **kwargs):
    """Execute fixed test tools and retain useful error output."""
    return subprocess.run(args, check=True, capture_output=True, timeout=30, **kwargs)  # nosec B603


@pytest.fixture(scope="module")
def tls_chains(tmp_path_factory):
    """Generate valid local chains with exactly one optional weak key."""
    root = tmp_path_factory.mktemp("installer-certs")
    for weak in ("none", "leaf", "intermediate", "root"):
        directory = root / weak
        directory.mkdir()
        for index, name in enumerate(("root", "intermediate", "leaf"), 1):
            bits = "2047" if name == weak else "3072"
            command(
                "openssl",
                "genpkey",
                "-algorithm",
                "RSA",
                "-pkeyopt",
                "rsa_keygen_bits:" + bits,
                "-out",
                name + ".key",
                cwd=directory,
            )
            command(
                "openssl",
                "req",
                "-new",
                "-key",
                name + ".key",
                "-out",
                name + ".csr",
                "-subj",
                "/CN=" + name,
                cwd=directory,
            )
            extension = "basicConstraints=critical,CA:TRUE\nkeyUsage=critical,keyCertSign,cRLSign\n"
            if name == "leaf":
                extension = "basicConstraints=critical,CA:FALSE\nkeyUsage=critical,digitalSignature,keyEncipherment\nextendedKeyUsage=serverAuth\nsubjectAltName=IP:127.0.0.1\n"
            (directory / (name + ".ext")).write_text(extension)
            issuer = "intermediate" if name == "leaf" else "root"
            signing = (
                ["-signkey", "root.key"]
                if name == "root"
                else ["-CA", issuer + ".pem", "-CAkey", issuer + ".key"]
            )
            command(
                "openssl",
                "x509",
                "-req",
                "-in",
                name + ".csr",
                *signing,
                "-set_serial",
                str(index),
                "-days",
                "1",
                "-sha256",
                "-extfile",
                name + ".ext",
                "-out",
                name + ".pem",
                cwd=directory,
            )
        (directory / "chain.pem").write_bytes(
            (directory / "leaf.pem").read_bytes() + (directory / "intermediate.pem").read_bytes()
        )
    return root


@pytest.fixture(scope="module")
def openssl_curl():
    """The strong profile explicitly requires an OpenSSL-backed curl."""
    for candidate in (
        shutil.which("curl"),
        "/opt/homebrew/opt/curl/bin/curl",
        "/usr/local/opt/curl/bin/curl",
    ):
        if (
            candidate
            and Path(candidate).is_file()
            and b" OpenSSL/" in command(candidate, "--version").stdout
        ):
            return candidate
    pytest.skip("OpenSSL-backed curl is required for this optional installer profile")


def install_command(monkeypatch):
    """Capture the actual generated remote script without invoking SSH."""
    calls = []
    monkeypatch.setattr(server, "TLS_SECURITY_LEVEL", "3")
    monkeypatch.setattr(
        server, "run_command", lambda args, timeout=300: (calls.append(args) or True, "")
    )
    assert server.update_inverter_control("v1.2.3")[0]
    return calls[0][-1]


@contextlib.contextmanager
def endpoint(directory, tls, payload):
    """Serve one disposable archive over a deliberately weak-capable TLS peer."""
    requests = []

    class Handler(http.server.BaseHTTPRequestHandler):
        """Record HTTP arrival separately from TLS handshake attempts."""

        def log_message(self, *_args):
            pass

        def do_GET(self):  # pylint: disable=invalid-name
            requests.append(self.path)
            self.send_response(200)
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.set_ciphers("DEFAULT:@SECLEVEL=0")  # Deliberately permissive fixture peer.
    context.minimum_version = context.maximum_version = tls
    context.load_cert_chain(directory / "chain.pem", directory / "leaf.key")
    with http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler) as httpd:
        httpd.socket = context.wrap_socket(httpd.socket, server_side=True)
        worker = threading.Thread(target=httpd.serve_forever, daemon=True)
        worker.start()
        try:
            yield f"https://127.0.0.1:{httpd.server_port}/source.tar.gz", requests
        finally:
            httpd.shutdown()
            worker.join(timeout=5)


@pytest.mark.parametrize("weak", ["none", "leaf", "intermediate", "root"])
@pytest.mark.parametrize("tls", [ssl.TLSVersion.TLSv1_2, ssl.TLSVersion.TLSv1_3])
def test_real_installer_enforces_strong_chain(
    monkeypatch, tmp_path, tls_chains, openssl_curl, weak, tls
):
    """A rejected chain must receive no HTTP or installer execution."""
    marker = tmp_path / "installed"
    script = f"#!/bin/sh\ntouch '{marker}'\n".encode()
    archive = io.BytesIO()
    with tarfile.open(fileobj=archive, mode="w") as tar:
        entry = tarfile.TarInfo("source/update.sh")
        entry.size = len(script)
        tar.addfile(entry, io.BytesIO(script))
    payload = gzip.compress(archive.getvalue())
    binary = tmp_path / "bin"
    binary.mkdir()
    (binary / "curl").symlink_to(openssl_curl)
    (tmp_path / ".curlrc").write_text("insecure\n")
    env = {
        **os.environ,
        "CURL_HOME": str(tmp_path),
        "PATH": str(binary) + os.pathsep + os.environ["PATH"],
        "CURL_CA_BUNDLE": str(tls_chains / weak / "root.pem"),
        "NO_PROXY": "*",
        "no_proxy": "*",
    }
    with endpoint(tls_chains / weak, tls, payload) as (url, requests):
        # Establish that even the deliberately weak chain is otherwise trusted/name-valid.
        command(
            openssl_curl, "--ciphers", "DEFAULT:@SECLEVEL=0", "--fail", "--silent", url, env=env
        )
        assert len(requests) == 1
        requests.clear()
        remote = (
            install_command(monkeypatch)
            .replace(
                "https://codeload.github.com/victron-venus/inverter-control/tar.gz/refs/tags/v1.2.3",
                url,
            )
            .replace("/data/.inverter-control-deploy.XXXXXX", str(tmp_path / "stage.XXXXXX"))
        )
        # The script is generated by application code and uses isolated test paths only.
        result = subprocess.run(
            ["/bin/sh", "-c", remote], env=env, capture_output=True, timeout=20, check=False
        )  # nosec B603
    assert (result.returncode == 0) is (weak == "none"), result.stderr
    assert marker.exists() is (weak == "none")
    assert len(requests) == (1 if weak == "none" else 0)
    assert not list(tmp_path.glob("stage.*"))


def test_strong_profile_rejects_non_openssl_before_transfer(monkeypatch, tmp_path):
    """Unsupported curl backends cannot silently ignore the selected policy."""
    binary = tmp_path / "bin"
    binary.mkdir()
    curl = binary / "curl"
    curl.write_text("#!/bin/sh\nprintf 'curl 8.0 SecureTransport LibreSSL/3.0\\n'\n")
    curl.chmod(0o700)
    remote = install_command(monkeypatch)
    env = {**os.environ, "PATH": str(binary) + os.pathsep + os.environ["PATH"]}
    result = subprocess.run(
        ["/bin/sh", "-c", remote], env=env, capture_output=True, timeout=20, check=False
    )  # nosec B603
    assert result.returncode != 0
    assert b"requires OpenSSL curl" in result.stderr


def test_invalid_tls_profile_never_invokes_ssh(monkeypatch):
    """Configuration typos fail before any network operation."""
    monkeypatch.setattr(server, "TLS_SECURITY_LEVEL", "invalid")
    monkeypatch.setattr(server, "run_command", lambda *_: pytest.fail("SSH must not run"))
    assert server.update_inverter_control("v1.2.3")[0] is False
