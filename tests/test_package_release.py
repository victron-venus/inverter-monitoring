"""Reject invalid package channels before invoking a version adapter."""

import hashlib
import json
import subprocess
import tarfile
from pathlib import Path
from unittest.mock import patch

import pytest

from scripts import package_release


@pytest.mark.parametrize("channel", ["stable", "--root=/tmp", "rc\n", "beta;id"])
def test_invalid_channel_cannot_reach_subprocess(tmp_path, channel):
    """The Python entrypoint has the same boundary as argparse choices."""
    (tmp_path / ".release-policy.json").write_text(
        json.dumps({"mode": "release", "versioning": {}}), encoding="utf-8"
    )
    (tmp_path / ".release-package.json").write_text("{}", encoding="utf-8")
    output = tmp_path / "release-dist"
    with (
        patch.object(package_release.subprocess, "run") as execute,
        pytest.raises(ValueError, match="Stable releases must promote"),
    ):
        package_release.build_candidate(tmp_path, "1.2.3", channel, output)
    execute.assert_not_called()
    assert not output.exists()


@pytest.mark.parametrize("escape", [False, True])
def test_container_paths_use_canonical_snapshot_root(tmp_path, monkeypatch, escape):
    """macOS /var aliases are valid; a context outside the snapshot is not."""
    source = tmp_path / "source"
    source.mkdir()
    (source / "Dockerfile").write_text("FROM scratch\n", encoding="utf-8")
    alias = tmp_path / "alias"
    alias.symlink_to(source, target_is_directory=True)
    monkeypatch.delenv("DOCKER_HOST", raising=False)
    config = {
        "containers": {
            "test.oci.tar": {"context": ".." if escape else ".", "dockerfile": "Dockerfile"}
        }
    }
    policy = {"container_assets": {"test.oci.tar": "example/test"}}
    with (
        patch.object(package_release.subprocess, "check_output", return_value="unix:///local"),
        patch.object(package_release.subprocess, "run") as execute,
    ):
        if escape:
            with pytest.raises(ValueError):
                package_release.build_containers(alias, tmp_path / "out", config, policy, {})
            execute.assert_not_called()
        else:
            package_release.build_containers(alias, tmp_path / "out", config, policy, {})
            assert execute.call_args.args[0][-1] == str(source.resolve())


def package_fixture(root):
    (root / "app").mkdir()
    script = root / "app/run.sh"
    script.write_text("#!/bin/sh\necho fixture\n", encoding="utf-8")
    script.chmod(0o755)
    (root / "version").write_text("1.2.3\n", encoding="utf-8")
    (root / ".release-policy.json").write_text(
        json.dumps({"mode": "release", "repository": "example/bridge", "version_file": "version"}),
        encoding="utf-8",
    )
    (root / ".release-package.json").write_text(
        json.dumps({"required": ["app", "version"], "include": ["app"]}), encoding="utf-8"
    )
    (root / ".mcp.json").write_text("{}", encoding="utf-8")
    (root / "analysis").mkdir()
    (root / "analysis/report.txt").write_text("not for distribution", encoding="utf-8")
    subprocess.run(["git", "init", "--quiet", str(root)], check=True)
    subprocess.run(
        [
            "git",
            "add",
            "app",
            "version",
            ".release-policy.json",
            ".release-package.json",
            ".mcp.json",
            "analysis",
        ],
        cwd=root,
        check=True,
    )
    # Release evidence is intentionally generated after git add; local secrets
    # are also untracked but must not receive the evidence-file exception.
    (root / ".release-plan.json").write_text('{"fixture":"plan"}', encoding="utf-8")
    (root / ".release-inputs.json").write_text('{"fixture":"inputs"}', encoding="utf-8")
    (root / "app/local-secret.txt").write_text("synthetic-private-fixture", encoding="utf-8")


def test_source_archive_preserves_scope_modes_evidence_and_bytes(tmp_path):
    package_fixture(tmp_path)
    first = tmp_path / "first"
    second = tmp_path / "second"
    results = [
        package_release.build_candidate(tmp_path, "1.2.3", "beta", output)
        for output in (first, second)
    ]
    assert all([path.name for path in paths] == ["bridge-1.2.3.tar.gz"] for paths in results)
    archive = results[0][0]
    raw = archive.read_bytes()
    assert results[1][0].read_bytes() == raw
    expected = f"{hashlib.sha256(raw).hexdigest()}  bridge-1.2.3.tar.gz\n"
    assert (first / "SHA256SUMS").read_text() == expected
    assert (second / "SHA256SUMS").read_text() == expected
    with tarfile.open(archive, "r:gz") as package:
        assert package.getnames() == [
            "bridge/.release-inputs.json",
            "bridge/.release-plan.json",
            "bridge/app/run.sh",
        ]
        script = package.getmember("bridge/app/run.sh")
        assert script.mode == 0o755
        assert package.getmember("bridge/.release-plan.json").mode == 0o644
        assert package.extractfile(script).read() == (tmp_path / "app/run.sh").read_bytes()


def test_missing_required_input_precedes_archive_and_cleans_snapshot(tmp_path, monkeypatch):
    package_fixture(tmp_path)
    (tmp_path / ".release-package.json").write_text(
        json.dumps({"required": ["app/missing", "also-missing"], "include": ["app"]}),
        encoding="utf-8",
    )
    snapshots = []
    real_temporary_directory = package_release.TemporaryDirectory

    def temporary_directory(**kwargs):
        temporary = real_temporary_directory(**kwargs)
        snapshots.append(Path(temporary.name))
        return temporary

    monkeypatch.setattr(package_release, "TemporaryDirectory", temporary_directory)
    output = tmp_path / "release-dist"
    with pytest.raises(ValueError, match="Required input is missing or not tracked: app/missing"):
        package_release.build_candidate(tmp_path, "1.2.3", "beta", output)
    assert list(output.iterdir()) == []
    assert len(snapshots) == 1
    assert not snapshots[0].exists()
