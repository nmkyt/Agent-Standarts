#!/usr/bin/env bash
# Тонкая обёртка над deliver.py. Использование: delivery/deliver.sh [СЕРВИС] [--dry-run|--check] [--agent NAME]
set -euo pipefail

find_python() {
  if [ -n "${PYTHON:-}" ]; then echo "$PYTHON"; return 0; fi
  local c
  for c in python3 python py; do
    if "$c" -c "" >/dev/null 2>&1; then echo "$c"; return 0; fi
  done
  echo "Python 3.9+ не найден (задайте PYTHON)" >&2
  return 1
}

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PY="$(find_python)"
exec "$PY" "$HERE/deliver.py" "$@"
