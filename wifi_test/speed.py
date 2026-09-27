"""Download/upload speed measurement using the Ookla Speedtest CLI binary.

The Ookla CLI is located on ``PATH`` as ``speedtest`` and driven as a
subprocess.  Its JSON output reports bandwidth in **bytes per second**, so the
values are converted to Mbit/s here.
"""

from __future__ import annotations

import json
import os
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

RATE_LIMIT_HINT = (
    "Ookla is rate limiting this public IP (HTTP 429 'Too many requests'). "
    "Every device shares that limit, so lower the speed-test frequency: "
    "raise --interval, use --speed-every N, keep --speed-devices at 1 (tests are "
    "then rotated between devices), and avoid running --list-servers/check in a "
    "loop. Pinning a server with --speed-server-id also cuts API calls. "
    "Speed tests resume automatically after --speed-cooldown minutes."
)


class SpeedtestError(RuntimeError):
    """Raised when the Ookla speedtest cannot be run or parsed."""


def is_rate_limited(message):
    """True when *message* looks like Ookla's HTTP 429 rate limit."""
    text = (message or "").lower()
    return "too many requests" in text or "429" in text


def find_binary():
    """Return the path of the ``speedtest`` binary, or ``None``."""
    return shutil.which("speedtest") or shutil.which("speedtest.exe")


_FLAVOUR_CACHE = {}


def detect_flavour():
    """Report what the ``speedtest`` on PATH actually is.

    Returns ``"ookla"``, ``"python-speedtest-cli"``, ``"unknown"`` or ``None``
    when no binary is present. The result is cached per binary path so a round
    does not spawn an extra process per test.
    """
    binary = find_binary()
    if binary is None:
        return None
    if binary in _FLAVOUR_CACHE:
        return _FLAVOUR_CACHE[binary]
    try:
        completed = subprocess.run(
            [binary, "--version"], capture_output=True, text=True, timeout=20
        )
    except (OSError, subprocess.SubprocessError):
        return None
    text = ((completed.stdout or "") + (completed.stderr or "")).lower()
    if "ookla" in text:
        flavour = "ookla"
    elif "speedtest-cli" in text or "matt martz" in text:
        flavour = "python-speedtest-cli"
    else:
        flavour = "unknown"
    _FLAVOUR_CACHE[binary] = flavour
    return flavour


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
        "--format=jsonl",
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

    elapsed = time.perf_counter() - started
    result, messages = parse_output(completed.stdout or "")
    if result is None:
        raise SpeedtestError(_failure_detail(completed, messages))

    stats = _stats_from_json(result, elapsed)
    stats["speed_messages"] = messages
    return stats


def parse_output(text):
    """Parse CLI output into ``(result_object, [log messages])``.

    The CLI emits newline-delimited JSON objects (``{"type":"log", ...}`` plus
    one ``{"type":"result", ...}``). Older builds emit a single JSON document,
    so fall back to parsing the whole output.
    """
    result = None
    messages = []
    for line in (text or "").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            item = json.loads(line)
        except ValueError:
            continue
        if not isinstance(item, dict):
            continue
        item_type = item.get("type")
        if item_type == "result":
            result = item
        elif item_type == "log":
            message = item.get("message")
            if message:
                messages.append(str(message))
        elif result is None and "download" in item:
            result = item
    if result is None:
        stripped = (text or "").strip()
        if stripped.startswith("{"):
            try:
                item = json.loads(stripped)
            except ValueError:
                item = None
            if isinstance(item, dict):
                return item, messages
    return result, messages


def _failure_detail(completed, messages):
    """Build a readable error message from a failed run."""
    lines = [line for line in (completed.stderr or "").splitlines() if line.strip()]
    detail = lines[-1].strip() if lines else ""
    if not detail and messages:
        detail = messages[-1]
    if not detail:
        detail = "no output"
    text = "speedtest exited with code {}: {}".format(completed.returncode, detail)
    if is_rate_limited(text):
        text += "  |  " + RATE_LIMIT_HINT
    return text


def _stats_from_json(data, elapsed):
    download = data.get("download") or {}
    upload = data.get("upload") or {}
    ping = data.get("ping") or {}
    server = data.get("server") or {}
    result = data.get("result") or {}
    interface = data.get("interface") or {}

    name = server.get("name") or "?"
    location = server.get("location") or ""
    label = "{} ({})".format(name, location) if location else name

    return {
        # Ookla reports bandwidth in bytes/second -> Mbit/s.
        "down_mbps": _to_mbps(download.get("bandwidth")),
        "up_mbps": _to_mbps(upload.get("bandwidth")),
        # Idle latency, and what the test measured while it was loading the link
        # (the "latency under load" figures - this is bufferbloat).
        "speed_latency_ms": ping.get("latency"),
        "speed_jitter_ms": ping.get("jitter"),
        "speed_latency_low_ms": ping.get("low"),
        "speed_latency_high_ms": ping.get("high"),
        "down_latency_ms": _latency(download, "iqm"),
        "down_latency_high_ms": _latency(download, "high"),
        "down_latency_jitter_ms": _latency(download, "jitter"),
        "up_latency_ms": _latency(upload, "iqm"),
        "up_latency_high_ms": _latency(upload, "high"),
        "up_latency_jitter_ms": _latency(upload, "jitter"),
        "speed_packet_loss": data.get("packetLoss"),
        "speed_server": label,
        "speed_server_id": server.get("id"),
        "speed_isp": data.get("isp") or "",
        "speed_iface": interface.get("name") or "",
        "speed_ip_internal": interface.get("internalIp") or "",
        "speed_ip_external": interface.get("externalIp") or "",
        "speed_vpn": interface.get("isVpn"),
        "speed_duration_s": round(elapsed, 1),
        "speed_result_url": result.get("url") or "",
        "error": None,
    }


def _latency(phase, key):
    """Read one latency value out of a download/upload block."""
    latency = phase.get("latency")
    if isinstance(latency, dict):
        return latency.get(key)
    return None


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


def config_dir():
    """Where the Ookla CLI keeps its config/licence files."""
    if os.name == "nt":
        base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
        return os.path.join(base, "Ookla", "Speedtest")
    return os.path.expanduser("~/.config/ookla")


def check():
    """Return a human-readable health report for the speedtest setup.

    Also runs a short command that initialises the licence/config files, so a
    ``ConfigurationError`` (non-writable config) shows up here.
    """
    binary = find_binary()
    if binary is None:
        return "speedtest : NOT FOUND on PATH. " + INSTALL_HINT

    flavour = detect_flavour()
    if flavour != "ookla":
        return ("speedtest : '{}' is {} - not the Ookla CLI. {}"
                .format(binary, flavour, INSTALL_HINT))

    directory = config_dir()
    if not os.path.isdir(directory):
        state = "missing (a successful run will create it)"
    elif os.access(directory, os.W_OK):
        state = "present and writable"
    else:
        state = "present but NOT writable - runs will fail with ConfigurationError"

    lines = [
        "speedtest : {} (Ookla CLI)".format(binary),
        "config    : {} - {}".format(directory, state),
    ]
    try:
        completed = subprocess.run(
            [binary, "--accept-license", "--accept-gdpr", "--format=jsonl", "--servers"],
            capture_output=True,
            text=True,
            timeout=60,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        lines.append("servers   : could not run: {}".format(exc))
        return "\n".join(lines)

    if completed.returncode == 0:
        lines.append("servers   : OK (licence accepted, server list retrieved)")
    else:
        detail = (completed.stderr or completed.stdout or "").strip().splitlines()
        lines.append("servers   : FAILED (exit {}) {}".format(
            completed.returncode, detail[-1] if detail else "no output"))
    return "\n".join(lines)


def config_writable():
    """``True``/``False`` if the config directory exists, ``None`` if not yet."""
    directory = config_dir()
    if not os.path.isdir(directory):
        return None
    return os.access(directory, os.W_OK)


def accept_licence(timeout=20.0):
    """Best effort: run the CLI once so the licence/GDPR files get written."""
    binary = find_binary()
    if binary is None or detect_flavour() != "ookla":
        return False
    try:
        completed = subprocess.run(
            [binary, "--accept-license", "--accept-gdpr", "--version"],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return completed.returncode == 0

