import os
import subprocess
import sys
from importlib.metadata import version
from pathlib import Path

from mommy_chaogu import __version__
from mommy_chaogu.web import create_app


def test_version_has_one_canonical_source() -> None:
    assert __version__ == "1.7.0"
    assert version("mommy-chaogu") == __version__
    assert create_app().version == __version__


def test_mommy_cli_version_flag_reports_canonical_version(tmp_path: Path) -> None:
    """`mommy --version` 打印裸版本号并 exit 0，不进 REPL/向导、不读 stdin。

    进程级验证（console script 的真实形态）：此前未识别参数会被忽略后继续
    启动，因此除了输出一致，还必须断言没有落入「已忽略无法识别的参数」路径。
    """
    code = (
        "import sys\n"
        "sys.argv = ['mommy', '--version']\n"
        "from mommy_chaogu.cli import main_mommy\n"
        "main_mommy()\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=tmp_path,
        env={**os.environ, "HOME": str(tmp_path)},
        text=True,
        capture_output=True,
        stdin=subprocess.DEVNULL,
        timeout=120,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == __version__
    assert "已忽略" not in result.stderr
