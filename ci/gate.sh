#!/usr/bin/env bash
# Проверки самого центра: тесты на временных репозиториях, без сети.
set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")/.."

find_python() {
  if [ -n "${PYTHON:-}" ]; then echo "$PYTHON"; return 0; fi
  local c
  for c in python3 python py; do
    if "$c" -c "" >/dev/null 2>&1; then echo "$c"; return 0; fi
  done
  echo "Python 3.9+ не найден (задайте PYTHON)" >&2
  return 1
}

PY="$(find_python)"
exec "$PY" -m unittest discover -s tests -v
