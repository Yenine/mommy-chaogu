"""One-line installer contract tests."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INSTALLER = ROOT / "install.sh"


def test_installer_is_valid_posix_shell() -> None:
    result = subprocess.run(
        ["sh", "-n", str(INSTALLER)],
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr


def test_installer_uses_uv_tool_and_verifies_mommy() -> None:
    text = INSTALLER.read_text(encoding="utf-8")

    assert "uv/install.sh" in text
    assert "tool install" in text
    assert '"$mommy_binary" --help' in text
    assert "curl -LsSf https://github.com/coffee-man666/mommy-chaogu/raw/" in text


def test_installer_runs_with_an_existing_uv(tmp_path: Path) -> None:
    fake_bin = tmp_path / "fake-bin"
    tool_bin = tmp_path / "tool-bin"
    fake_bin.mkdir()
    tool_bin.mkdir()
    log = tmp_path / "uv.log"
    curl_log = tmp_path / "curl.log"
    fake_curl = fake_bin / "curl"
    fake_curl.write_text(
        """#!/bin/sh
set -eu
printf '%s\\n' "$*" >> "$FAKE_CURL_LOG"
exit 99
""",
        encoding="utf-8",
    )
    fake_curl.chmod(0o755)
    fake_uv = fake_bin / "uv"
    fake_uv.write_text(
        """#!/bin/sh
set -eu
printf '%s\\n' "$*" >> "$FAKE_UV_LOG"
if [ "${1:-} ${2:-} ${3:-}" = "tool dir --bin" ]; then
    printf '%s\\n' "$FAKE_TOOL_BIN"
elif [ "${1:-} ${2:-}" = "tool install" ]; then
    printf '#!/bin/sh\\nexit 0\\n' > "$FAKE_TOOL_BIN/mommy"
    chmod +x "$FAKE_TOOL_BIN/mommy"
fi
""",
        encoding="utf-8",
    )
    fake_uv.chmod(0o755)
    env = {
        **os.environ,
        "PATH": f"{fake_bin}:{os.environ.get('PATH', '')}",
        "HOME": str(tmp_path / "home"),
        "FAKE_UV_LOG": str(log),
        "FAKE_TOOL_BIN": str(tool_bin),
        "FAKE_CURL_LOG": str(curl_log),
        "MOMMY_INSTALL_SOURCE": "mommy-chaogu @ https://example.test/mommy.tar.gz",
    }

    result = subprocess.run(
        ["sh", str(INSTALLER)],
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert "mommy-chaogu 安装完成" in result.stdout
    calls = log.read_text(encoding="utf-8")
    assert (
        "tool install --quiet --quiet --refresh-package mommy-chaogu "
        "--reinstall-package mommy-chaogu --python 3.12" in calls
    )
    assert "tool dir --bin" in calls
    assert not curl_log.exists(), "explicit source must skip latest-release probing"


def test_installer_fails_when_latest_release_cannot_be_resolved(tmp_path: Path) -> None:
    fake_bin = tmp_path / "fake-bin"
    fake_bin.mkdir()
    uv_log = tmp_path / "uv.log"
    fake_curl = fake_bin / "curl"
    fake_curl.write_text(
        """#!/bin/sh
set -eu
printf '%s\\n' "$*" >> "$FAKE_CURL_LOG"
printf '{}'
""",
        encoding="utf-8",
    )
    fake_curl.chmod(0o755)
    fake_uv = fake_bin / "uv"
    fake_uv.write_text(
        """#!/bin/sh
set -eu
printf '%s\\n' "$*" >> "$FAKE_UV_LOG"
exit 99
""",
        encoding="utf-8",
    )
    fake_uv.chmod(0o755)

    result = subprocess.run(
        ["sh", str(INSTALLER)],
        env={
            **os.environ,
            "PATH": f"{fake_bin}:{os.environ.get('PATH', '')}",
            "HOME": str(tmp_path / "home"),
            "FAKE_CURL_LOG": str(tmp_path / "curl.log"),
            "FAKE_UV_LOG": str(uv_log),
        },
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode != 0
    assert "无法解析最新 release" in result.stderr
    assert not uv_log.exists(), "release resolution must fail before installation"


def test_installer_binds_default_source_to_valid_release_tag(tmp_path: Path) -> None:
    fake_bin = tmp_path / "fake-bin"
    tool_bin = tmp_path / "tool-bin"
    fake_bin.mkdir()
    tool_bin.mkdir()
    uv_log = tmp_path / "uv.log"
    curl_log = tmp_path / "curl.log"
    fake_curl = fake_bin / "curl"
    fake_curl.write_text(
        """#!/bin/sh
set -eu
printf '%s\\n' "$*" >> "$FAKE_CURL_LOG"
printf '%s' '{"tag_name":"v1.2.3"}'
""",
        encoding="utf-8",
    )
    fake_curl.chmod(0o755)
    fake_uv = fake_bin / "uv"
    fake_uv.write_text(
        """#!/bin/sh
set -eu
printf '%s\\n' "$*" >> "$FAKE_UV_LOG"
if [ "${1:-} ${2:-} ${3:-}" = "tool dir --bin" ]; then
    printf '%s\\n' "$FAKE_TOOL_BIN"
elif [ "${1:-} ${2:-}" = "tool install" ]; then
    printf '#!/bin/sh\\nexit 0\\n' > "$FAKE_TOOL_BIN/mommy"
    chmod +x "$FAKE_TOOL_BIN/mommy"
fi
""",
        encoding="utf-8",
    )
    fake_uv.chmod(0o755)

    result = subprocess.run(
        ["sh", str(INSTALLER)],
        env={
            **os.environ,
            "PATH": f"{fake_bin}:{os.environ.get('PATH', '')}",
            "HOME": str(tmp_path / "home"),
            "FAKE_CURL_LOG": str(curl_log),
            "FAKE_UV_LOG": str(uv_log),
            "FAKE_TOOL_BIN": str(tool_bin),
        },
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    calls = uv_log.read_text(encoding="utf-8")
    assert "/archive/refs/tags/v1.2.3.tar.gz" in calls
    assert "/archive/refs/heads/main.tar.gz" not in calls
    assert "releases/latest" in curl_log.read_text(encoding="utf-8")


def test_installer_fails_when_latest_request_returns_nonzero(tmp_path: Path) -> None:
    fake_bin = tmp_path / "fake-bin"
    fake_bin.mkdir()
    uv_log = tmp_path / "uv.log"
    fake_curl = fake_bin / "curl"
    fake_curl.write_text(
        """#!/bin/sh
set -eu
printf '%s' '{"tag_name":"v9.9.9"}'
exit 42
""",
        encoding="utf-8",
    )
    fake_curl.chmod(0o755)
    fake_uv = fake_bin / "uv"
    fake_uv.write_text(
        """#!/bin/sh
set -eu
printf '%s\\n' "$*" >> "$FAKE_UV_LOG"
exit 99
""",
        encoding="utf-8",
    )
    fake_uv.chmod(0o755)

    result = subprocess.run(
        ["sh", str(INSTALLER)],
        env={
            **os.environ,
            "PATH": f"{fake_bin}:{os.environ.get('PATH', '')}",
            "HOME": str(tmp_path / "home"),
            "FAKE_UV_LOG": str(uv_log),
        },
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode != 0
    assert "无法解析最新 release" in result.stderr
    assert not uv_log.exists(), "curl failure must fail before installation"
