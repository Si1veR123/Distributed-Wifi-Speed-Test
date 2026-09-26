"""Live time-series graphs for the master (matplotlib, optional dependency)."""

from __future__ import annotations

import os


GRAPH_ACCENTS = (
    "#1f77b4", "#ff7f0e", "#2ca02c", "#d62728",
    "#9467bd", "#8c564b", "#e377c2", "#17becf",
)

# (result-file column, axis title, y-axis unit)
GRAPH_SERIES = (
    ("ping_avg_ms", "Ping - average", "ms"),
    ("ping_max_ms", "Ping - maximum", "ms"),
    ("loss_pct", "Packet loss", "%"),
    ("down_mbps", "Download speed", "Mbit/s"),
    ("up_mbps", "Upload speed", "Mbit/s"),
)


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

        devices = list(history.keys())
        for index, (column, title, unit) in enumerate(GRAPH_SERIES):
            axis = self._axes[index]
            axis.clear()
            axis.set_title(title, fontsize=10)
            axis.set_ylabel(unit, fontsize=8)
            axis.grid(True, alpha=0.3)
            axis.tick_params(axis="x", labelrotation=30, labelsize=7)
            if unit == "%":
                axis.set_ylim(0, 100)

            plotted = 0
            for device_index, device in enumerate(devices):
                times = []
                values = []
                for row in history.get(device, []):
                    value = row.get(column)
                    if value in (None, ""):
                        continue
                    try:
                        values.append(float(value))
                        times.append(float(row.get("epoch") or 0.0))
                    except (TypeError, ValueError):
                        continue
                if times:
                    axis.plot(
                        times,
                        values,
                        marker=".",
                        linewidth=1.0,
                        markersize=4,
                        color=GRAPH_ACCENTS[device_index % len(GRAPH_ACCENTS)],
                        label=device,
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
