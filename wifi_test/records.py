"""Turn raw measurement stats into rows for the results file and the graphs."""

from __future__ import annotations

import datetime
import time


CSV_FIELDS = [
    "timestamp",
    "epoch",
    "round",
    "device",
    "role",
    "kind",
    "target",
    "sent",
    "received",
    "loss_pct",
    "ping_min_ms",
    "ping_avg_ms",
    "ping_max_ms",
    "jitter_ms",
    "down_mbps",
    "up_mbps",
    "speed_server",
    "speed_latency_ms",
    "error",
]


def now_stamp():
    """Return ``(iso_timestamp, epoch_seconds)`` for the current moment."""
    epoch = time.time()
    stamp = datetime.datetime.fromtimestamp(epoch).isoformat(timespec="seconds")
    return stamp, epoch


def _round(value, digits: int = 3):
    if value is None or value == "":
        return ""
    try:
        return round(float(value), digits)
    except (TypeError, ValueError):
        return ""


def _base_row(round_no, device, role, kind, timestamp, epoch):
    row = {field: "" for field in CSV_FIELDS}
    row["timestamp"] = timestamp
    row["epoch"] = _round(epoch)
    row["round"] = round_no
    row["device"] = device
    row["role"] = role
    row["kind"] = kind
    return row


def ping_row(round_no, device, role, stats, timestamp=None, epoch=None):
    """Build a result-file row describing one ping measurement."""
    if timestamp is None or epoch is None:
        timestamp, epoch = now_stamp()
    row = _base_row(round_no, device, role, "ping", timestamp, epoch)
    row["target"] = stats.get("target", "")
    row["sent"] = stats.get("sent", "")
    row["received"] = stats.get("received", "")
    row["loss_pct"] = _round(stats.get("loss_pct"))
    row["ping_min_ms"] = _round(stats.get("ping_min_ms"))
    row["ping_avg_ms"] = _round(stats.get("ping_avg_ms"))
    row["ping_max_ms"] = _round(stats.get("ping_max_ms"))
    row["jitter_ms"] = _round(stats.get("jitter_ms"))
    row["error"] = stats.get("error") or ""
    return row


def speed_row(round_no, device, role, stats, timestamp=None, epoch=None):
    """Build a result-file row describing one speed measurement."""
    if timestamp is None or epoch is None:
        timestamp, epoch = now_stamp()
    row = _base_row(round_no, device, role, "speed", timestamp, epoch)
    row["down_mbps"] = _round(stats.get("down_mbps"))
    row["up_mbps"] = _round(stats.get("up_mbps"))
    row["speed_server"] = stats.get("speed_server", "")
    row["speed_latency_ms"] = _round(stats.get("speed_latency_ms"))
    row["error"] = stats.get("error") or ""
    return row


def row_from_result(round_no, device, role, kind, stats, timestamp=None, epoch=None):
    """Build a row from a slave's ``result`` message."""
    if timestamp is None or epoch is None:
        timestamp, epoch = now_stamp()
    if kind == "speed":
        return speed_row(round_no, device, role, stats, timestamp, epoch)
    return ping_row(round_no, device, role, stats, timestamp, epoch)
