"""Download/upload speed measurement using the Ookla Speedtest CLI binary.

The Ookla CLI is located on ``PATH`` as ``speedtest`` and driven as a
subprocess.  Its JSON output reports bandwidth in **bytes per second**, so the
values are converted to Mbit/s here.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import time


INSTALL_HINT = (
    "Install the Ookla CLI from https://www.speedtest.net/apps/cli. On "
    "Raspberry Pi / Debian / Ubuntu: "
    "curl -s https://packagecloud.io/install/repositories/ookla/speedtest-cli/"
    "script.deb.sh | sudo bash && sudo apt install speedtest. "
    "Beware: the Debian 'speedtest-cli' package installs a *different* "
    "binary also called 'speedtest' at /usr/bin/speedtest."
)


class SpeedtestError(RuntimeError):
    """Raised when the Ookla speedtest cannot be run or parsed."""


def find_binary():
    """Return the path of the ``speedtest`` binary, or ``None``."""
    return shutil.which("speedtest") or shutil.which("speedtest.exe")


def detect_flavour():
    """Report what the ``speedtest`` on PATH actually is.

    Returns ``"ookla"``, ``"python-speedtest-cli"``, ``"unknown"`` or ``None``
    when no binary is present.
    """
    binary = find_binary()
    if binary is None:
        return None
    try:
        completed = subprocess.run(
            [binary, "--version"], capture_output=True, text=True, timeout=20
        )
    except (OSError, subprocess.SubprocessError):
        return None
    text = ((completed.stdout or "") + (completed.stderr or "")).lower()
    if "ookla" in text:
        return "ookla"
    if "speedtest-cli" in text or "matt martz" in text:
        return "python-speedtest-cli"
    return "unknown"


def can_run():
    """True only when an Ookla CLI is available (not the Python one)."""
    return detect_flavour() == "ookla"


def run_speedtest(server_id=None, timeout=180.0):
    """Run one Ookla speedtest and return a stats dict.

    Raises :class:`SpeedtestError` with an actionable message on failure.
    """
    binary = find_binary()
    if binary is None:
        raise SpeedtestError("Ookla 'speedtest' not found on PATH. " + INSTALL_HINT)

    flavour = detect_flavour()
    if flavour == "python-speedtest-cli":
        raise SpeedtestError(
            "the 'speedtest' on PATH is the Python speedtest-cli, not the Ookla "
            "CLI. " + INSTALL_HINT
        )

    command = [
        binary,
        "--format=json",
        "--accept-license",
        "--accept-gdpr",
    ]
    if server_id:
        command.append("--server-id={}".format(server_id))

    started = time.perf_counter()
    try:
        completed = subprocess.run(
            command, capture_output=True, text=True, timeout=timeout
        )
    except subprocess.TimeoutExpired:
        raise SpeedtestError("speedtest timed out after {:.0f}s".format(timeout))
    except OSError as exc:
        raise SpeedtestError("could not run '{}': {}".format(binary, exc))

    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout or "").strip()
        last_line = detail.splitlines()[-1] if detail else "no output"
        raise SpeedtestError(
            "speedtest exited with code {}: {}".format(completed.returncode, last_line)
        )

    try:
        data = json.loads((completed.stdout or "").strip())
    except ValueError as exc:
        raise SpeedtestError("could not parse speedtest JSON: {}".format(exc))

    return _stats_from_json(data, time.perf_counter() - started)


def _stats_from_json(data, elapsed):
    download = data.get("download") or {}
    upload = data.get("upload") or {}
    ping = data.get("ping") or {}
    server = data.get("server") or {}
    result = data.get("result") or {}

    name = server.get("name") or "?"
    location = server.get("location") or ""
    label = "{} ({})".format(name, location) if location else name

    return {
        # Ookla reports bandwidth in bytes/second -> Mbit/s.
        "down_mbps": _to_mbps(download.get("bandwidth")),
        "up_mbps": _to_mbps(upload.get("bandwidth")),
        "speed_server": label,
        "speed_server_id": server.get("id"),
        "speed_latency_ms": ping.get("latency"),
        "speed_jitter_ms": ping.get("jitter"),
        "speed_result_url": result.get("url"),
        "speed_duration_s": round(elapsed, 1),
        "error": None,
    }


def _to_mbps(bytes_per_second):
    if bytes_per_second in (None, ""):
        return None
    return float(bytes_per_second) * 8.0 / 1_000_000.0


def list_servers():
    """Return the raw ``speedtest --servers`` output (best effort)."""
    binary = find_binary()
    if binary is None:
        raise SpeedtestError("Ookla 'speedtest' not found on PATH. " + INSTALL_HINT)
    completed = subprocess.run(
        [binary, "--servers", "--accept-license", "--accept-gdpr"],
        capture_output=True,
        text=True,
        timeout=60,
    )
    return (completed.stdout or "") + (completed.stderr or "")

