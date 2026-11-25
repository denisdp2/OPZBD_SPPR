"""Точка входа: поднимает локальный сервер и открывает браузер.

По умолчанию сервер доступен только на этом компьютере (127.0.0.1).
Адрес можно изменить параметром --host.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import socket
import subprocess
import sys
import threading
import webbrowser
from pathlib import Path

import uvicorn

from app import __version__, paths


def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(prog="szi", description="СППР: подбор средств и мер защиты")
    p.add_argument("--port", type=int, default=0, help="порт (по умолчанию — любой свободный)")
    p.add_argument("--host", default="127.0.0.1", help="адрес (по умолчанию 127.0.0.1)")
    p.add_argument("--no-browser", action="store_true", help="не открывать браузер")
    p.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    return p.parse_args(argv)


def open_browser(url: str) -> None:
    if sys.platform == "win32":
        if paths.is_frozen():
            portable = Path(sys.executable).resolve().parent.parent / "browser" / "firefox.exe"
            if portable.is_file():
                profile = paths.data_dir() / "browser-profile"
                profile.mkdir(parents=True, exist_ok=True)
                subprocess.Popen([str(portable), "-profile", str(profile), url])
                return

        if sys.getwindowsversion().major < 10:
            for variable in ("ProgramFiles", "ProgramFiles(x86)", "ProgramW6432", "LOCALAPPDATA"):
                folder = os.environ.get(variable)
                if folder:
                    firefox = Path(folder) / "Mozilla Firefox" / "firefox.exe"
                    if firefox.is_file():
                        subprocess.Popen([str(firefox), url])
                        return
            print(
                "Откройте адрес в Firefox ESR 115. Internet Explorer не поддерживается.", flush=True
            )
            return

    webbrowser.open(url)


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    from app.api import create_app  # импорт здесь, чтобы --version работал мгновенно

    port = args.port or free_port()
    url = f"http://127.0.0.1:{port}"

    server: uvicorn.Server | None = None

    def stop() -> None:
        if server is not None:
            server.should_exit = True

    app = create_app(on_shutdown=stop)
    config = uvicorn.Config(app, host=args.host, port=port, log_level="warning")
    server = uvicorn.Server(config)

    if sys.platform == "win32" and sys.version_info[:2] == (3, 8):
        # The legacy Windows runtime can raise WinError 10054 in Proactor while closing sockets.
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

    print(f"СППР {__version__}")
    print(f"Данные: {paths.data_dir()}")
    print(f"Откройте в браузере: {url}")
    print(
        "Для завершения закройте это окно или нажмите «Завершить работу» в интерфейсе.",
        flush=True,
    )

    if not args.no_browser:
        threading.Timer(1.0, open_browser, args=(url,)).start()
    server.run()


if __name__ == "__main__":
    main()
