"""Run Parlera: python -m parlera [--port 8642] [--no-browser]"""
from __future__ import annotations

import argparse
import logging
import threading
import time


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

    from .config import Paths, Settings
    from .system import configure_offline, open_ui

    # Decide offline mode before any model library is imported.
    paths = Paths()
    paths.ensure()
    settings = Settings(paths.settings).all()
    offline = configure_offline(settings)

    from .main import create_app

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    app = create_app()
    app.state.offline = offline
    url = f"http://{args.host}:{args.port}"
    print(f"\n  Parlera is running at {url}\n  Data folder: {app.state.core.paths.root}\n  Press Ctrl+C to stop.\n")
    if not args.no_browser:
        mode = settings.get("app", {}).get("window", "auto")
        threading.Thread(target=lambda: (time.sleep(1.2), print("  Opened in:", open_ui(url, mode, paths.browser_profile))),
                         daemon=True).start()
    if offline["offline"]:
        print("  Offline mode: all models are downloaded, no internet needed.")
    elif offline["missing"]:
        print("  Will download on first use (needs internet once):", ", ".join(offline["missing"]))
    server = uvicorn.Server(uvicorn.Config(app, host=args.host, port=args.port, log_level="warning"))
    app.state.server = server  # lets the Quit button and the auto-quit watchdog stop the server
    server.run()
    print("\n  Parlera stopped. Your progress is saved.\n")


if __name__ == "__main__":
    main()
