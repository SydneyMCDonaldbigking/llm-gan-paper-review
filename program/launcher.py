from __future__ import annotations

import sys
import threading
import time
import webbrowser

import uvicorn

from runtime_paths import get_runtime_program_dir, get_workspace_dir


HOST = "127.0.0.1"
PORT = 8000


def _prepare_workspace() -> None:
    workspace_dir = get_workspace_dir()
    runtime_dir = get_runtime_program_dir()
    for path in [
        workspace_dir / "essay",
        workspace_dir / "api_settings",
        workspace_dir / "final_report",
        runtime_dir,
    ]:
        path.mkdir(parents=True, exist_ok=True)


def _open_browser_later() -> None:
    time.sleep(2.0)
    webbrowser.open(f"http://{HOST}:{PORT}/")


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    _prepare_workspace()
    from review_api import app as review_app

    threading.Thread(target=_open_browser_later, daemon=True).start()
    uvicorn.run(review_app, host=HOST, port=PORT, reload=False)


if __name__ == "__main__":
    main()
