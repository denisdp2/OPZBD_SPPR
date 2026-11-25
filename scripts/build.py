"""Сборка портативной версии для Windows и Linux.

Программа работает без установки, в том числе с флешки.

    pip install -e .[build]
    python scripts/build.py

Результат: dist/SZI-<os>/ и архив dist/SZI-<os>.zip

    SZI-<os>/
    ├── szi/                 программа (PyInstaller, режим onedir)
    ├── data/                база и сценарии (сохраняются между запусками)
    ├── start-windows.bat  или  start-linux.sh
    └── README.txt

Кросс-компиляции нет: версию для Windows собирают на Windows, для Linux —
на Linux (лучше на самой старой Ubuntu, где программа должна работать:
сборка привязана к версии glibc). В GitHub Actions это делает release.yml.
"""

from __future__ import annotations

import argparse
import os
import platform
import shutil
import stat
import subprocess
import sys
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).resolve().parent.parent
DIST = ROOT / "dist"
LAUNCHERS = ROOT / "scripts" / "launchers"


def os_tag() -> str:
    if platform.system() == "Windows" and sys.version_info[:2] == (3, 8):
        # Use the interpreter architecture, including when x86 Python runs on x64 Windows.
        return "windows-legacy-x64" if sys.maxsize > 2**32 else "windows-legacy-x86"
    return {"Windows": "windows", "Linux": "linux", "Darwin": "macos"}.get(
        platform.system(), platform.system().lower()
    )


def run_pyinstaller() -> Path:
    sep = os.pathsep  # ';' на Windows, ':' на Linux
    tag = os_tag()
    distpath = DIST / "pyinstaller" / tag
    workpath = ROOT / "build" / tag
    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--noconfirm", "--clean", "--onedir",
        "--name", "szi",
        "--distpath", str(distpath),
        "--workpath", str(workpath),
        "--specpath", str(workpath),
        "--paths", str(ROOT),
        "--add-data", f"{ROOT / 'frontend'}{sep}frontend",
        # uvicorn подгружает часть модулей по строковым именам
        "--collect-submodules", "uvicorn",
        str(ROOT / "run.py"),
    ]  # fmt: skip
    print(">", " ".join(cmd))
    subprocess.run(cmd, check=True)
    return distpath / "szi"


def assemble(app_dir: Path, firefox_dir: Optional[Path] = None) -> Path:
    tag = os_tag()
    if firefox_dir is not None:
        tag += "-with-firefox"
    out = DIST / f"SZI-{tag}"
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)

    shutil.copytree(app_dir, out / "szi")
    if firefox_dir is not None:
        shutil.copytree(firefox_dir, out / "browser")
    (out / "data").mkdir()
    shutil.copy(ROOT / "data" / "seed_bundle.json", out / "data" / "seed_bundle.json")
    shutil.copy(LAUNCHERS / "README.txt", out / "README.txt")

    if platform.system() == "Windows":
        shutil.copy(LAUNCHERS / "start-windows.bat", out / "start-windows.bat")
    else:
        dst = out / "start-linux.sh"
        shutil.copy(LAUNCHERS / "start-linux.sh", dst)
        dst.chmod(dst.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)

    archive = shutil.make_archive(str(out), "zip", root_dir=DIST, base_dir=out.name)
    print(f"Готово: {out}\nАрхив: {archive}")
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--firefox-dir", type=Path, help="каталог Firefox ESR 115 для Windows")
    args = parser.parse_args()
    if args.firefox_dir is not None and (
        not os_tag().startswith("windows-legacy-")
        or not (args.firefox_dir / "firefox.exe").is_file()
    ):
        parser.error("--firefox-dir требует сборку Windows Legacy и каталог с firefox.exe")
    assemble(run_pyinstaller(), args.firefox_dir)


if __name__ == "__main__":
    main()
