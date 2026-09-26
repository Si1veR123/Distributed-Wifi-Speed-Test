# Distributed Wi-Fi diagnostics

Measures **ping (latency, jitter, packet loss)** and **internet speed** on several
devices *at the same time*, so you can see whether "high ping / low speed" periods
affect every device on the Wi-Fi or only one. One device is the **master**; the
others run as **slaves** and report back over TCP on the local network.

## Install

```
python -m pip install -r requirements.txt
```

`matplotlib` is only needed on the master (for graphs). `speedtest-cli` is used
for the download/upload measurement and takes roughly 30 seconds per test.

## Run the master

On the always-on device (the one that will collect results and draw graphs):

```
python -m wifi_test master --interval 60 --speed
```

* `--interval 60`   start a measurement round every 60 seconds.
* `--speed`         also run a speedtest each round (~30 s). Without it only
                    ping/loss is measured, which is much faster.
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
* Running a speedtest on every device at once saturates the connection, so the
  measured speed is shared. If you want representative per-device speeds use
  `--speed-every 5` (speed test every 5th round) or leave `--speed` off.
* If ICMP ping is blocked, add `--ping-method tcp --tcp-port 443` on the master;
  the setting is passed to the slaves.
* The graph is drawn by the master only; slaves need neither matplotlib nor the
  graph settings.
