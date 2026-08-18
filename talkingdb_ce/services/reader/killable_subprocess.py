import subprocess
import time
from typing import Callable, List, Optional, Tuple

_POLL_INTERVAL_SECONDS = 0.5


class ReadCancelled(Exception):
    """Raised when ``cancel_check`` reports cancellation mid-conversion."""


def run_killable(
    cmd: List[str],
    *,
    timeout_seconds: float,
    cancel_check: Optional[Callable[[], bool]] = None,
    poll_interval: float = _POLL_INTERVAL_SECONDS,
) -> Tuple[int, str, str]:
    """Run ``cmd`` with cancellation and timeout support.

    Returns ``(returncode, stdout, stderr)`` on success. Raises ``ReadCancelled``
    on cancellation and ``subprocess.TimeoutExpired`` on timeout; the child is
    killed in both cases.
    """
    proc = subprocess.Popen(
        cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
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
                proc.kill()
                proc.communicate()
                raise ReadCancelled(f"cancelled while running: {cmd[0]}")

            if time.monotonic() >= deadline:
                proc.kill()
                proc.communicate()
                raise subprocess.TimeoutExpired(cmd, timeout_seconds)
    finally:
        if proc.poll() is None:
            proc.kill()
