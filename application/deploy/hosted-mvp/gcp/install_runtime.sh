#!/bin/bash
# Relocate the exact official bookworm Python runtime onto a fresh Ubuntu host.
set -euo pipefail
umask 022
test "${EPM_H02_QUALIFICATION:-}" = 1
test "$(id -u)" = 0
test ! -e /opt/epm/python
install -d -m 0755 /opt/epm/python
image='python@sha256:1faf2343e747208b2a36e5f2b5ff908ec3b2d0078a6a7bfe73b535698fe83909'
container_id=$(docker create --entrypoint /bin/true "$image")
trap 'docker rm "$container_id" >/dev/null' EXIT
docker cp "$container_id:/usr/local/." /opt/epm/python/
printf '/opt/epm/python/lib\n' >/etc/ld.so.conf.d/epm-python.conf
ldconfig
/opt/epm/python/bin/python3.14 -c 'import sys,ssl,sqlite3,bz2,lzma,ctypes,zlib; assert sys.version_info[:2] == (3,14); print(sys.version)'
