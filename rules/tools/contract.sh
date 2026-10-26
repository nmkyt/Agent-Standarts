#!/usr/bin/env bash
# Проверка контракта подключения: AGENTS.md, конфиг проекта, gate. Ничего не меняет.
set -euo pipefail

# Python: $PYTHON или первый рабочий из python3/python/py.
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
cd "$HERE/../.."
PY="$(find_python)"
exec "$PY" "$HERE/core.py" contract
