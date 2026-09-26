"""Command line entry point: ``python -m wifi_test {master|slave|selftest}``."""

from __future__ import annotations

import argparse

from .master import run_master
from .slave import run_slave


DEFAULT_PORT = 50607


def _add_measurement_options(parser):
    parser.add_argument(
        "--ping-target",
        default="1.1.1.1",
        help="host to ping for latency/jitter/loss (default: %(default)s)",
    )
    parser.add_argument(
        "--ping-count",
        type=int,
        default=10,
        help="number of pings per round (default: %(default)s)",
    )
    parser.add_argument(
        "--ping-timeout-ms",
        type=int,
        default=1000,
        help="per-ping timeout in ms (default: %(default)s)",
    )
    parser.add_argument(
        "--ping-method",
        choices=("icmp", "tcp"),
        default="icmp",
        help="latency probe type; use 'tcp' when ICMP is filtered (default: %(default)s)",
    )
    parser.add_argument(
        "--tcp-port",
        type=int,
        default=443,
        help="port used by --ping-method tcp (default: %(default)s)",
    )


def build_parser():
    parser = argparse.ArgumentParser(
        prog="python -m wifi_test",
        description="Distributed Wi-Fi diagnostics across several devices.",
    )
    subparsers = parser.add_subparsers(dest="mode", required=True)

    master = subparsers.add_parser(
        "master", help="coordinate test rounds and measure this device too"
    )
    master.add_argument("--bind", default="0.0.0.0", help="interface to listen on")
    master.add_argument("--port", type=int, default=DEFAULT_PORT, help="TCP port")
    master.add_argument(
        "--interval", type=float, default=60.0, help="seconds between rounds"
    )
    master.add_argument(
        "--duration",
        type=float,
        default=0.0,
        help="minutes to run; 0 means run until Ctrl+C",
    )
    master.add_argument(
        "--speed",
        action="store_true",
        help="run an Ookla speed test each round (about 30s per test)",
    )
    master.add_argument(
        "--speed-every",
        type=int,
        default=1,
        help="run the speedtest on every Nth round (default: %(default)s)",
    )
    master.add_argument(
        "--speed-stagger",
        type=float,
        default=15.0,
        help="seconds between each device's speed test within a round "
        "(default: %(default)s)",
    )
    master.add_argument(
        "--speed-timeout",
        type=float,
        default=180.0,
        help="seconds before a speed test is abandoned (default: %(default)s)",
    )
    master.add_argument(
        "--speed-server-id",
        type=int,
        default=None,
        help="pin a specific Ookla server id for comparable results "
        "(see --list-servers)",
    )
    master.add_argument(
        "--list-servers",
        action="store_true",
        help="print the Ookla server list for this machine and exit",
    )
    master.add_argument(
        "--round-timeout",
        type=float,
        default=120.0,
        help="seconds to wait for all devices in a round (default: %(default)s)",
    )
    master.add_argument(
        "--results", default="results.csv", help="results CSV path"
    )
    master.add_argument(
        "--graph", default="wifi_graphs.png", help="output graph image path"
    )
    master.add_argument(
        "--show", action="store_true", help="open a live graph window"
    )
    master.add_argument(
        "--no-graphs", action="store_true", help="do not create graphs at all"
    )
    master.add_argument(
        "--device", default=None, help="name shown for this device (default: hostname)"
    )
    master.add_argument(
        "--startup-delay",
        type=float,
        default=5.0,
        help="seconds to wait for slaves to connect before round 1 (default: %(default)s)",
    )
    _add_measurement_options(master)

    slave = subparsers.add_parser(
        "slave", help="connect to a master and run rounds on command"
    )
    slave.add_argument(
        "--master-ip",
        default=None,
        help="the master's local IP address (prompted for if omitted)",
    )
    slave.add_argument("--port", type=int, default=DEFAULT_PORT, help="master TCP port")
    slave.add_argument(
        "--device", default=None, help="name shown for this device (default: hostname)"
    )
    slave.add_argument(
        "--connect-timeout",
        type=float,
        default=10.0,
        help="seconds to wait when connecting (default: %(default)s)",
    )

    return parser


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.mode == "master":
        return run_master(args)
    if args.mode == "slave":
        return run_slave(args)
    parser.error(f"unknown mode: {args.mode}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
