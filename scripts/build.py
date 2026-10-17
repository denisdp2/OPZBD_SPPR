"""Сборка портативной версии для флешки.

    pip install -e .[build]
    python scripts/build.py

Результат: dist/SZI-<os>/ и архив dist/SZI-<os>.zip

    SZI-<os>/
    ├── szi/                 программа (PyInstaller, режим onedir)
    ├── data/                база и сценарии (сохраняются между запусками)
    ├── start-windows.bat  или  start-linux.sh
    └── ПРОЧТИ.txt

Кросс-компиляции нет: версию для Windows собирают на Windows, для Linux —
на Linux (лучше на самой старой Ubuntu, где программа должна работать:
сборка привязана к версии glibc). В GitHub Actions это делает release.yml.
"""

from __future__ import annotations

import os
import platform
import shutil
import stat
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DIST = ROOT / "dist"
LAUNCHERS = ROOT / "scripts" / "launchers"


def os_tag() -> str:
    return {"Windows": "windows", "Linux": "linux", "Darwin": "macos"}.get(
        platform.system(), platform.system().lower()
    )


def run_pyinstaller() -> Path:
    sep = os.pathsep  # ';' на Windows, ':' на Linux
    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--noconfirm", "--clean", "--onedir",
        "--name", "szi",
        "--distpath", str(DIST / "pyinstaller"),
        "--workpath", str(ROOT / "build"),
        "--specpath", str(ROOT / "build"),
        "--paths", str(ROOT),
        "--add-data", f"{ROOT / 'frontend'}{sep}frontend",
        # uvicorn подгружает часть модулей по строковым именам
        "--collect-submodules", "uvicorn",
        str(ROOT / "run.py"),
    ]  # fmt: skip
    print(">", " ".join(cmd))
    subprocess.run(cmd, check=True)
    return DIST / "pyinstaller" / "szi"


def assemble(app_dir: Path) -> Path:
    tag = os_tag()
    out = DIST / f"SZI-{tag}"
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)

    shutil.copytree(app_dir, out / "szi")
    (out / "data").mkdir()
    shutil.copy(LAUNCHERS / "ПРОЧТИ.txt", out / "ПРОЧТИ.txt")

    if tag == "windows":
        shutil.copy(LAUNCHERS / "start-windows.bat", out / "start-windows.bat")
    else:
        dst = out / "start-linux.sh"
        shutil.copy(LAUNCHERS / "start-linux.sh", dst)
        dst.chmod(dst.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)

    archive = shutil.make_archive(str(out), "zip", root_dir=DIST, base_dir=out.name)
    print(f"Готово: {out}\nАрхив: {archive}")
    return out


def main() -> None:
    assemble(run_pyinstaller())


if __name__ == "__main__":
    main()
