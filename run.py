"""Запуск из исходников: python run.py  (это же точка входа для PyInstaller)."""

import sys


def run() -> None:
    portable_windows = sys.platform == "win32" and getattr(sys, "frozen", False)
    try:
        if portable_windows:
            for stream in (sys.stdout, sys.stderr):
                if stream is not None:
                    stream.reconfigure(errors="backslashreplace")

        from app.main import main

        main()
    except Exception:
        if not portable_windows:
            raise

        import tempfile
        import traceback
        from contextlib import suppress
        from pathlib import Path

        log_path = Path(tempfile.gettempdir()) / "szi-startup-error.log"
        with log_path.open("w", encoding="utf-8", errors="backslashreplace") as log:
            log.write(f"Windows: {sys.getwindowsversion()}\nPython: {sys.version}\n\n")
            traceback.print_exc(file=log)

        with suppress(OSError):
            print(f"SZI stopped. Error log: {log_path}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    run()
