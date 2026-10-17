"""Пути к ресурсам и данным.

Программа должна одинаково работать:
  * из исходников (python run.py);
  * из сборки PyInstaller, запущенной с флешки на любом компьютере.

Поэтому пути НИКОГДА не считаются от текущей папки (os.getcwd()),
только от расположения программы.
"""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

log = logging.getLogger(__name__)

APP_NAME = "szi-sppr"


def is_frozen() -> bool:
    """True, если программа запущена из сборки PyInstaller."""
    return bool(getattr(sys, "frozen", False))


def project_root() -> Path:
    """Корень репозитория (в режиме разработки)."""
    return Path(__file__).resolve().parent.parent


def resource_dir() -> Path:
    """Папка с ресурсами, вшитыми в сборку (frontend/)."""
    if is_frozen():
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).resolve().parent))
    return project_root()


def frontend_dir() -> Path:
    return resource_dir() / "frontend"


def _is_writable(p: Path) -> bool:
    try:
        p.mkdir(parents=True, exist_ok=True)
        probe = p / ".write_test"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
        return True
    except OSError:
        return False


def data_dir() -> Path:
    """Папка для изменяемых данных: база, сохранённые сценарии.

    Порядок поиска:
      1. переменная окружения SZI_DATA_DIR;
      2. в сборке: data/ рядом с исполняемым файлом или уровнем выше
         (раскладка на флешке: SZI/szi/szi.exe + SZI/data/);
      3. в разработке: data/ в корне репозитория.
    Если папка недоступна для записи (флешка только для чтения),
    используется ~/.szi-sppr/data.
    """
    env = os.environ.get("SZI_DATA_DIR")
    if env:
        candidates = [Path(env)]
    elif is_frozen():
        exe_dir = Path(sys.executable).resolve().parent
        options = [exe_dir / "data", exe_dir.parent / "data"]
        candidates = [p for p in options if p.is_dir()] or options[:1]
    else:
        candidates = [project_root() / "data"]

    for c in candidates:
        if _is_writable(c):
            return c

    fallback = Path.home() / f".{APP_NAME}" / "data"
    fallback.mkdir(parents=True, exist_ok=True)
    log.warning("Папка %s недоступна для записи, данные сохраняются в %s", candidates[0], fallback)
    return fallback
