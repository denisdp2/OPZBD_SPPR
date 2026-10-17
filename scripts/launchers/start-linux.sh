#!/bin/sh
# Запуск программы с флешки. Данные хранятся в папке data рядом с этим файлом.
#
# Если файл не запускается двойным щелчком, выполните в терминале:
#     sh start-linux.sh
#
# Флешки с FAT32/exFAT не хранят право на запуск, а иногда монтируются
# с noexec. В этом случае программа копируется во временную папку
# и запускается оттуда; данные всё равно пишутся на флешку.

DIR="$(cd "$(dirname "$0")" && pwd)"
export SZI_DATA_DIR="$DIR/data"
BIN="$DIR/szi/szi"

if [ -x "$BIN" ] && "$BIN" --version >/dev/null 2>&1; then
    exec "$BIN" "$@"
fi

TMP="${TMPDIR:-/tmp}/szi-sppr-$(id -u)"
echo "Запуск напрямую с флешки невозможен, копирую программу в $TMP ..."
rm -rf "$TMP"
mkdir -p "$TMP"
cp -r "$DIR/szi" "$TMP/"
chmod +x "$TMP/szi/szi"
exec "$TMP/szi/szi" "$@"
