#!/bin/sh
# Dev helper: rebuild the zip (frontend included) and upgrade the extension inside the local
# Plesk test container (docker container "grt-plesk", see README.md).
set -e
cd "$(dirname "$0")/.."
python build.py
VERSION=$(sed -n 's:.*<version>\(.*\)</version>.*:\1:p' src/meta.xml)
RELEASE=$(sed -n 's:.*<release>\(.*\)</release>.*:\1:p' src/meta.xml)
MSYS_NO_PATHCONV=1 docker cp "dist/runway-$VERSION-$RELEASE.zip" grt-plesk:/root/runway.zip
MSYS_NO_PATHCONV=1 docker exec grt-plesk plesk bin extension --upgrade /root/runway.zip
