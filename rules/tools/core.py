#!/usr/bin/env python3
"""Общая логика стандартов: lock, хеши, безопасные пути, проверки потребителя.

Используется центром (delivery/deliver.py) и сервисами (.agent-rules/tools/*.sh).
Только стандартная библиотека, Python 3.9+.

CLI (корень сервиса — текущий каталог):
    core.py integrity   целостность доставленных файлов по .agent-rules.lock
    core.py contract   контракт подключения сервиса
"""
import hashlib
import json
import os
import sys
from pathlib import PurePosixPath

MANAGED_DIR = ".agent-rules"
CLIENT_DIRS = {"claude": ".claude", "kilo": ".kilo", "cursor": ".cursor"}
LOCK_FILE = ".agent-rules.lock"
VERSION_FILE = ".agent-rules.version"
PROJECT_CONFIG = ".agent-rules.json"
GATE_FILE = "ci/gate.sh"
LOCK_SCHEMA = 1
STUB_MARKER = "GATE-UNCONFIGURED"
WORKFLOW_REF = ".agent-rules/workflow.md"


class RulesError(Exception):
    pass


def sha256_bytes(data):
    return hashlib.sha256(data).hexdigest()


def sha256_file(path):
    with open(path, "rb") as f:
        return sha256_bytes(f.read())


def safe_relpath(value, allowed_roots=None):
    """Нормализует относительный POSIX-путь; запрещает абсолютные пути, `..` и выход из корней."""
    if not isinstance(value, str) or not value:
        raise RulesError("пустой путь")
    if "\\" in value or ":" in value or value.startswith("/"):
        raise RulesError("недопустимый путь (абсолютный или с разделителем ОС): %s" % value)
    parts = PurePosixPath(value).parts
    if not parts or any(p in ("", ".", "..") for p in parts):
        raise RulesError("недопустимый путь (`.` или `..`): %s" % value)
    if allowed_roots is not None and parts[0] not in allowed_roots:
        raise RulesError(
            "путь вне управляемых каталогов (%s): %s" % (", ".join(sorted(allowed_roots)), value)
        )
    return "/".join(parts)


def managed_roots():
    return {MANAGED_DIR} | set(CLIENT_DIRS.values())


def is_executable_dest(dest):
    return dest.endswith(".sh")


def read_lock(root):
    path = os.path.join(root, LOCK_FILE)
    if not os.path.isfile(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            lock = json.load(f)
    except (OSError, ValueError) as exc:
        raise RulesError("%s не читается: %s" % (LOCK_FILE, exc))
    if not isinstance(lock, dict) or lock.get("schema") != LOCK_SCHEMA or not isinstance(lock.get("managed"), dict):
        raise RulesError("%s: неподдерживаемая схема" % LOCK_FILE)
    return lock


def dump_lock(lock):
    return json.dumps(lock, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def integrity(root):
    """Возвращает список ошибок целостности (пустой — всё в порядке)."""
    try:
        lock = read_lock(root)
    except RulesError as exc:
        return [str(exc)]
    if lock is None:
        return ["%s не найден: выполните deliver центрального репозитория" % LOCK_FILE]

    errors = []
    version_path = os.path.join(root, VERSION_FILE)
    try:
        with open(version_path, "r", encoding="utf-8") as f:
            version = f.read().strip()
    except OSError:
        version = None
    if version != lock.get("version"):
        errors.append("%s (%s) не совпадает с версией в lock (%s)" % (VERSION_FILE, version, lock.get("version")))

    for dest, info in sorted(lock["managed"].items()):
        try:
            safe_relpath(dest, managed_roots())
        except RulesError as exc:
            errors.append("lock содержит недопустимый путь: %s" % exc)
            continue
        path = os.path.join(root, *dest.split("/"))
        if not os.path.isfile(path):
            errors.append("отсутствует: %s" % dest)
            continue
        if sha256_file(path) != info.get("sha256"):
            errors.append("изменён локально: %s" % dest)
        elif info.get("exec") and os.name != "nt" and not os.access(path, os.X_OK):
            errors.append("потерян бит исполняемости: %s" % dest)
    return errors


def contract(root):
    """Проверка контракта подключения. Возвращает список ошибок."""
    errors = []

    agents = os.path.join(root, "AGENTS.md")
    if not os.path.isfile(agents):
        errors.append("нет AGENTS.md")
    else:
        with open(agents, "r", encoding="utf-8") as f:
            text = f.read()
        if WORKFLOW_REF not in text:
            errors.append("AGENTS.md не ссылается на %s" % WORKFLOW_REF)
        if "{{" in text:
            errors.append("AGENTS.md содержит незаполненные {{...}} из шаблона")

    config = None
    config_path = os.path.join(root, PROJECT_CONFIG)
    if not os.path.isfile(config_path):
        errors.append("нет %s" % PROJECT_CONFIG)
    else:
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                config = json.load(f)
        except (OSError, ValueError) as exc:
            errors.append("%s не читается: %s" % (PROJECT_CONFIG, exc))
    if config is not None:
        if not isinstance(config, dict) or "schema" not in config:
            errors.append("%s: нет поля schema" % PROJECT_CONFIG)
        else:
            for key in ("read_first", "docs"):
                items = config.get(key)
                if not isinstance(items, list):
                    errors.append("%s: поле %s должно быть списком" % (PROJECT_CONFIG, key))
                    continue
                for item in items:
                    try:
                        rel = safe_relpath(item)
                    except RulesError as exc:
                        errors.append("%s: %s" % (key, exc))
                        continue
                    if not os.path.isfile(os.path.join(root, *rel.split("/"))):
                        errors.append("%s: файл не найден: %s" % (key, rel))

    gate = os.path.join(root, *GATE_FILE.split("/"))
    if not os.path.isfile(gate):
        errors.append("нет %s" % GATE_FILE)
    else:
        with open(gate, "r", encoding="utf-8", errors="replace") as f:
            if STUB_MARKER in f.read():
                errors.append("%s — заглушка шаблона: впишите проверки проекта и удалите маркер %s" % (GATE_FILE, STUB_MARKER))
    return errors


def main(argv=None):
    for stream in (sys.stdout, sys.stderr):
        stream.reconfigure(encoding="utf-8", errors="replace")
    argv = sys.argv[1:] if argv is None else argv
    commands = {"integrity": integrity, "contract": contract}
    if len(argv) != 1 or argv[0] not in commands:
        print("использование: core.py integrity|contract", file=sys.stderr)
        return 2
    errors = commands[argv[0]](os.getcwd())
    for err in errors:
        print("%s: %s" % (argv[0], err), file=sys.stderr)
    if not errors:
        print("%s: ок" % argv[0])
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
