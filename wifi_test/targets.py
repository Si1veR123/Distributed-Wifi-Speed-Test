"""Discovery helpers: default gateway, DNS servers and Wi-Fi link context.

Everything here is best-effort: on failure the caller simply gets ``None`` or
an empty value and the round carries on.
"""

from __future__ import annotations

import platform
import re
import subprocess


_SYSTEM = platform.system().lower()
_IS_WINDOWS = _SYSTEM.startswith("win")
_IS_DARWIN = _SYSTEM == "darwin"


def run_command(command, timeout=10):
    """Run *command* and return its combined output (empty string on failure)."""
    try:
        completed = subprocess.run(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            errors="replace",
            timeout=timeout,
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    return completed.stdout or ""


def _first_ip(line):
    match = re.search(r"(\d{1,3}(?:\.\d{1,3}){3})", line)
    return match.group(1) if match else None


def default_gateway():
    """Return the IPv4 default gateway, or ``None``."""
    if _IS_WINDOWS:
        for line in run_command(["ipconfig"]).splitlines():
            if "gateway" in line.lower():
                address = _first_ip(line)
                if address and address != "0.0.0.0":
                    return address
        for line in run_command(["route", "print", "-4"]).splitlines():
            parts = line.split()
            if len(parts) >= 3 and parts[0] == "0.0.0.0" and parts[1] == "0.0.0.0":
                return parts[2]
        return None

    if _IS_DARWIN:
        for line in run_command(["netstat", "-rn", "-f", "inet"]).splitlines():
            parts = line.split()
            if len(parts) >= 2 and parts[0] == "default":
                return parts[1]
        return None

    text = run_command(["ip", "route", "show", "default"])
    match = re.search(r"default\s+via\s+(\d{1,3}(?:\.\d{1,3}){3})", text)
    if match:
        return match.group(1)
    for line in run_command(["route", "-n"]).splitlines():
        parts = line.split()
        if len(parts) >= 2 and parts[0] == "0.0.0.0":
            return parts[1]
    return None


def dns_servers():
    """Return the configured IPv4 DNS servers (loopback/IPv6 filtered out)."""
    found = []
    if _IS_WINDOWS:
        capturing = False
        for line in run_command(["ipconfig", "/all"]).splitlines():
            if re.search(r"DNS servers", line, re.IGNORECASE):
                capturing = True
                found.extend(re.findall(r"\d{1,3}(?:\.\d{1,3}){3}", line))
                continue
            if capturing:
                if re.match(r"^\s{2,}\S.*:", line):
                    capturing = False
                    continue
                found.extend(re.findall(r"\d{1,3}(?:\.\d{1,3}){3}", line))
    else:
        try:
            with open("/etc/resolv.conf", encoding="utf-8", errors="replace") as handle:
                for line in handle:
                    parts = line.split()
                    if len(parts) >= 2 and parts[0] == "nameserver":
                        found.append(parts[1])
        except OSError:
            pass

    servers = []
    for server in found:
        if ":" in server or server.startswith("127.") or server == "0.0.0.0":
            continue
        if server not in servers:
            servers.append(server)
    return servers


def default_ping_targets():
    """Return ``[(target, kind), ...]`` covering the LAN hop and the WAN.

    ``kind`` is one of ``gateway``, ``dns`` or ``wan``; it is what lets the
    analysis tell a local problem from an upstream one.
    """
    targets = []
    gateway = default_gateway()
    if gateway:
        targets.append((gateway, "gateway"))
    for server in dns_servers()[:1]:
        targets.append((server, "dns"))
    targets.append(("1.1.1.1", "wan"))
    targets.append(("8.8.8.8", "wan"))
    return targets


def parse_targets(text):
    """Parse ``--ping-targets`` (``host`` or ``host:kind``, comma separated)."""
    targets = []
    for chunk in (text or "").split(","):
        chunk = chunk.strip()
        if not chunk:
            continue
        if ":" in chunk and not re.match(r"^\d{1,3}(\.\d{1,3}){3}$", chunk):
            host, kind = chunk.rsplit(":", 1)
            targets.append((host.strip(), kind.strip() or "wan"))
        else:
            targets.append((chunk, "wan"))
    return targets


def _split_escaped(text, separator=":"):
    """Split on *separator*, honouring nmcli's backslash escaping."""
    parts = []
    current = []
    escaped = False
    for char in text:
        if escaped:
            current.append(char)
            escaped = False
        elif char == "\\":
            escaped = True
        elif char == separator:
            parts.append("".join(current))
            current = []
        else:
            current.append(char)
    parts.append("".join(current))
    return parts


def _linux_wifi():
    for line in run_command(
        ["nmcli", "-t", "-f", "DEVICE,ACTIVE,SSID,BSSID,SIGNAL", "dev", "wifi"]
    ).splitlines():
        parts = _split_escaped(line.strip())
        if len(parts) >= 5 and parts[1].lower() in ("yes", "connected"):
            return {
                "iface": parts[0],
                "ssid": parts[2],
                "bssid": parts[3],
                "rssi": parts[4],
            }
    return {}


def _windows_wifi():
    output = run_command(["netsh", "wlan", "show", "interfaces"])
    if not output:
        return {}
    context = {}
    for line in output.splitlines():
        if ":" not in line:
            continue
        label, _, value = line.partition(":")
        label = label.strip().lower()
        value = value.strip()
        if label == "name" and "iface" not in context:
            context["iface"] = value
        elif label == "ssid":
            context["ssid"] = value
        elif label == "bssid":
            context["bssid"] = value
        elif label == "signal":
            match = re.search(r"(\d+)", value)
            if match:
                context["rssi"] = match.group(1)
    return context if context.get("ssid") else {}


def wifi_context():
    """Return ``{iface, ssid, bssid, rssi}`` for the active Wi-Fi link.

    ``rssi`` is a percentage on Windows (netsh) and Linux (nmcli signal).
    Wired devices get an empty dict.
    """
    try:
        if _IS_WINDOWS:
            return _windows_wifi()
        if _IS_DARWIN:
            return {}
        return _linux_wifi()
    except Exception:  # pragma: no cover - never break a round over this
        return {}
