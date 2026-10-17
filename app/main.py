"""Точка входа: поднимает локальный сервер и открывает браузер.

Программа слушает только 127.0.0.1, поэтому брандмауэр Windows не
спрашивает прав администратора, а с других компьютеров она недоступна.
"""

from __future__ import annotations

import argparse
import logging
import socket
import threading
import webbrowser

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

    print(f"СППР {__version__}")
    print(f"Данные: {paths.data_dir()}")
    print(f"Откройте в браузере: {url}")
    print("Для завершения закройте это окно или нажмите «Завершить работу» в интерфейсе.")

    if not args.no_browser:
        threading.Timer(1.0, lambda: webbrowser.open(url)).start()
    server.run()


if __name__ == "__main__":
    main()
