#!/usr/bin/env python3
"""Deterministic XOS mock node worker — stdin lines, stdout replies. No network."""

import sys


def handle(line: str) -> str | None:
    text = line.strip()
    if not text:
        return None
    upper = text.upper()
    if upper == "PING":
        return "PONG"
    if upper == "EXIT":
        return "BYE"
    if upper.startswith("ECHO "):
        return text[5:]
    if text.startswith("XOS_SPOOF:"):
        # Simulate a provider trying to forge identity — manager must ignore it
        return text
    return f"XOS_NODE_REPLY: {text}"


def main() -> None:
    sys.stdout.write("XOS_NODE_READY\n")
    sys.stdout.flush()
    for raw in sys.stdin:
        line = raw.rstrip("\n")
        reply = handle(line)
        if reply is not None:
            sys.stdout.write(reply + "\n")
            sys.stdout.flush()
        if line.strip().upper() == "EXIT":
            break


if __name__ == "__main__":
    main()
