"""Reject invalid package channels before invoking a version adapter."""

import json
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
