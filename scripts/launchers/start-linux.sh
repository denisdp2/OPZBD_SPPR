#!/bin/sh
# Запуск портативной программы. Данные хранятся в папке data рядом с этим файлом.
#
# Если файл не запускается двойным щелчком, выполните в терминале:
#     sh start-linux.sh
#
# На носителях с FAT32/exFAT или при монтировании с noexec прямой запуск
# может быть недоступен. В этом случае программа копируется во временную
# папку и запускается оттуда; данные остаются в исходной папке data.

DIR="$(cd "$(dirname "$0")" && pwd)"
export SZI_DATA_DIR="$DIR/data"
BIN="$DIR/szi/szi"

if [ -x "$BIN" ] && "$BIN" --version >/dev/null 2>&1; then
    exec "$BIN" "$@"
fi

TMP="${TMPDIR:-/tmp}/szi-sppr-$(id -u)"
echo "Прямой запуск недоступен, копирую программу в $TMP ..."
rm -rf "$TMP"
mkdir -p "$TMP"
cp -r "$DIR/szi" "$TMP/"
chmod +x "$TMP/szi/szi"
exec "$TMP/szi/szi" "$@"
