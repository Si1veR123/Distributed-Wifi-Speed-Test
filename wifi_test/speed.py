"""Download/upload speed measurement using the speedtest-cli library."""

from __future__ import annotations


def run_speedtest() -> dict:
    """Run a speedtest and return a stats dict (raises on fatal errors)."""
    import speedtest

    client = speedtest.Speedtest(secure=True)
    server = client.get_best_server()
    download_bps = client.download()
    upload_bps = client.upload()

    server = server or {}
    return {
        "down_mbps": download_bps / 1_000_000.0,
        "up_mbps": upload_bps / 1_000_000.0,
        "speed_server": "{} - {}".format(server.get("sponsor", "?"), server.get("name", "?")),
        "speed_latency_ms": server.get("latency"),
        "error": None,
    }
