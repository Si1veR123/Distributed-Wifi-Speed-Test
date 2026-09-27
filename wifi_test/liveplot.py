"""Live time-series graphs for the master (matplotlib, optional dependency)."""

from __future__ import annotations

import os


GRAPH_ACCENTS = (
    "#1f77b4", "#ff7f0e", "#2ca02c", "#d62728",
    "#9467bd", "#8c564b", "#e377c2", "#17becf",
)

# (result-file column, panel title, y-axis unit, row filter)
GRAPH_SERIES = (
    ("ping_avg_ms", "Ping - gateway (average)", "ms",
     {"kind": "ping", "target_kind": "gateway"}),
    ("ping_avg_ms", "Ping - WAN (average)", "ms",
     {"kind": "ping", "target_kind": "wan"}),
    ("ping_max_ms", "Ping - WAN (worst probe)", "ms",
     {"kind": "ping", "target_kind": "wan"}),
    ("loss_pct", "Packet loss (probes)", "%", {"kind": ("ping", "dns")}),
    ("ping_avg_ms", "DNS resolution", "ms", {"kind": "dns"}),
    ("ping_avg_ms", "TCP connect", "ms", {"kind": "ping", "target_kind": "tcp"}),
    ("speed_latency_ms", "Latency idle (speedtest)", "ms", {"kind": "speed"}),
    ("down_latency_ms", "Latency under download", "ms", {"kind": "speed"}),
    ("up_latency_ms", "Latency under upload", "ms", {"kind": "speed"}),
    ("down_mbps", "Download speed", "Mbit/s", {"kind": "speed"}),
    ("up_mbps", "Upload speed", "Mbit/s", {"kind": "speed"}),
    ("speed_packet_loss", "Packet loss (speedtest)", "%", {"kind": "speed"}),
)


def _matches(row, flt):
    for key, wanted in flt.items():
        value = row.get(key)
        if isinstance(wanted, (tuple, list, set)):
            if value not in wanted:
                return False
        elif value != wanted:
            return False
    return True


def _series_for_panel(history, column, flt, split_target):
    """Group the rows of *history* into ``{label: ([x], [y])}``."""
    series = {}
    for device, rows in history.items():
        for row in rows:
            if not _matches(row, flt):
                continue
            value = row.get(column)
            if value in (None, ""):
                continue
            try:
                x = float(row.get("epoch") or 0.0)
                y = float(value)
            except (TypeError, ValueError):
                continue
            if split_target:
                label = "{} @{}".format(
                    device, row.get("target") or row.get("target_kind") or "?"
                )
            else:
                label = device
            times, values = series.setdefault(label, ([], []))
            times.append(x)
            values.append(y)
    return series


class GraphingUnavailable(RuntimeError):
    """Raised when matplotlib cannot be imported."""


def load_pyplot(interactive: bool):
    """Import matplotlib.pyplot with a sensible backend, or raise."""
    try:
        import matplotlib

        if not interactive:
            matplotlib.use("Agg", force=True)
        import matplotlib.pyplot as plt

        matplotlib.rcParams["axes.unicode_minus"] = False
        return plt
    except Exception as exc:  # pragma: no cover - depends on the environment
        raise GraphingUnavailable(str(exc)) from exc


class LivePlotter:
    """Redraws one figure with a panel per metric, one line per device."""

    def __init__(self, output_path, show=False, title="Distributed Wi-Fi diagnostics"):
        self.output_path = output_path
        self.show = show
        self.title = title
        self._plt = load_pyplot(interactive=show)
        self._fig = None
        self._axes = None

    def update(self, history):
        """Redraw from *history* (``device -> list of result rows``)."""
        plt = self._plt
        count = len(GRAPH_SERIES)
        columns = 2 if count > 1 else 1
        rows = (count + columns - 1) // columns

        if self._fig is None:
            if self.show:
                plt.ion()
            self._fig, axes = plt.subplots(
                rows, columns, figsize=(6.0 * columns, 2.6 * rows), squeeze=False
            )
            self._axes = [axes[r][c] for r in range(rows) for c in range(columns)]
            if self.show:
                try:
                    plt.show(block=False)
                except Exception:
                    pass

        for index, (column, title, unit, flt) in enumerate(GRAPH_SERIES):
            axis = self._axes[index]
            axis.clear()
            axis.set_title(title, fontsize=10)
            axis.set_ylabel(unit, fontsize=8)
            axis.grid(True, alpha=0.3)
            axis.tick_params(axis="x", labelrotation=30, labelsize=7)
            if unit == "%":
                axis.set_ylim(0, 100)

            split_target = flt.get("kind") != "speed"
            series = _series_for_panel(history, column, flt, split_target)

            plotted = 0
            for label in sorted(series):
                times, values = series[label]
                axis.plot(
                    times,
                    values,
                    marker=".",
                    linewidth=1.0,
                    markersize=4,
                    color=GRAPH_ACCENTS[plotted % len(GRAPH_ACCENTS)],
                    label=label,
                )
                plotted += 1

            if plotted:
                axis.legend(loc="best", fontsize=7)

        for index in range(count, len(self._axes)):
            self._axes[index].clear()

        self._fig.suptitle(self.title, fontsize=11)
        self._fig.tight_layout(rect=(0, 0, 1, 0.97))
        self._save()
        if self.show:
            try:
                self._fig.canvas.draw_idle()
                plt.pause(0.001)
            except Exception:
                pass

    def _save(self):
        try:
            directory = os.path.dirname(os.path.abspath(self.output_path))
            if directory:
                os.makedirs(directory, exist_ok=True)
            self._fig.savefig(self.output_path, dpi=100)
        except Exception as exc:  # pragma: no cover - best effort
            print(f"[graph] could not save {self.output_path}: {exc}")

    def close(self):
        if self._fig is None:
            return
        try:
            self._plt.close(self._fig)
        except Exception:
            pass
