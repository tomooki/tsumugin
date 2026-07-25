"""親プロセス監視ウォッチドッグの実プロセステスト (V2c レビュー指摘 #1 「孤児 sidecar」)。

`desktop/sidecar/tsumugin_workbench_sidecar.py` は `--parent-pid` を渡されると、Windows API
(``ctypes``: ``OpenProcess`` + ``WaitForSingleObject``) で指定 PID の終了を監視するデーモン
スレッドを起動する (``_watch_parent_pid``)。タスクマネージャ等で親プロセス (Tauri シェル) が
強制終了された場合でも、素の ``std::process::Command`` で spawn された sidecar が孤児化しない
ことを保証する安全機構であり、モックではなく実プロセスで検証する:
子プロセス (sidecar) を起動 → 疑似親プロセスを kill → 子が自発的に終了することを実測する。

Windows 専用 (``ctypes.windll`` 依存, sidecar 側も同様) — 他 OS では skip する。
"""

from __future__ import annotations

import queue
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(
    sys.platform != "win32",
    reason="親プロセス監視ウォッチドッグは Windows (ctypes.windll) 専用",
)

_REPO_ROOT = Path(__file__).resolve().parents[2]
_SIDECAR_ENTRY = _REPO_ROOT / "desktop" / "sidecar" / "tsumugin_workbench_sidecar.py"

_WATCHDOG_STARTED_MARKER = "watching parent pid"
_STARTUP_TIMEOUT_S = 20.0
_EXIT_TIMEOUT_S = 20.0


def _free_port() -> int:
    """OS にポートを割り当てさせる — 固定ポートだと他のテスト/実行中インスタンスと衝突しうる。"""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _stream_reader(stream, out_queue: "queue.Queue[str | None]") -> None:
    """子プロセスの stderr を行単位で queue へ流し込む (ブロッキング readline を別スレッドへ
    逃がすことで、呼び出し側がタイムアウト付きで待てるようにする)。"""
    try:
        for line in iter(stream.readline, ""):
            out_queue.put(line)
    finally:
        out_queue.put(None)


def _wait_for_marker(out_queue: "queue.Queue[str | None]", marker: str, timeout_s: float) -> bool:
    deadline = time.monotonic() + timeout_s
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return False
        try:
            line = out_queue.get(timeout=remaining)
        except queue.Empty:
            return False
        if line is None:
            return False
        if marker in line:
            return True


def test_sidecar_exits_when_parent_process_is_killed() -> None:
    """子 (sidecar) プロセスを起動し、疑似親プロセスを kill すると子が自発的に終了する。"""
    fake_parent = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(120)"],
    )
    sidecar: subprocess.Popen | None = None
    try:
        port = _free_port()
        sidecar = subprocess.Popen(
            [
                sys.executable,
                str(_SIDECAR_ENTRY),
                "--host",
                "127.0.0.1",
                "--port",
                str(port),
                "--parent-pid",
                str(fake_parent.pid),
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
        )

        out_queue: "queue.Queue[str | None]" = queue.Queue()
        reader = threading.Thread(
            target=_stream_reader, args=(sidecar.stderr, out_queue), daemon=True
        )
        reader.start()

        started = _wait_for_marker(out_queue, _WATCHDOG_STARTED_MARKER, _STARTUP_TIMEOUT_S)
        if not started and sidecar.poll() is not None:
            pytest.fail(
                f"sidecar exited before the watchdog started (rc={sidecar.returncode})"
            )
        assert started, "sidecar never logged that its parent watchdog started"

        # 【疑似親を kill】: 実際の OS プロセス終了で監視スレッドの WaitForSingleObject が
        #   シグナルされることを確認する — シミュレーションではない。
        fake_parent.kill()
        fake_parent.wait(timeout=10)

        try:
            sidecar.wait(timeout=_EXIT_TIMEOUT_S)
        except subprocess.TimeoutExpired:
            pytest.fail(
                f"sidecar did not exit within {_EXIT_TIMEOUT_S}s of its parent process dying "
                "(orphaned)"
            )
        assert sidecar.returncode is not None
    finally:
        if sidecar is not None and sidecar.poll() is None:
            sidecar.kill()
            sidecar.wait(timeout=10)
        if fake_parent.poll() is None:
            fake_parent.kill()
            fake_parent.wait(timeout=10)
