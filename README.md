# Distributed Wi-Fi diagnostics

Measures **ping (latency, jitter, packet loss)** and **internet speed** on several
devices *at the same time*, so you can see whether "high ping / low speed" periods
affect every device on the Wi-Fi or only one. One device is the **master**; the
others run as **slaves** and report back over TCP on the local network.

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

## Run the master

On the always-on device (the one that will collect results and draw graphs):

```
python -m wifi_test master --interval 60 --speed
```

* `--interval 60`   start a measurement round every 60 seconds.
* `--speed`         also run an Ookla speed test each round (~30 s). Without it
                    only ping/loss is measured, which is much faster.
* `--speed-stagger 15`  start each device's speed test this many seconds after
                    the previous one, so tests don't share the link or corrupt
                    server selection.
* `--speed-server-id 12345`  pin one server for comparable results (find an id
                    with `--list-servers`).
* `--speed-timeout 180`  seconds before a speed test is abandoned.
* `--duration 30`   stop automatically after 30 minutes (0 = run until Ctrl+C).
* `--results results.csv`   results file, appended after every round.
* `--graph wifi_graphs.png` graph image, rewritten after every round.
* `--show`          also open a live graph window.
* `--no-graphs`     skip graphs entirely.

The master prints its listening address and its own device name on startup.

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

## Output

`results.csv` is a long-format time series with one row per measurement:

| column | meaning |
|--------|---------|
| `timestamp`, `epoch` | when the measurement finished |
| `round` | round number (same across devices for the same round) |
| `device`, `role` | device label and `master`/`slave` |
| `kind` | `ping` or `speed` |
| `target`, `sent`, `received`, `loss_pct` | ping probe details |
| `ping_min_ms`, `ping_avg_ms`, `ping_max_ms`, `jitter_ms` | latency stats |
| `down_mbps`, `up_mbps`, `speed_server`, `speed_latency_ms` | speedtest results |
| `error` | any error message for that row |

The master also redraws `wifi_graphs.png` after each round with one panel per
metric (ping average, ping maximum, packet loss, download, upload) and one line
per device.

## Notes

* All devices run their round as soon as the master broadcasts it, so the
  measurements line up in time.
* Speed tests are **staggered** by `--speed-stagger` seconds so they never
  overlap. Running them simultaneously shares the link *and* breaks the server
  selection — which shows up as absurd `speed_latency_ms` values (e.g.
  `1800000`) and speeds far below a solo `speedtest`. Keep `--interval` above
  the round estimate the master prints at startup.
* If ICMP ping is blocked, add `--ping-method tcp --tcp-port 443` on the master;
  the setting is passed to the slaves.
* The graph is drawn by the master only; slaves need neither matplotlib nor the
  graph settings.

## Troubleshooting

* **Slaves disconnect/reconnect every round** — fixed in this version; make sure
  every device runs the same (current) copy of the tool.
* **Speeds far below a manual `speedtest`** — confirm `speedtest --version` says
  "Speedtest by Ookla" on that device, raise `--speed-stagger`, and/or pin a
  server with `--list-servers` + `--speed-server-id`.
* **"speed tests skipped for <device>"** — the Ookla CLI isn't on that device's
  `PATH`, or the Python `speedtest-cli` is shadowing it.
* **CSV looks out of date** — make sure only one master is running
  (`ps -ef | grep wifi_test`) and that the `results file : …` line printed at
  master startup matches the file you are opening.
* **A slave ack'd no result for a round** — the master logs
  `no reply from <device>`; the device either was not connected yet or its test
  overran `--speed-timeout`.
