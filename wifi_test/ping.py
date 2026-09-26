"""Latency measurement helpers (ICMP via the system ping command, or TCP connect)."""

from __future__ import annotations

import platform
import re
import socket
import statistics
import subprocess
import time


_SYSTEM = platform.system().lower()
_IS_WINDOWS = _SYSTEM.startswith("win")
_IS_DARWIN = _SYSTEM == "darwin"

# Matches both "time=12ms"/"time=12.3 ms" and "time<1ms".
_TIME_RE = re.compile(r"time[=<]\s*([\d.]+)\s*ms", re.IGNORECASE)

_NOT_FOUND_MARKERS = (
    "could not find host",
    "unknown host",
    "name or service not known",
    "nodename nor servname",
    "no route to host",
)


def _ping_command(target: str, count: int, timeout_ms: int):
    if _IS_WINDOWS:
        # Windows: -n count, -w per-ping timeout in milliseconds.
        return ["ping", "-n", str(count), "-w", str(timeout_ms), target]
    if _IS_DARWIN:
        # macOS: -W is milliseconds, -t is an overall timeout in seconds.
        return ["ping", "-c", str(count), "-W", str(timeout_ms), target]
    # Linux: -W is seconds, optional -i interval.
    timeout_s = max(1, int(round(timeout_ms / 1000.0)))
    return ["ping", "-c", str(count), "-W", str(timeout_s), target]


def _parse_times(output: str):
    times = []
    for match in _TIME_RE.finditer(output):
        value = float(match.group(1))
        if match.group(0).lower().startswith("time<"):
            # "time<1ms" means "faster than 1 ms"; use half the resolution.
            value *= 0.5
        times.append(value)
    return times


def _stats(target: str, method: str, sent: int, times, error=None) -> dict:
    received = len(times)
    loss_pct = 0.0 if sent <= 0 else (sent - received) / float(sent) * 100.0
    if times:
        ping_min = min(times)
        ping_max = max(times)
        ping_avg = statistics.fmean(times)
        if received > 1:
            diffs = [abs(times[i] - times[i - 1]) for i in range(1, received)]
            jitter = statistics.fmean(diffs)
        else:
            jitter = 0.0
    else:
        ping_min = ping_max = ping_avg = jitter = None
    return {
        "method": method,
        "target": target,
        "sent": sent,
        "received": received,
        "loss_pct": loss_pct,
        "ping_min_ms": ping_min,
        "ping_avg_ms": ping_avg,
        "ping_max_ms": ping_max,
        "jitter_ms": jitter,
        "error": error,
    }


def ping_icmp(target: str, count: int = 10, timeout_ms: int = 1000) -> dict:
    """Ping *target* *count* times using the OS ``ping`` command."""
    command = _ping_command(target, count, timeout_ms)
    subprocess_timeout = count * (timeout_ms / 1000.0) + 15.0
    try:
        completed = subprocess.run(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=subprocess_timeout,
        )
    except subprocess.TimeoutExpired:
        return _stats(target, "icmp", count, [], "ping command timed out")
    except OSError as exc:
        return _stats(target, "icmp", count, [], f"ping command failed: {exc}")

    output = (completed.stdout or "") + (completed.stderr or "")
    lowered = output.lower()
    error = None
    for marker in _NOT_FOUND_MARKERS:
        if marker in lowered:
            error = f"target unreachable: {marker}"
            break
    times = _parse_times(output)
    return _stats(target, "icmp", count, times, error)


def ping_tcp(target: str, port: int = 443, count: int = 10, timeout_ms: int = 1000) -> dict:
    """Measure TCP-connect latency, useful when ICMP is filtered."""
    timeout_s = timeout_ms / 1000.0
    times = []
    for _ in range(count):
        start = time.perf_counter()
        try:
            with socket.create_connection((target, port), timeout=timeout_s):
                times.append((time.perf_counter() - start) * 1000.0)
        except OSError:
            pass
        time.sleep(0.05)
    return _stats(target, "tcp", count, times)
