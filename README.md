# Distributed Wi-Fi diagnostics

Measures **latency, jitter and packet loss** (to the gateway, your DNS server and
the internet), **DNS resolution time**, **TCP connection setup** and **internet
speed** (including latency under load) on several devices *at the same time*, so
you can see whether a bad period affects every device, only the wireless ones,
or is upstream of your router. One device is the **master**; the others run as
**slaves** and report back over TCP on the local network.

## Requirements

* **Python 3.8+** on every device.
* **Ookla Speedtest CLI** (`speedtest`) on `PATH` on every device that runs
  speed tests. Download: https://www.speedtest.net/apps/cli
* **matplotlib** on the **master only**, for the graphs:
  `python -m pip install -r requirements.txt` (or `sudo apt install python3-matplotlib`).

Verify the Ookla CLI:

```
speedtest --version        # must print "Speedtest by Ookla"
speedtest --accept-license --accept-gdpr   # accept the licence once
```

> The Debian/Raspberry Pi package `speedtest-cli` installs a *different* Python
> program that is **also** called `speedtest`. This tool detects that and refuses
> to use it, because its numbers and server selection are unreliable. Install the
> real Ookla CLI from https://www.speedtest.net/apps/cli

## Check the setup

On every device:

```
python -m wifi_test check
```

It reports which `speedtest` binary is in use, whether the Ookla config
directory is writable (a `ConfigurationError` means it is not) and initialises
the licence/GDPR files. Every speed test also passes `--accept-license
--accept-gdpr`, so nothing is ever prompted for at run time.

## Run the master

On the always-on device (the one that will collect results and draw graphs):

```
python -m wifi_test master --interval 60 --speed
```

* `--interval 60`   start a measurement round every 60 seconds.
* `--speed`         also run an Ookla speed test each round (~30 s). Without it
                    only latency/loss is measured, which is much faster.
* `--ping-targets "192.168.0.1:gateway,1.1.1.1:wan"`  override the probe targets
                    (default: the default gateway, your DNS server, 1.1.1.1 and
                    8.8.8.8).
* `--ping-count 10`, `--ping-interval 1`, `--ping-timeout-ms 1000`  latency probes.
* `--no-dns`        skip the DNS-resolution probe.
* `--dns-count 3`, `--dns-timeout 5`  fresh hostnames resolved per round, and the
                    time allowed for each lookup.
* `--no-tcp`        skip the TCP-connect probe.
* `--tcp-probe 1.1.1.1`, `--tcp-count 5`, `--tcp-port 443`  TCP-connect probe.
* `--ping-method tcp`  probe the WAN targets with TCP connects instead of ICMP.
* `--speed-stagger 15`  start each device's speed test this many seconds after
                    the previous one, so tests don't share the link or corrupt
                    server selection.
* `--speed-server-id 12345`  pin one server for comparable results (find an id
                    with `--list-servers`).
* `--speed-timeout 180`  seconds before a speed test is abandoned.
* `--speed-devices 1`  how many devices run a speed test per round. Tests are
                    **rotated** between devices, because every device behind the
                    router shares one rate limit for your public IP.
* `--speed-cooldown 30`  minutes to pause speed tests after Ookla answers HTTP
                    429 ("Too many requests received"); tests resume by
                    themselves afterwards.
* `--speed-every 5`  only run the speed test every Nth round.
* `--duration 30`   stop automatically after 30 minutes (0 = run until Ctrl+C).
* `--results-dir results`  where the per-session files are written.
* `--results out.csv` / `--graph out.png`  explicit paths instead of the
                    session-stamped defaults.
* `--show`          also open a live graph window.
* `--no-graphs`     skip graphs entirely.
* `--graph-columns 3`  how many columns of panels the graph uses (0 = automatic:
                    3 columns for the 12 panels, i.e. a 1680x1080 image). Use 2
                    for a taller/narrower sheet or 4 for a wide one.
* `--list-servers`  print the Ookla server list for this machine and exit.

The master prints its session id, listening address, every probe target and the
worst-case round length on startup.

## Run the slaves

On every other device:

```
python -m wifi_test slave --master-ip 192.168.1.23
```

If you omit `--master-ip`, you will be prompted to type the master's IP address.
The slave reconnects automatically if the master restarts, and stops when the
master is stopped.

Use `--device <name>` to control the label shown in the results/graphs
(defaults to the hostname).

## What is measured each round

| probe | what it tells you |
|-------|-------------------|
| ICMP ping to the **gateway** | is the local hop / booster healthy? |
| ICMP ping to your **DNS server**, **1.1.1.1**, **8.8.8.8** | is the router / WAN healthy? |
| **DNS resolution** of fresh hostnames | "apps take ages to load while speed looks fine" |
| **TCP connect** to a WAN host:443 | connection setup (resolver + SYN + handshake) |
| **Ookla speed test** | download/upload, idle latency, **latency under load** (bufferbloat), packet loss |
| Wi-Fi context | SSID / BSSID / signal recorded with every row |

Each probe is written as its own row, so a spike can be attributed to the
gateway, the resolver or the WAN — and the per-round SSID/BSSID shows which
access point the device was actually attached to.

## Output

Every run writes its own pair of files, so round numbers can never collide with
an earlier run:

```
results/session-20260927-024052.csv    # the data
results/session-20260927-024052.png    # the graph
```

`results.csv`-style long-format, one row per measurement:

| column | meaning |
|--------|---------|
| `session`, `round` | run id and round number |
| `device`, `role` | device label and `master`/`slave` |
| `kind` | `ping`, `dns` or `speed` |
| `target`, `target_kind` | probed host and `gateway`/`dns`/`wan`/`tcp`/`speed` |
| `ssid`, `bssid`, `rssi` | Wi-Fi link context (blank when wired) |
| `timestamp`, `epoch` | when *that device* finished the measurement |
| `sent`, `received`, `loss_pct` | probes sent/replied and loss (for DNS: lookups that resolved) |
| `ping_min_ms`, `ping_avg_ms`, `ping_max_ms`, `jitter_ms` | latency stats (for DNS: resolution times) |
| `down_mbps`, `up_mbps` | throughput |
| `speed_latency_ms`, `speed_jitter_ms` | idle latency/jitter reported by the speed test |
| `down_latency_ms`, `up_latency_ms` | **latency under load** (bufferbloat), average |
| `down_latency_high_ms`, `up_latency_high_ms`, `down_latency_jitter_ms`, `up_latency_jitter_ms` | worst case / jitter of the loaded latency |
| `speed_packet_loss` | packet loss reported by the speed test |
| `speed_server`, `speed_server_id`, `speed_isp` | chosen server and ISP |
| `speed_iface`, `speed_ip_internal`, `speed_ip_external`, `speed_vpn` | interface the test used |
| `speed_duration_s`, `speed_result_url` | how long the test took, shareable result link |
| `error` | any error message for that row |

The graph has one panel per metric — gateway ping, WAN ping average/max, probe
packet loss, DNS resolution, TCP connect, idle latency, latency under download,
latency under upload, download, upload and speedtest packet loss — with one line
per device (and per target for the probe panels).

## Notes

* All devices start probing as soon as the master sends the round, so the
  measurements line up in time.
* The **gateway vs WAN** split is what localises a problem: if the gateway ping
  spikes on the booster devices while the wired device is flat, the fault is the
  local hop, not the ISP.
* **Latency under load** is the bufferbloat metric. Idle latency can be 10 ms
  while a download pushes it past 200 ms — that is what makes a game lag even
  though a plain speed test looks fine.
* The **DNS probe** uses fresh hostnames picked per round, so the OS resolver
  cache cannot hide a slow or failing resolver.
* Speed tests are **staggered** by `--speed-stagger` seconds so they never
  overlap. Running them simultaneously shares the link *and* breaks the server
  selection — which showed up as absurd `speed_latency_ms` values (e.g.
  `1800000`) and speeds far below a solo `speedtest`. Keep `--interval` above
  the round estimate the master prints at startup.
* Ookla limits how often **one public IP** may run tests, and every device behind
  your router shares that limit. That is why only `--speed-devices` devices test
  per round (rotated) and why `--list-servers` / `check` also count towards it.
* If ICMP is filtered on the WAN, add `--ping-method tcp` on the master; the
  setting is passed to the slaves.
* The graph is drawn by the master only; slaves need neither matplotlib nor the
  graph settings.

## Troubleshooting

* **`check` says the binary is `python-speedtest-cli`** — uninstall the Python
  `speedtest-cli` (or reorder `PATH`) and install the Ookla CLI.
* **A speed test reports a tiny download but no `speed_result_url`** — the run
  aborted and the number is not a measurement (a healthy gigabit line can look
  like "4 Mbit/s"). Newer builds set
  `error = incomplete result from speedtest (no idle latency, upload, server,
  result url)`; filter on `error` (or on an empty `speed_result_url`) before
  analysing speeds in older files.
* **`429` / "Too many requests received"** — your public IP is rate limited by
  Ookla; it is shared by every device behind the router. The master detects it,
  prints the hint once and pauses speed tests for `--speed-cooldown` minutes. To
  hit the limit less often: only one device per round
  (`--speed-devices 1`, the default), a bigger `--interval`, `--speed-every`, and
  avoid repeated `--list-servers`/`check` runs. Try `--speed-every 3` with
  `--interval 180` for roughly one test per device per 9 minutes.
* **`ConfigurationError` on one device** — its Ookla config directory is not
  writable; `python -m wifi_test check` prints the path and the problem.
* **Every device spikes at the same moment** — look at the gateway and DNS rows
  for that round: if they are elevated too, the fault is local to the router or
  the wireless hop; if they are clean, it is upstream.
* **Apps slow but `down_mbps` high** — check the DNS-resolution panel/rows and
  the latency-under-load columns; that combination points at the resolver or at
  bufferbloat rather than at raw throughput.
* **Results look stale** — each run now writes its own `results/session-*.csv`;
  the master prints the exact path at startup. Also make sure only one master is
  running (`ps -ef | grep wifi_test`).
* **`no reply from <device>`** — that device either was not connected or its
  round overran; the master no longer waits the full `--round-timeout` for a
  device that dropped mid-round.
