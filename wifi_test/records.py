"""Turn raw measurement stats into rows for the results file and the graphs."""

from __future__ import annotations

import datetime
import time


CSV_FIELDS = [
    # identity
    "session",
    "round",
    "device",
    "role",
    "kind",
    "target",
    "target_kind",
    "ssid",
    "bssid",
    "rssi",
    "timestamp",
    "epoch",
    # latency / loss (ICMP, TCP connect or DNS resolution)
    "sent",
    "received",
    "loss_pct",
    "ping_min_ms",
    "ping_avg_ms",
    "ping_max_ms",
    "jitter_ms",
    # throughput
    "down_mbps",
    "up_mbps",
    # what the Ookla test itself measured
    "speed_latency_ms",
    "speed_jitter_ms",
    "speed_latency_low_ms",
    "speed_latency_high_ms",
    "down_latency_ms",
    "down_latency_high_ms",
    "down_latency_jitter_ms",
    "up_latency_ms",
    "up_latency_high_ms",
    "up_latency_jitter_ms",
    "speed_packet_loss",
    "speed_server",
    "speed_server_id",
    "speed_isp",
    "speed_iface",
    "speed_ip_internal",
    "speed_ip_external",
    "speed_vpn",
    "speed_duration_s",
    "speed_result_url",
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


def _base_row(session, round_no, device, role, kind, target, target_kind,
              context, timestamp, epoch):
    row = {field: "" for field in CSV_FIELDS}
    row["session"] = session
    row["round"] = round_no
    row["device"] = device
    row["role"] = role
    row["kind"] = kind
    row["target"] = target or ""
    row["target_kind"] = target_kind or ""
    context = context or {}
    row["ssid"] = context.get("ssid") or ""
    row["bssid"] = context.get("bssid") or ""
    row["rssi"] = context.get("rssi") or ""
    row["timestamp"] = timestamp
    row["epoch"] = _round(epoch)
    return row


def ping_row(session, round_no, device, role, stats, context=None,
             timestamp=None, epoch=None):
    """Build a result-file row describing one latency/loss measurement."""
    if timestamp is None or epoch is None:
        timestamp, epoch = now_stamp()
    row = _base_row(session, round_no, device, role, stats.get("kind", "ping"),
                    stats.get("target"), stats.get("target_kind"),
                    context, timestamp, epoch)
    row["sent"] = stats.get("sent", "")
    row["received"] = stats.get("received", "")
    row["loss_pct"] = _round(stats.get("loss_pct"))
    row["ping_min_ms"] = _round(stats.get("ping_min_ms"))
    row["ping_avg_ms"] = _round(stats.get("ping_avg_ms"))
    row["ping_max_ms"] = _round(stats.get("ping_max_ms"))
    row["jitter_ms"] = _round(stats.get("jitter_ms"))
    row["error"] = stats.get("error") or ""
    return row


def speed_row(session, round_no, device, role, stats, context=None,
              timestamp=None, epoch=None):
    """Build a result-file row describing one Ookla speed measurement."""
    if timestamp is None or epoch is None:
        timestamp, epoch = now_stamp()
    row = _base_row(session, round_no, device, role, "speed", "", "speed",
                    context, timestamp, epoch)
    row["down_mbps"] = _round(stats.get("down_mbps"))
    row["up_mbps"] = _round(stats.get("up_mbps"))
    row["speed_latency_ms"] = _round(stats.get("speed_latency_ms"))
    row["speed_jitter_ms"] = _round(stats.get("speed_jitter_ms"))
    row["speed_latency_low_ms"] = _round(stats.get("speed_latency_low_ms"))
    row["speed_latency_high_ms"] = _round(stats.get("speed_latency_high_ms"))
    row["down_latency_ms"] = _round(stats.get("down_latency_ms"))
    row["down_latency_high_ms"] = _round(stats.get("down_latency_high_ms"))
    row["down_latency_jitter_ms"] = _round(stats.get("down_latency_jitter_ms"))
    row["up_latency_ms"] = _round(stats.get("up_latency_ms"))
    row["up_latency_high_ms"] = _round(stats.get("up_latency_high_ms"))
    row["up_latency_jitter_ms"] = _round(stats.get("up_latency_jitter_ms"))
    row["speed_packet_loss"] = _round(stats.get("speed_packet_loss"))
    row["speed_server"] = stats.get("speed_server", "")
    row["speed_server_id"] = stats.get("speed_server_id", "")
    row["speed_isp"] = stats.get("speed_isp", "")
    row["speed_iface"] = stats.get("speed_iface", "")
    row["speed_ip_internal"] = stats.get("speed_ip_internal", "")
    row["speed_ip_external"] = stats.get("speed_ip_external", "")
    row["speed_vpn"] = stats.get("speed_vpn", "")
    row["speed_duration_s"] = _round(stats.get("speed_duration_s"), 1)
    row["speed_result_url"] = stats.get("speed_result_url", "")
    row["error"] = stats.get("error") or ""
    return row


def row_for(session, round_no, device, role, kind, stats, context=None,
            timestamp=None, epoch=None):
    """Build a row of the right type from a measurement's ``(kind, stats)``."""
    if kind == "speed":
        return speed_row(session, round_no, device, role, stats, context,
                         timestamp, epoch)
    return ping_row(session, round_no, device, role, stats, context,
                    timestamp, epoch)


def row_from_result(session, round_no, device, role, message):
    """Build a row from a slave's ``result`` message.

    The slave's own timestamp/epoch is kept so each device's rows are stamped
    by the clock of the device that made the measurement.
    """
    return row_for(
        session,
        round_no,
        device,
        role,
        message.get("kind"),
        message.get("stats") or {},
        message.get("context"),
        message.get("timestamp"),
        message.get("epoch"),
    )

