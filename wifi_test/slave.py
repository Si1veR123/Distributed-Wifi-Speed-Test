"""Slave role: connect to a master and run the rounds it asks for."""

from __future__ import annotations

import socket
import time

from . import measure as measure_module
from . import protocol
from . import records
from . import speed as speed_module


RECONNECT_DELAY = 3.0


def _send_result(sock, round_no, device, kind, stats, context):
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
            "context": context,
            "stats": stats,
        },
    )


def _run_round(sock, round_no, device, params):
    delay = float(params.get("speed_delay") or 0.0)
    print(f"[slave] round {round_no} starting ...")
    for kind, stats, context in measure_module.iter_measurements(params):
        _send_result(sock, round_no, device, kind, stats, context)
        if kind == "speed":
            suffix = "" if delay <= 0 else "  (delayed {:.0f}s)".format(delay)
            print("[slave] speed    {} {}".format(
                measure_module.describe_speed(stats), suffix))
        else:
            print("[slave] {:<8} {:<16} {}".format(
                stats.get("target_kind") or kind,
                stats.get("target") or "",
                measure_module.describe_latency(stats)))
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
        state = speed_module.config_writable()
        if state is False:
            note = "  [config NOT writable - runs may fail with ConfigurationError]"
        elif state is None:
            note = "  [config not created yet]"
        else:
            note = ""
        print(f"  speedtest   : Ookla CLI at {speed_module.find_binary()}{note}")
        speed_module.accept_licence()
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
