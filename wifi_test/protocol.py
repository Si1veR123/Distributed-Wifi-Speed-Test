"""Tiny newline-delimited JSON protocol used between master and slaves."""

from __future__ import annotations

import json
import socket


ENCODING = "utf-8"

# Message types used on the wire.
MSG_HELLO = "hello"
MSG_RUN = "run"
MSG_RESULT = "result"
MSG_ROUND_DONE = "round_done"
MSG_SHUTDOWN = "shutdown"


def send_message(sock: socket.socket, message: dict) -> None:
    """Serialise *message* as one JSON line and send it over *sock*."""
    data = (json.dumps(message) + "\n").encode(ENCODING)
    sock.sendall(data)


class LineReader:
    """Reads newline-delimited JSON objects from a blocking socket."""

    def __init__(self, sock: socket.socket):
        self._sock = sock
        self._buffer = b""

    def read_message(self):
        """Return the next decoded JSON object, or ``None`` on EOF."""
        while b"\n" not in self._buffer:
            try:
                chunk = self._sock.recv(4096)
            except socket.timeout:
                # A read timeout only means "no data yet"; keep waiting.
                continue
            except OSError:
                return None
            if not chunk:
                return None
            self._buffer += chunk

        line, self._buffer = self._buffer.split(b"\n", 1)
        line = line.strip()
        if not line:
            return self.read_message()
        try:
            return json.loads(line.decode(ENCODING))
        except (ValueError, UnicodeDecodeError):
            # Ignore malformed lines instead of tearing the connection down.
            return self.read_message()
