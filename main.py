#!/usr/bin/env python3
"""
OSINT Agent-X — Python version
Usage:
  python main.py          → Start CLI (interactive terminal)
  python main.py --server → Start web server
  python main.py --cli    → Start CLI (explicit)
"""
import sys
import os
from dotenv import load_dotenv

load_dotenv()


def main():
    if len(sys.argv) > 1 and sys.argv[1] in ("--server", "-s"):
        from server import start_server
        port = int(os.environ.get("PORT", "3000"))
        host = os.environ.get("HOST", "127.0.0.1")
        start_server(host=host, port=port)
    else:
        from cli import main as cli_main
        cli_main()


if __name__ == "__main__":
    main()
