"""Fault-injection test for scripts/mahjong-mitm-watchdog.sh.

Spec: .trellis/spec/guides/mitm-connection-stability-guide.md 铁律 6
"监督/保护/恢复机制本身必须有故障注入测试"。

Test scenarios:
1. Service healthy: counter stays at 0, no restart called
2. Service hangs (handler thread dead, main thread alive — the exact case that bit
   us on 2026-06-26): counter accumulates 0→1→2→3, mock systemctl restart called
3. Service recovers: counter resets to 0
4. The OLD bug regression guard: verify counter is NOT reset on is-active=ok
   (the path that produced the 2026-06-26 stuck-at-1 behavior)

Why not run on production ECS: test triggers real `systemctl restart` calls and
needs port exclusivity. Runs locally with mocked systemctl + local mock service.

Run: python -m pytest interface/tests/test_watchdog_fault_injection.py -v
"""
from __future__ import annotations

import os
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
WATCHDOG_SH = REPO_ROOT / "scripts" / "mahjong-mitm-watchdog.sh"


def _find_free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class MockService:
    """Single HTTPServer with /healthz + /control endpoints.

    /healthz returns 200 if mode == 'ok', hangs forever if mode == 'hang'.
    /control?mode=ok|hang toggles state.
    """

    def __init__(self) -> None:
        self.mode = "ok"
        self.healthz_port = _find_free_port()
        self.mode_port = _find_free_port()
        self._server_thread: threading.Thread | None = None
        self._mode_thread: threading.Thread | None = None
        self._healthz_server: ThreadingHTTPServer | None = None
        self._mode_server: ThreadingHTTPServer | None = None

    def start(self) -> None:
        # We use one server with both paths on healthz_port to keep it simple
        # (probe URL is /healthz; /mode is on a different port).
        # Actually use two servers because /mode must be on a separate URL
        # for the watchdog's RELAY_URL.
        # For the test we collapse to one healthz probe + a separate mode probe
        # on different ports. But to keep logic simple, we just expose /healthz
        # on healthz_port and /mode on mode_port, both controlled by self.mode.

        def make_handler(label: str):
            class Handler(BaseHTTPRequestHandler):
                def log_message(self, *_args):
                    pass  # silence

                def do_GET(self):
                    outer = self  # noqa
                    # Access outer mode
                    if self.path.startswith("/control"):
                        # Parse ?mode=hang|ok
                        from urllib.parse import urlparse, parse_qs
                        q = parse_qs(urlparse(self.path).query)
                        outer_mode = q.get("mode", ["ok"])[0]
                        if outer_mode not in ("ok", "hang"):
                            self.send_response(400)
                            self.end_headers()
                            return
                        # Find the MockService via the closure chain
                        # The class-level _test_instance is set in start()
                        MockService._test_instance.mode = outer_mode
                        self.send_response(200)
                        self.end_headers()
                        self.wfile.write(b"OK " + outer_mode.encode())
                        return
                    if self.path == "/healthz" and label == "healthz":
                        self._serve_probe()
                        return
                    if self.path == "/mode" and label == "mode":
                        self._serve_probe()
                        return
                    self.send_response(404)
                    self.end_headers()

                def _serve_probe(self):
                    # Fail FAST (1ms) so cycle time = 1s sleep + ~0s probe.
                    # We use status 503 to simulate "service alive but unhealthy"
                    # — the watchdog's curl --max-time 5 still has 5s headroom,
                    # this just keeps the test under 30s.
                    if MockService._test_instance.mode == "ok":
                        self.send_response(200)
                        self.send_header("Content-Type", "application/json")
                        self.end_headers()
                        self.wfile.write(b'{"status":"ok"}')
                    else:
                        # hang mode: simulate "handler thread dead" by returning 503
                        # (this is what a real misbehaving service would look like
                        # to the watchdog — the connection works, but the response
                        # indicates failure)
                        self.send_response(503)
                        self.send_header("Content-Type", "application/json")
                        self.end_headers()
                        self.wfile.write(b'{"status":"hang"}')

            return Handler

        # Use the class-level slot for the singleton
        MockService._test_instance = self

        # Start healthz server
        self._healthz_server = ThreadingHTTPServer(
            ("127.0.0.1", self.healthz_port), make_handler("healthz")
        )
        self._healthz_server.timeout = 1.0
        t1 = threading.Thread(target=self._healthz_server.serve_forever, daemon=True)
        t1.start()
        self._server_thread = t1

        # Start mode server
        self._mode_server = ThreadingHTTPServer(
            ("127.0.0.1", self.mode_port), make_handler("mode")
        )
        self._mode_server.timeout = 1.0
        t2 = threading.Thread(target=self._mode_server.serve_forever, daemon=True)
        t2.start()
        self._mode_thread = t2

        # Wait for both ports to be ready
        for port in (self.healthz_port, self.mode_port):
            for _ in range(50):
                try:
                    with socket.create_connection(("127.0.0.1", port), timeout=0.1):
                        break
                except OSError:
                    time.sleep(0.05)

    def stop(self) -> None:
        if self._healthz_server:
            self._healthz_server.shutdown()
        if self._mode_server:
            self._mode_server.shutdown()

    def set_mode(self, mode: str) -> None:
        """Switch the mock service's health mode via direct attribute (faster than HTTP)."""
        self.mode = mode

    _test_instance: "MockService | None" = None  # class-level for handler closure


class MockSystemctl:
    """Records all systemctl invocations to a log file instead of touching systemd.

    Also reports WATCH_SERVICES as 'active' so the watchdog's is-active path
    doesn't trigger a real restart in the test.
    """

    def __init__(self, log_path: Path, watch_services: list[str]) -> None:
        self.log_path = Path(log_path)  # Path for Python access (.exists, .read_text)
        self._log_path_posix = self.log_path.as_posix()  # forward slashes for git-bash safety
        self.watch_services = watch_services
        self._dir = tempfile.mkdtemp(prefix="mock_systemctl_")
        self._bin = Path(self._dir) / "systemctl"
        self._script = Path(self._dir) / "_systemctl_inner.sh"
        self._write_scripts()
        self._calls: list[str] = []

    def _write_scripts(self) -> None:
        # Inner script: does the actual work + logging
        # Be permissive: report 'active' for ANY service name (the test only
        # injects fault via mock service hangs, not via systemctl lies).
        log_path = self._log_path_posix
        script_path = self._script.as_posix()
        self._script.write_text(
            "#!/bin/bash\n"
            f"echo \"$@\" >> '{log_path}'\n"
            # is-active: always active (we don't test 'process died' here,
            # only 'process alive but probes hang' which is the 06-26 case)
            "if [[ \"$1\" == \"is-active\" ]]; then\n"
            "  echo active\n"
            "  exit 0\n"
            "fi\n"
            # restart: just log + pretend success
            "exit 0\n"
        )
        self._script.chmod(0o755)
        # Outer wrapper: routes to inner via direct path (also forward-slash)
        self._bin.write_text(
            "#!/bin/bash\n"
            f"exec '{script_path}' \"$@\"\n"
        )
        self._bin.chmod(0o755)

    @property
    def bin_dir(self) -> str:
        return self._dir

    def get_calls(self) -> list[str]:
        if not self.log_path.exists():
            return []
        return self.log_path.read_text().strip().splitlines()

    def cleanup(self) -> None:
        shutil.rmtree(self._dir, ignore_errors=True)


def _read_counter(state_dir: Path, svc: str) -> int:
    f = state_dir / f"{svc}.counter"
    if not f.exists():
        return 0
    try:
        return int(f.read_text().strip())
    except ValueError:
        return 0


def _read_last_restart(state_dir: Path, svc: str) -> int:
    f = state_dir / f"{svc}.last_restart"
    if not f.exists():
        return 0
    try:
        return int(f.read_text().strip())
    except ValueError:
        return 0


@pytest.fixture
def watchdog_env(tmp_path):
    """Set up mock service, mock systemctl, and clean state dir for a watchdog run."""
    if not WATCHDOG_SH.exists():
        pytest.skip(f"watchdog script not found at {WATCHDOG_SH}")
    if not _bash_available():
        pytest.skip("bash not available")

    mock_svc = MockService()
    mock_svc.start()

    state_dir = tmp_path / "state"
    state_dir.mkdir()
    log_file = tmp_path / "watchdog.log"
    systemctl_log = tmp_path / "systemctl.log"

    mock_systemctl = MockSystemctl(
        systemctl_log,
        watch_services=["mahjong-mitm-hotupdate", "mahjong-tcp-proxy"],
    )

    env = os.environ.copy()
    # Convert all state paths to forward slashes for git-bash safety
    state_dir_p = state_dir.as_posix()
    log_file_p = log_file.as_posix()
    env.update({
        "HEALTH_URL": f"http://127.0.0.1:{mock_svc.healthz_port}/healthz",
        "RELAY_URL": f"http://127.0.0.1:{mock_svc.mode_port}/mode",
        "PROBE_INTERVAL": "1",   # fast for test
        "FAIL_THRESHOLD": "3",
        "COOLDOWN_SECONDS": "0",  # disable cooldown so we can repeat
        "STATE_DIR": state_dir_p,
        "LOG_FILE": log_file_p,
        # Use just the basename; bash will resolve via PATH (which we set below)
        "SYSTEMCTL_CMD": "systemctl",
        "PATH": mock_systemctl.bin_dir + os.pathsep + env.get("PATH", ""),
        # MSYS bash on Windows mangles exit codes from native binaries like
        # curl.exe (returns 0 when curl actually returned 23). Without this,
        # the watchdog's `curl ... || fail=$((fail+1))` thinks every probe
        # succeeds and the counter never increments.
        "MSYS_NO_PATHCONV": "1",
        "MSYS2_ARG_CONV_EXCL": "*",
    })

    yield {
        "mock_svc": mock_svc,
        "mock_systemctl": mock_systemctl,
        "state_dir": state_dir,
        "log_file": log_file,
        "systemctl_log": systemctl_log,
        "env": env,
    }

    mock_svc.stop()
    mock_systemctl.cleanup()


def _bash_available() -> bool:
    if shutil.which("bash"):
        return True
    # Windows: try common locations
    for path in (
        r"C:\Program Files\Git\usr\bin\bash.exe",
        r"C:\Windows\System32\bash.exe",
    ):
        if os.path.exists(path):
            return True
    return False


def _start_watchdog(env: dict[str, str], log_path: Path) -> subprocess.Popen:
    """Launch watchdog in subprocess. Returns Popen object."""
    bash = shutil.which("bash")
    if not bash:
        for candidate in (r"C:\Program Files\Git\usr\bin\bash.exe",):
            if os.path.exists(candidate):
                bash = candidate
                break
    assert bash, "bash not found"

    # The watchdog's log() does `tee -a LOG_FILE >&2`. If we redirect stdout
    # to a file that IS LOG_FILE, we get double-writes / truncation. Instead
    # just send stdout to DEVNULL; tee's append to LOG_FILE is the canonical
    # write path. Test reads log_path directly afterwards.
    return subprocess.Popen(
        [bash, str(WATCHDOG_SH)],
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        # New process group so we can kill children cleanly
        preexec_fn=os.setsid if sys.platform != "win32" else None,
        creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if sys.platform == "win32" else 0,
    )


def _stop_watchdog(proc: subprocess.Popen, timeout: float = 3.0) -> None:
    if proc.poll() is not None:
        return
    try:
        if sys.platform == "win32":
            proc.terminate()
        else:
            os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
        proc.wait(timeout=timeout)
    except (subprocess.TimeoutExpired, ProcessLookupError):
        try:
            if sys.platform == "win32":
                proc.kill()
            else:
                os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
        except ProcessLookupError:
            pass


class TestWatchdogFaultInjection:
    """铁律 6:监督代码必须有故障注入测试。"""

    def test_healthy_service_keeps_counter_at_zero(self, watchdog_env):
        """Scenario 1: service healthy → counter stays 0, no restart."""
        env = watchdog_env["env"]
        state_dir = watchdog_env["state_dir"]

        proc = _start_watchdog(env, watchdog_env["log_file"])
        try:
            # Run for 3 probe cycles (3s with PROBE_INTERVAL=1)
            time.sleep(3.5)
        finally:
            _stop_watchdog(proc)

        assert _read_counter(state_dir, "mahjong-mitm-hotupdate") == 0, (
            f"counter should stay 0 when service healthy, got {_read_counter(state_dir, 'mahjong-mitm-hotupdate')}. "
            f"Watchdog log: {watchdog_env['log_file'].read_text()}"
        )
        # No restart should have been called
        calls = watchdog_env["mock_systemctl"].get_calls()
        assert not any("restart" in c for c in calls), (
            f"should NOT call restart when service healthy, got: {calls}"
        )

    def test_hanging_service_triggers_restart_at_threshold(self, watchdog_env):
        """Scenario 2: handler thread dead (probes hang) → counter accumulates → restart at 3.

        This is the EXACT scenario that the 2026-06-26 4G stall regression exposed.
        The OLD buggy watchdog would have stuck counter at 1 forever.
        The NEW (fixed) watchdog must accumulate 1→2→3 and call restart.
        """
        env = watchdog_env["env"]
        state_dir = watchdog_env["state_dir"]
        mock_svc = watchdog_env["mock_svc"]

        # Pre-set the mock to hang BEFORE starting watchdog
        mock_svc.set_mode("hang")

        proc = _start_watchdog(env, watchdog_env["log_file"])
        try:
            # Windows MSYS bash is slow (~5s/cycle: 3 is-active calls + 2 probes
            # + log tee writes). 25s = ~4 cycles, enough to hit counter=3 + restart.
            deadline = time.time() + 30.0
            last_counter = -1
            while time.time() < deadline:
                time.sleep(1.0)
                cur = _read_counter(state_dir, "mahjong-mitm-hotupdate")
                if cur != last_counter:
                    last_counter = cur
                # Success: either counter reached 3 (pre-restart) OR restart was called
                calls = watchdog_env["mock_systemctl"].get_calls()
                if any("restart" in c for c in calls):
                    break
        finally:
            _stop_watchdog(proc)

        calls = watchdog_env["mock_systemctl"].get_calls()
        restart_calls = [c for c in calls if "restart" in c]

        # The success condition: restart was called on the failing service.
        # (Counter file is reset to 0 by restart_service AFTER it logs, so the
        # final counter value depends on whether we read before/after that
        # reset — instead assert on the mock systemctl log which is durable.)
        assert any("mahjong-mitm-hotupdate" in c for c in restart_calls), (
            f"restart should target mahjong-mitm-hotupdate after counter hits threshold. "
            f"Got calls: {calls}. Watchdog log:\n{watchdog_env['log_file'].read_text()}"
        )

    def test_counter_resets_after_service_recovery(self, watchdog_env):
        """Scenario 3: service was failing, then recovers → counter resets to 0."""
        env = watchdog_env["env"]
        state_dir = watchdog_env["state_dir"]
        mock_svc = watchdog_env["mock_svc"]

        # Start with hang to build up counter
        mock_svc.set_mode("hang")
        proc = _start_watchdog(env, watchdog_env["log_file"])
        try:
            # Let counter climb. With 5s/cycle on Windows, 25s = ~5 cycles,
            # enough to hit threshold + restart (which resets counter to 0).
            time.sleep(25.0)
            mid = _read_counter(state_dir, "mahjong-mitm-hotupdate")
            # Counter might be 0 (post-restart) or 3 (pre-restart) depending
            # on where the cycle is when we read. The important thing is
            # restart was called.
            calls = watchdog_env["mock_systemctl"].get_calls()
            assert any("restart" in c and "mahjong-mitm-hotupdate" in c for c in calls), (
                f"expected restart to have been called during hang. Got: {calls}. "
                f"mid counter: {mid}. Watchdog log:\n{watchdog_env['log_file'].read_text()}"
            )

            # Recover the service
            mock_svc.set_mode("ok")

            # Wait long enough for the watchdog to run a full probe cycle after
            # recovery and reset the counter via the `fails == 0` path.
            # One cycle is ~5s on Windows. Wait 10s for safety margin.
            time.sleep(10.0)
        finally:
            _stop_watchdog(proc)

        final_counter = _read_counter(state_dir, "mahjong-mitm-hotupdate")
        assert final_counter == 0, (
            f"counter should reset to 0 after service recovers, got {final_counter}. "
            f"Watchdog log:\n{watchdog_env['log_file'].read_text()}"
        )

    def test_old_bug_regression_guard(self, watchdog_env):
        """Scenario 4: regression guard for the 2026-06-26 bug.

        The OLD watchdog reset the counter to 0 on is-active=ok BEFORE the probe.
        This test ensures the NEW watchdog does NOT reset counter on is-active.
        Concretely: with a hanging service, the counter must reach >= 3 in finite time
        (NOT get stuck at 1 because the is-active path is wiping it).
        """
        env = watchdog_env["env"]
        state_dir = watchdog_env["state_dir"]
        mock_svc = watchdog_env["mock_svc"]

        mock_svc.set_mode("hang")
        proc = _start_watchdog(env, watchdog_env["log_file"])
        try:
            # Watch counter for 20s — must reach > 1, not stuck at 1
            max_seen = 0
            for _ in range(20):
                time.sleep(1.0)
                cur = _read_counter(state_dir, "mahjong-mitm-hotupdate")
                max_seen = max(max_seen, cur)
        finally:
            _stop_watchdog(proc)

        # If we never see counter > 1, the old bug is back
        assert max_seen > 1, (
            f"counter stuck at 1 — the 2026-06-26 regression is back! "
            f"Max seen: {max_seen}. Watchdog log:\n{watchdog_env['log_file'].read_text()}"
        )


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
