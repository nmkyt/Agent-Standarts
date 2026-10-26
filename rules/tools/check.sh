#!/usr/bin/env bash
# Единая точка входа проверок: integrity -> contract -> ci/gate.sh. Ничего не правит.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$HERE/../.." && pwd)"
cd "$ROOT"

echo "== integrity =="
bash "$HERE/integrity.sh"
echo "== contract =="
bash "$HERE/contract.sh"
echo "== ci/gate.sh =="
if [ ! -f ci/gate.sh ]; then
  echo "check: нет ci/gate.sh" >&2
  exit 1
fi
bash ci/gate.sh
echo "check: ок"
