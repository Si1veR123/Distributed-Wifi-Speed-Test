"""Slave role: connect to a master and run the rounds it asks for."""

from __future__ import annotations

import socket
import time

from . import protocol
from . import records
from . import speed as speed_module
from .master import measure_once


RECONNECT_DELAY = 3.0


def _send_stats(sock, round_no, device, kind, stats):
    stamp, epoch = records.now_stamp()
    protocol.send_message(
        sock,
        {
            "type": protocol.MSG_RESULT,
            "round": round_no,
            "device": device,
            "kind": kind,
            "timestamp": stamp,
            "epoch": epoch,
            "stats": stats,
        },
    )


def _run_round(sock, round_no, device, params):
    delay = float(params.get("speed_delay") or 0.0)
    print(f"[slave] round {round_no} starting ...")
    ping_stats, speed_stats = measure_once(params)
    _send_stats(sock, round_no, device, "ping", ping_stats)
    if ping_stats.get("ping_avg_ms") is not None:
        print(
            "[slave] ping {:6.1f} ms  loss {:5.1f}%".format(
                ping_stats["ping_avg_ms"], ping_stats.get("loss_pct") or 0.0
            )
        )
    else:
        print(f"[slave] ping failed: {ping_stats.get('error') or 'no replies'}")

    if speed_stats is not None:
        _send_stats(sock, round_no, device, "speed", speed_stats)
        if speed_stats.get("error"):
            print(f"[slave] speed failed: {speed_stats['error']}")
        else:
            print(
                "[slave] down {:6.1f} / up {:6.1f} Mbit/s  [{}]{}".format(
                    speed_stats.get("down_mbps") or 0.0,
                    speed_stats.get("up_mbps") or 0.0,
                    speed_stats.get("speed_server", "?"),
                    "" if delay <= 0 else f" delay {delay:g}s",
                )
            )
    protocol.send_message(
        sock, {"type": protocol.MSG_ROUND_DONE, "round": round_no, "device": device}
    )


def _session(sock, device):
    protocol.send_message(
        sock,
        {
            "type": protocol.MSG_HELLO,
            "device": device,
            "speedtest": speed_module.can_run(),
        },
    )
    reader = protocol.LineReader(sock)
    while True:
        message = reader.read_message()
        if message is None:
            print("[slave] master closed the connection")
            return False
        kind = message.get("type")
        if kind == protocol.MSG_RUN:
            params = message.get("params") or {}
            _run_round(sock, message.get("round"), device, params)
        elif kind == protocol.MSG_SHUTDOWN:
            print("[slave] master asked us to stop")
            return True
    return False


def run_slave(args):
    """Entry point for ``python -m wifi_test slave``."""
    master_ip = args.master_ip
    if not master_ip:
        master_ip = input("Master IP address: ").strip()
    if not master_ip:
        raise SystemExit("a master IP address is required")

    device = args.device or socket.gethostname()
    print("=" * 72)
    print("Distributed Wi-Fi diagnostics - SLAVE")
    print(f"  device name : {device}")
    print(f"  master      : {master_ip}:{args.port}")
    flavour = speed_module.detect_flavour()
    if flavour == "ookla":
        print(f"  speedtest   : Ookla CLI at {speed_module.find_binary()}")
    elif flavour is None:
        print("  speedtest   : NOT FOUND on PATH (speed tests will be skipped)")
    else:
        print(f"  speedtest   : '{speed_module.find_binary()}' is {flavour}, not the "
              "Ookla CLI (speed tests will be skipped)")
    print("  Press Ctrl+C to stop.")
    print("=" * 72)

    try:
        while True:
            try:
                sock = socket.create_connection(
                    (master_ip, args.port), timeout=args.connect_timeout
                )
            except OSError as exc:
                print(f"[slave] cannot reach master ({exc}); retrying in "
                      f"{RECONNECT_DELAY:g}s")
                time.sleep(RECONNECT_DELAY)
                continue

            print(f"[slave] connected to {master_ip}:{args.port}")
            # The connect timeout must not leak into the blocking reads that
            # wait for the next round, otherwise idle periods look like a
            # closed connection and the slave reconnects every round.
            sock.settimeout(None)
            stopped_by_master = False
            try:
                stopped_by_master = _session(sock, device)
            except OSError as exc:
                print(f"[slave] connection lost ({exc})")
            finally:
                try:
                    sock.close()
                except OSError:
                    pass
            if stopped_by_master:
                break
            print(f"[slave] reconnecting in {RECONNECT_DELAY:g}s")
            time.sleep(RECONNECT_DELAY)
    except KeyboardInterrupt:
        print("\n[slave] interrupted by user")
    return 0
