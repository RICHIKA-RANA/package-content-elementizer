import os
import signal
import subprocess
import time
from typing import Callable, List, Optional, Tuple

_POLL_INTERVAL_SECONDS = 0.5


class ReadCancelled(Exception):
    """Raised when ``cancel_check`` reports cancellation mid-conversion."""


def _kill_process_group(proc: subprocess.Popen) -> None:
    try:
        os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
    except ProcessLookupError:
        pass  # already exited


def run_killable(
    cmd: List[str],
    *,
    timeout_seconds: float,
    cancel_check: Optional[Callable[[], bool]] = None,
    poll_interval: float = _POLL_INTERVAL_SECONDS,
) -> Tuple[int, str, str]:
    """Run ``cmd`` with cancellation and timeout support.

    Returns ``(returncode, stdout, stderr)`` on success. Raises ``ReadCancelled``
    on cancellation and ``subprocess.TimeoutExpired`` on timeout; the whole
    process group is killed and reaped in both cases, and in the ``finally``
    cleanup for any other exception.
    """
    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        start_new_session=True,
    )
    deadline = time.monotonic() + timeout_seconds

    try:
        while True:
            try:
                stdout, stderr = proc.communicate(timeout=poll_interval)
                return proc.returncode, stdout, stderr
            except subprocess.TimeoutExpired:
                pass

            if cancel_check is not None and cancel_check():
                _kill_process_group(proc)
                proc.communicate()
                raise ReadCancelled(f"cancelled while running: {cmd[0]}")

            if time.monotonic() >= deadline:
                _kill_process_group(proc)
                proc.communicate()
                raise subprocess.TimeoutExpired(cmd, timeout_seconds)
    finally:
        if proc.poll() is None:
            _kill_process_group(proc)
            proc.wait()
