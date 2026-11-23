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
    parser.add_argument("--demo", choices=["copy", "fresh"],
                        help="demo mode: run on a temporary copy of your data (deleted afterwards)")
    args = parser.parse_args()

    import os
    if args.data:
        os.environ["PARLERA_DATA"] = args.data
    demo_dir = None
    real_profile = None
    if args.demo:
        from .config import Paths as _Paths
        from .demo import prepare_demo_dir
        real_profile = _Paths().browser_profile   # reuse the app-window profile (keeps the mic permission)
        demo_dir = prepare_demo_dir(_Paths(), args.demo)
        os.environ["PARLERA_DATA"] = str(demo_dir)
        os.environ["PARLERA_DEMO"] = args.demo

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
    if demo_dir:
        print(f"\n  DEMO MODE ({args.demo}) at {url}\n  Temporary data: {demo_dir} (deleted when the demo stops)\n")
    else:
        print(f"\n  Parlera is running at {url}\n  Data folder: {app.state.core.paths.root}\n  Press Ctrl+C to stop.\n")
    if not args.no_browser:
        mode = settings.get("app", {}).get("window", "auto")
        threading.Thread(target=lambda: (time.sleep(1.2), print("  Opened in:", open_ui(url, mode, real_profile if demo_dir else paths.browser_profile))),
                         daemon=True).start()
    if offline["offline"]:
        print("  Offline mode: all models are downloaded, no internet needed.")
    elif offline["missing"]:
        print("  Will download on first use (needs internet once):", ", ".join(offline["missing"]))
    server = uvicorn.Server(uvicorn.Config(app, host=args.host, port=args.port, log_level="warning"))
    app.state.server = server  # lets the Quit button and the auto-quit watchdog stop the server
    try:
        server.run()
    finally:
        if demo_dir:
            import shutil
            app.state.core.db.close()
            shutil.rmtree(demo_dir, ignore_errors=True)
            print("\n  Demo ended — the temporary copy was deleted. Your real data was never touched.\n")
        else:
            print("\n  Parlera stopped. Your progress is saved.\n")


if __name__ == "__main__":
    main()
