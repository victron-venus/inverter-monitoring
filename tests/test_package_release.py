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
