"""Shared measurement engine used by both the master and the slaves.

A round is made of: one latency/loss probe per ping target (gateway, DNS
server, WAN), a DNS-resolution probe, an optional TCP-connect probe, and
finally the Ookla speed test - which also reports idle latency, latency under
load (bufferbloat) and packet loss of its own.
"""

from __future__ import annotations

import time

from . import ping as ping_module
from . import speed as speed_module
from . import targets as targets_module


# Rotated through so a round never measures a name the OS has already cached.
DNS_NAME_POOL = (
    "www.google.com",
    "github.com",
    "www.microsoft.com",
    "www.cloudflare.com",
    "www.amazon.co.uk",
    "www.bbc.co.uk",
    "www.wikipedia.org",
    "duckduckgo.com",
    "cdn.jsdelivr.net",
    "pypi.org",
    "www.apple.com",
    "www.spotify.com",
    "www.reddit.com",
    "www.ebay.co.uk",
    "www.raspberrypi.com",
    "api.github.com",
)


def dns_names_for_round(round_no, count=3):
    """Pick a rotating set of hostnames for round *round_no*."""
    count = max(1, min(count, len(DNS_NAME_POOL)))
    start = (max(1, round_no) - 1) * count
    return [DNS_NAME_POOL[(start + index) % len(DNS_NAME_POOL)]
            for index in range(count)]


def for_round(params, round_no):
    """Return a copy of *params* with the per-round DNS names filled in."""
    params = dict(params)
    params["dns_names"] = dns_names_for_round(round_no, params.get("dns_count", 3))
    return params


def measure_pings(params):
    """Yield one stats dict per configured ping target."""
    count = int(params.get("ping_count", 10))
    timeout_ms = int(params.get("ping_timeout_ms", 1000))
    interval_ms = params.get("ping_interval_ms")
    port = int(params.get("tcp_port", 443))
    use_tcp = params.get("ping_method") == "tcp"
    for target in params.get("ping_targets") or []:
        host = target.get("host")
        kind = target.get("kind") or "wan"
        if not host:
            continue
        # The gateway and DNS server are on the LAN, where ICMP is normally
        # allowed; --ping-method tcp is aimed at the WAN targets.
        if use_tcp and kind == "wan":
            yield ping_module.ping_tcp(host, port, count=count,
                                       timeout_ms=timeout_ms, target_kind=kind)
        else:
            yield ping_module.ping_icmp(host, count=count, timeout_ms=timeout_ms,
                                        interval_ms=interval_ms, target_kind=kind)


def measure_extras(params):
    """Yield the DNS-resolution and TCP-connect probes."""
    if params.get("dns_enabled") and params.get("dns_names"):
        yield ping_module.dns_stats(
            params["dns_names"],
            timeout_s=float(params.get("dns_timeout_s") or 5.0),
        )
    if params.get("tcp_enabled") and params.get("tcp_probe_target"):
        yield ping_module.ping_tcp(
            params["tcp_probe_target"],
            int(params.get("tcp_port", 443)),
            count=int(params.get("tcp_count", 5)),
            timeout_ms=int(params.get("ping_timeout_ms", 1000)),
            target_kind="tcp",
        )


def iter_measurements(params):
    """Yield ``(kind, stats, context)`` for one round, in measurement order.

    Yielding lets the caller forward each measurement immediately, so a ping
    result is not held up by the slow speed test that runs at the end.
    """
    context = targets_module.wifi_context()
    for stats in measure_pings(params):
        yield "ping", stats, context
    for stats in measure_extras(params):
        yield stats.get("kind") or "ping", stats, context
    if params.get("speed"):
        delay = float(params.get("speed_delay") or 0.0)
        if delay > 0:
            time.sleep(delay)
        try:
            speed_stats = speed_module.run_speedtest(
                server_id=params.get("speed_server_id"),
                timeout=float(params.get("speed_timeout") or 180.0),
            )
        except Exception as exc:
            speed_stats = {"error": str(exc)}
        yield "speed", speed_stats, context


def describe_latency(stats):
    """One-line summary of a latency/loss measurement."""
    if stats.get("ping_avg_ms") is None:
        return "no replies ({})".format(stats.get("error") or "target unreachable")
    text = "avg {:6.1f}  max {:6.1f}  jitter {:5.1f} ms  loss {:5.1f}%".format(
        stats.get("ping_avg_ms") or 0.0,
        stats.get("ping_max_ms") or 0.0,
        stats.get("jitter_ms") or 0.0,
        stats.get("loss_pct") or 0.0,
    )
    if stats.get("error"):
        text += "  [{}]".format(stats["error"])
    return text


def describe_speed(stats):
    """One-line summary of an Ookla measurement."""
    if stats.get("error"):
        return "ERROR {}".format(stats["error"])
    text = "down {:7.1f} / up {:7.1f} Mbit/s  [{}]".format(
        stats.get("down_mbps") or 0.0,
        stats.get("up_mbps") or 0.0,
        stats.get("speed_server") or "?",
    )
    if stats.get("speed_latency_ms") is not None:
        text += "  idle {:5.1f} ms".format(stats["speed_latency_ms"])
    for label, key in (("load-down", "down_latency_ms"), ("load-up", "up_latency_ms")):
        if stats.get(key) is not None:
            text += "  {} {:5.1f} ms".format(label, stats[key])
    if stats.get("speed_packet_loss") is not None:
        text += "  loss {}%".format(stats["speed_packet_loss"])
    return text
