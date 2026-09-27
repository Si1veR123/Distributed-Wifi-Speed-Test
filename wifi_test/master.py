"""Master role: schedule rounds, measure locally and collect slave results."""

from __future__ import annotations

import csv
import os
import queue
import socket
import threading
import time

from . import measure as measure_module
from . import protocol
from . import records
from . import speed as speed_module
from . import targets as targets_module


class ResultsStore:
    """Appends rows to the results file so partial data survives a crash."""

    def __init__(self, path):
        self.path = path
        self._lock = threading.Lock()
        self._row_count = 0
        self._ensure_header()

    def _ensure_header(self):
        directory = os.path.dirname(os.path.abspath(self.path))
        if directory:
            os.makedirs(directory, exist_ok=True)
        if os.path.exists(self.path) and os.path.getsize(self.path) > 0:
            return
        with open(self.path, "w", newline="", encoding="utf-8") as handle:
            csv.DictWriter(handle, fieldnames=records.CSV_FIELDS).writeheader()

    def append(self, row):
        with self._lock:
            with open(self.path, "a", newline="", encoding="utf-8") as handle:
                writer = csv.DictWriter(
                    handle, fieldnames=records.CSV_FIELDS, extrasaction="ignore"
                )
                writer.writerow(row)
            self._row_count += 1

    @property
    def row_count(self):
        return self._row_count


class _Client:
    def __init__(self, sock, address):
        self.sock = sock
        self.address = address
        self.device = None
        self.speed_available = None


class MasterServer:
    """TCP server that slaves connect to; results arrive on an internal queue."""

    def __init__(self, host, port):
        self.host = host
        self.port = port
        self._server = None
        self._clients = {}
        self._clients_lock = threading.Lock()
        self._queue = queue.Queue()
        self._stop = threading.Event()

    def start(self):
        self._server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._server.bind((self.host, self.port))
        self._server.listen(16)
        threading.Thread(target=self._accept_loop, daemon=True).start()

    @property
    def bound_port(self):
        if self._server is None:
            return self.port
        return self._server.getsockname()[1]

    def _accept_loop(self):
        while not self._stop.is_set():
            try:
                sock, address = self._server.accept()
            except OSError:
                break
            threading.Thread(
                target=self._client_loop, args=(_Client(sock, address),), daemon=True
            ).start()

    def _client_loop(self, client):
        try:
            reader = protocol.LineReader(client.sock)
            while not self._stop.is_set():
                message = reader.read_message()
                if message is None:
                    break
                kind = message.get("type")
                if kind == protocol.MSG_HELLO:
                    client.device = message.get("device") or client.address[0]
                    client.speed_available = message.get("speedtest")
                    with self._clients_lock:
                        self._clients[client.device] = client
                    note = ""
                    if client.speed_available is False:
                        note = "  [no Ookla speedtest - speed tests skipped]"
                    print(f"[master] slave connected: {client.device} "
                          f"({client.address[0]}){note}")
                elif kind == protocol.MSG_RESULT:
                    self._queue.put(("result", client.device, message))
                elif kind == protocol.MSG_ROUND_DONE:
                    self._queue.put(("done", client.device, message.get("round")))
        except OSError:
            pass
        finally:
            try:
                client.sock.close()
            except OSError:
                pass
            if client.device:
                with self._clients_lock:
                    if self._clients.get(client.device) is client:
                        del self._clients[client.device]
                # Let an in-progress round stop waiting for this device.
                self._queue.put(("disconnect", client.device, None))
                print(f"[master] slave disconnected: {client.device}")

    def connected_devices(self):
        with self._clients_lock:
            return list(self._clients.keys())

    def clients_snapshot(self):
        """Return ``{device: speed_available}`` for the connected slaves."""
        with self._clients_lock:
            return {name: client.speed_available for name, client in self._clients.items()}

    def send_to(self, device, message):
        with self._clients_lock:
            client = self._clients.get(device)
        if client is None:
            return False
        try:
            protocol.send_message(client.sock, message)
            return True
        except OSError:
            return False

    def broadcast(self, message):
        with self._clients_lock:
            clients = list(self._clients.values())
        for client in clients:
            try:
                protocol.send_message(client.sock, message)
            except OSError:
                pass

    def submit(self, event, device, payload):
        self._queue.put((event, device, payload))

    def wait_for(self, devices, deadline, on_result):
        """Wait for every device in *devices* to finish, until the deadline.

        Returns the set of devices that never reported.  A slave that drops
        out mid-round is removed immediately so the round does not stall for
        the full round timeout.
        """
        remaining = set(devices)
        while remaining and time.time() < deadline and not self._stop.is_set():
            wait = min(0.5, max(0.05, deadline - time.time()))
            try:
                event, device, payload = self._queue.get(timeout=wait)
            except queue.Empty:
                continue
            if event == "done":
                remaining.discard(device)
            elif event == "disconnect":
                if device in remaining:
                    remaining.discard(device)
                    print(f"[master] {device} disconnected mid-round; "
                          "not waiting for it")
            else:
                on_result(device, payload)
        return remaining

    def stop(self):
        self._stop.set()
        if self._server is not None:
            try:
                self._server.close()
            except OSError:
                pass
        with self._clients_lock:
            for client in self._clients.values():
                try:
                    protocol.send_message(client.sock, {"type": protocol.MSG_SHUTDOWN})
                except OSError:
                    pass
                try:
                    client.sock.close()
                except OSError:
                    pass


def format_measurement(device, round_no, kind, stats):
    """Format a single measurement as one console line."""
    if kind == "speed":
        label = "speed"
        detail = measure_module.describe_speed(stats)
    else:
        label = "{} {}".format(stats.get("target_kind") or kind,
                               stats.get("target") or "")
        detail = measure_module.describe_latency(stats)
    return "[round {:>3}] {:>16}  {:<26} {}".format(
        round_no, device, label.strip()[:26], detail
    )


def resolve_paths(args, session):
    """Return ``(results_path, graph_path)`` for this session.

    Every run gets its own pair of files, so round numbers can never collide
    with an earlier run that was appended to the same file.
    """
    if args.results:
        graph = args.graph or os.path.splitext(args.results)[0] + ".png"
        return args.results, graph
    return (os.path.join(args.results_dir, "session-{}.csv".format(session)),
            os.path.join(args.results_dir, "session-{}.png".format(session)))


def build_params(args, ping_targets, tcp_probe_target):
    """Assemble the per-round settings that are handed to every device."""
    return {
        "ping_targets": [{"host": host, "kind": kind} for host, kind in ping_targets],
        "ping_count": args.ping_count,
        "ping_timeout_ms": args.ping_timeout_ms,
        "ping_interval_ms": int(round(args.ping_interval * 1000)),
        "ping_method": args.ping_method,
        "tcp_port": args.tcp_port,
        "dns_enabled": not args.no_dns,
        "dns_count": args.dns_count,
        "dns_timeout_s": args.dns_timeout,
        "tcp_enabled": not args.no_tcp,
        "tcp_probe_target": tcp_probe_target,
        "tcp_count": args.tcp_count,
        "speed": args.speed,
        "speed_timeout": args.speed_timeout,
        "speed_server_id": args.speed_server_id,
    }



def run_master(args):
    """Entry point for ``python -m wifi_test master``."""
    if getattr(args, "list_servers", False):
        print(speed_module.list_servers())
        return 0

    master_can_speed = speed_module.can_run()
    session = time.strftime("%Y%m%d-%H%M%S")
    results_path, graph_path = resolve_paths(args, session)
    server = MasterServer(args.bind, args.port)
    server.start()
    store = ResultsStore(results_path)

    plotter = None
    if not args.no_graphs:
        try:
            from .liveplot import LivePlotter

            plotter = LivePlotter(graph_path, show=args.show)
        except Exception as exc:
            print(f"[master] graphs disabled ({exc}); results are still recorded")

    ping_targets = (targets_module.parse_targets(args.ping_targets)
                    or targets_module.default_ping_targets())
    tcp_probe_target = (args.tcp_probe
                        or next((host for host, kind in ping_targets if kind == "wan"),
                                "1.1.1.1"))
    params = build_params(args, ping_targets, tcp_probe_target)

    local_name = args.device or socket.gethostname()
    print("=" * 72)
    print("Distributed Wi-Fi diagnostics - MASTER")
    print(f"  session          : {session}")
    print(f"  listening on     : {args.bind}:{server.bound_port}")
    print(f"  local device name: {local_name}")
    duration_text = "unlimited" if not args.duration else f"{args.duration:g} min"
    print(f"  interval         : {args.interval:g}s   duration: {duration_text}")
    print("  ping targets     : " + ", ".join(
        f"{host} [{kind}]" for host, kind in ping_targets))
    print(f"  probes           : {args.ping_count} per target, {args.ping_method}, "
          f"interval {args.ping_interval:g}s")
    if not args.no_dns:
        print(f"  dns probe        : {args.dns_count} fresh names per round "
              f"(timeout {args.dns_timeout:g}s)")
    if not args.no_tcp:
        print(f"  tcp connect probe: {tcp_probe_target}:{args.tcp_port} "
              f"x{args.tcp_count}")
    if args.speed:
        if not master_can_speed:
            print("  speedtest binary : WARNING - Ookla 'speedtest' not found on this "
                  "master's PATH")
        else:
            print(f"  speedtest binary : {speed_module.find_binary()}")
        print(f"  speed stagger    : {args.speed_stagger:g}s per device")
    print(f"  results file     : {os.path.abspath(results_path)}")
    if plotter is not None:
        print(f"  graph file       : {os.path.abspath(graph_path)}")
    print("  round estimate   : up to %gs with 4 devices (keep --interval above this)"
          % round_budget(args, 4, args.speed, len(ping_targets)))
    print("  Run slaves with:  python -m wifi_test slave --master-ip <this-ip>")
    print("  Press Ctrl+C to stop.")
    print("=" * 72)

    # (the per-round settings were built above as ``params``)

    history = {}
    stop_at = time.time() + args.duration * 60 if args.duration else None

    if args.startup_delay > 0:
        print(f"[master] waiting {args.startup_delay:g}s for slaves to connect ...")
        time.sleep(args.startup_delay)
        print(f"[master] {len(server.connected_devices())} slave(s) connected")

    round_no = 0
    next_round_at = time.time()

    try:
        while True:
            now = time.time()
            if stop_at is not None and now >= stop_at:
                break
            if now < next_round_at:
                time.sleep(min(1.0, next_round_at - now))
                continue

            round_no += 1
            round_start = time.time()
            next_round_at = round_start + args.interval
            run_round(server, store, history, plotter, params, session,
                      local_name, round_no, args)
    except KeyboardInterrupt:
        print("\n[master] interrupted by user")
    finally:
        server.stop()
        if plotter is not None:
            plotter.close()
        print(f"[master] results written to {os.path.abspath(results_path)}")
    return 0



def device_budget(args, target_count):
    """Worst-case seconds one device needs to finish its own measurements."""
    probe_span = max(1, target_count) * args.ping_count * max(1.0, args.ping_interval)
    budget = probe_span + 10.0
    if not args.no_dns:
        budget += args.dns_count * args.dns_timeout + 2.0
    if not args.no_tcp:
        budget += args.tcp_count * (args.ping_timeout_ms / 1000.0 + 0.1) + 2.0
    return budget


def round_budget(args, device_count, speed_enabled, target_count):
    """Longest a round may take, allowing for the staggered speed tests."""
    budget = device_budget(args, target_count)
    if speed_enabled:
        budget += args.speed_timeout
        budget += max(0, device_count - 1) * args.speed_stagger
    return max(args.round_timeout, budget)


def run_round(server, store, history, plotter, params, session, local_name,
              round_no, args):
    """Command one round, measure locally, collect the results, refresh the graph."""
    round_params = measure_module.for_round(params, round_no)
    round_params["speed"] = args.speed and (
        args.speed_every <= 1 or round_no % args.speed_every == 1
    )
    capabilities = server.clients_snapshot()
    slaves = sorted(capabilities)
    devices = sorted(set(slaves) | {local_name})
    # Deterministic stagger slots so the speed tests do not overlap.
    slots = {name: index for index, name in enumerate(devices)}

    print(f"\n[master] round {round_no} starting ({len(slaves)} slave(s) connected)")
    no_speed = []
    for name in slaves:
        device_params = dict(round_params)
        if capabilities.get(name) is False:
            device_params["speed"] = False
            no_speed.append(name)
        device_params["speed_delay"] = slots[name] * args.speed_stagger
        if not server.send_to(
            name, {"type": protocol.MSG_RUN, "round": round_no, "params": device_params}
        ):
            print(f"[master] could not send the round to {name}")
    if no_speed:
        print("[master] speed tests skipped for {} (no Ookla speedtest on PATH)".format(
            ", ".join(no_speed)
        ))

    def record(device, message):
        row = records.row_from_result(
            session, message.get("round") or round_no, device, "slave", message
        )
        history.setdefault(device, []).append(row)
        store.append(row)
        print(format_measurement(device, row["round"], row["kind"],
                                 message.get("stats") or {}))

    local_params = dict(round_params)
    local_params["speed_delay"] = slots[local_name] * args.speed_stagger

    def measure_local():
        for kind, stats, context in measure_module.iter_measurements(local_params):
            stamp, epoch = records.now_stamp()
            row = records.row_for(session, round_no, local_name, "master", kind,
                                  stats, context, stamp, epoch)
            history.setdefault(local_name, []).append(row)
            store.append(row)
            print(format_measurement(local_name, round_no, kind, stats))
        server.submit("done", local_name, round_no)

    threading.Thread(target=measure_local, daemon=True).start()
    deadline = time.time() + round_budget(
        args, len(devices), round_params["speed"],
        len(round_params.get("ping_targets") or []),
    )
    missing = server.wait_for(set(devices), deadline, record)
    if missing:
        print(f"[master] round {round_no}: no reply from {', '.join(sorted(missing))}")
    if plotter is not None:
        plotter.update(history)
    print(f"[master] round {round_no} complete "
          f"({store.row_count} rows in {os.path.basename(store.path)})")

