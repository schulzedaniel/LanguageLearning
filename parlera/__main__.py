"""Run Parlera: python -m parlera [--port 8642] [--no-browser]"""
from __future__ import annotations

import argparse
import logging
import threading
import time
import webbrowser


def main() -> None:
    parser = argparse.ArgumentParser(prog="parlera", description="Local language tutor")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8642)
    parser.add_argument("--no-browser", action="store_true")
    parser.add_argument("--data", help="data directory (default ~/Parlera or $PARLERA_DATA)")
    args = parser.parse_args()

    if args.data:
        import os
        os.environ["PARLERA_DATA"] = args.data

    import uvicorn

    from .main import create_app

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    app = create_app()
    url = f"http://{args.host}:{args.port}"
    print(f"\n  Parlera is running at {url}\n  Data folder: {app.state.core.paths.root}\n  Press Ctrl+C to stop.\n")
    if not args.no_browser:
        threading.Thread(target=lambda: (time.sleep(1.2), webbrowser.open(url)), daemon=True).start()
    server = uvicorn.Server(uvicorn.Config(app, host=args.host, port=args.port, log_level="warning"))
    app.state.server = server  # lets the Quit button and the auto-quit watchdog stop the server
    server.run()
    print("\n  Parlera stopped. Your progress is saved.\n")


if __name__ == "__main__":
    main()
