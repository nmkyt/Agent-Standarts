#!/usr/bin/env python3
"""Доставка управляемых файлов центра в сервис копиями.

    deliver.py [СЕРВИС] [--dry-run | --check] [--agent claude|kilo|cursor ...]

Источник — рабочая копия центра (каталог над delivery/). Без сети, без коммитов и тегов.
Локально изменённый управляемый файл не перезаписывается и не удаляется.
"""
import argparse
import os
import stat
import sys

CENTER = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(CENTER, "rules", "tools"))

import core as st  # noqa: E402


def read_manifest(center, allowed_roots):
    path = os.path.join(center, "delivery", "manifest.txt")
    entries, seen = [], set()
    with open(path, "r", encoding="utf-8") as f:
        for number, raw in enumerate(f, 1):
            line = raw.split("#", 1)[0].strip()
            if not line:
                continue
            fields = line.split()
            if len(fields) != 2:
                raise st.RulesError("manifest.txt:%d: ожидается «<src> <dest>»" % number)
            src = st.safe_relpath(fields[0])
            dest = st.safe_relpath(fields[1], allowed_roots)
            if dest in seen:
                raise st.RulesError("manifest.txt:%d: повтор назначения %s" % (number, dest))
            seen.add(dest)
            entries.append((src, dest))
    return entries


def read_version(center):
    with open(os.path.join(center, "VERSION"), "r", encoding="utf-8") as f:
        return f.read().strip()


def within(root, path):
    root_real = os.path.realpath(root)
    path_real = os.path.realpath(path)
    return path_real == root_real or path_real.startswith(root_real + os.sep)


def file_sha(path):
    return st.sha256_file(path) if os.path.isfile(path) else None


def plan(center, target, clients):
    """Строит план. Возвращает (actions, conflicts, lock_text, version)."""
    version = read_version(center)
    previous = st.read_lock(target)
    prev_files = previous["managed"] if previous else {}

    client_dirs = {st.CLIENT_DIRS[c] for c in clients}
    entries = read_manifest(center, st.managed_roots())

    desired = {}
    for src, dest in entries:
        root = dest.split("/", 1)[0]
        if root != st.MANAGED_DIR and root not in client_dirs:
            continue
        src_path = os.path.join(center, *src.split("/"))
        if not within(center, src_path) or not os.path.isfile(src_path):
            raise st.RulesError("источник не найден в центре: %s" % src)
        with open(src_path, "rb") as f:
            desired[dest] = f.read()

    actions, conflicts = [], []
    for dest in sorted(desired):
        path = os.path.join(target, *dest.split("/"))
        if not within(target, path):
            raise st.RulesError("путь выходит за пределы сервиса: %s" % dest)
        data = desired[dest]
        want = st.sha256_bytes(data)
        have = file_sha(path)
        if have is None:
            actions.append(("create", dest, data))
        elif have == want:
            if st.is_executable_dest(dest) and os.name != "nt" and not os.access(path, os.X_OK):
                actions.append(("chmod", dest, data))
        elif prev_files.get(dest, {}).get("sha256") == have:
            actions.append(("update", dest, data))
        elif dest in prev_files:
            conflicts.append("изменён локально, не перезаписан: %s" % dest)
        else:
            conflicts.append("уже существует и не управляется центром: %s" % dest)

    for dest in sorted(set(prev_files) - set(desired)):
        try:
            st.safe_relpath(dest, st.managed_roots())
        except st.RulesError as exc:
            conflicts.append("в прежнем lock недопустимый путь: %s" % exc)
            continue
        path = os.path.join(target, *dest.split("/"))
        have = file_sha(path)
        if have is None:
            continue
        if have == prev_files[dest].get("sha256"):
            actions.append(("remove", dest, None))
        else:
            conflicts.append("устарел, но изменён локально, не удалён: %s" % dest)

    lock = {
        "schema": st.LOCK_SCHEMA,
        "version": version,
        "source": {"name": os.path.basename(CENTER), "kind": "working-tree"},
        "clients": sorted(clients),
        "managed": {
            dest: {"sha256": st.sha256_bytes(data), "exec": st.is_executable_dest(dest)}
            for dest, data in desired.items()
        },
    }
    return actions, conflicts, st.dump_lock(lock), version


def apply(target, actions, lock_text, version):
    for kind, dest, data in actions:
        path = os.path.join(target, *dest.split("/"))
        if kind in ("create", "update"):
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "wb") as f:
                f.write(data)
        if kind in ("create", "update", "chmod") and st.is_executable_dest(dest) and os.name != "nt":
            mode = os.stat(path).st_mode
            os.chmod(path, mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
        if kind == "remove":
            os.remove(path)
            parent = os.path.dirname(path)
            while parent != target and os.path.isdir(parent) and not os.listdir(parent):
                os.rmdir(parent)
                parent = os.path.dirname(parent)
    # Метаданные пишутся последними: lock не опережает файлы.
    with open(os.path.join(target, st.VERSION_FILE), "w", encoding="utf-8", newline="\n") as f:
        f.write(version + "\n")
    with open(os.path.join(target, st.LOCK_FILE), "w", encoding="utf-8", newline="\n") as f:
        f.write(lock_text)


def read_text(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except OSError:
        return None


def main(argv=None):
    for stream in (sys.stdout, sys.stderr):
        stream.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description="Доставка управляемых файлов стандартов в сервис")
    parser.add_argument("target", nargs="?", default=".", help="корень сервиса (по умолчанию текущий каталог)")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true", help="показать план, ничего не писать")
    mode.add_argument("--check", action="store_true", help="выйти с кодом 1, если есть дрейф от центра")
    parser.add_argument("--agent", action="append", choices=sorted(st.CLIENT_DIRS), default=None,
                        help="доставить команды клиента (можно несколько); без флага берутся из прежнего lock")
    args = parser.parse_args(argv)

    target = os.path.abspath(args.target)
    if not os.path.isdir(target):
        print("deliver: каталог не найден: %s" % target, file=sys.stderr)
        return 1
    if os.path.realpath(target) == os.path.realpath(CENTER):
        print("deliver: центр не потребитель, укажите каталог сервиса", file=sys.stderr)
        return 1

    try:
        if args.agent is not None:
            clients = set(args.agent)
        else:
            previous = st.read_lock(target)
            clients = set(previous.get("clients", [])) if previous else set()
        actions, conflicts, lock_text, version = plan(CENTER, target, clients)
    except st.RulesError as exc:
        print("deliver: %s" % exc, file=sys.stderr)
        return 1

    for kind, dest, _ in actions:
        print("%-6s %s" % (kind, dest))
    for message in conflicts:
        print("deliver: %s" % message, file=sys.stderr)
    if conflicts:
        print("deliver: остановлено, ничего не изменено. Верните файл к версии центра "
              "или удалите локальную копию и запустите deliver снова.", file=sys.stderr)
        return 1

    drift = bool(actions)
    if read_text(os.path.join(target, st.LOCK_FILE)) != lock_text:
        drift = True
    if read_text(os.path.join(target, st.VERSION_FILE)) != version + "\n":
        drift = True

    if args.check:
        if drift:
            print("deliver: есть дрейф от центра (версия %s)" % version, file=sys.stderr)
            return 1
        print("deliver: ок (версия %s)" % version)
        return 0
    if args.dry_run:
        print("deliver: dry-run, %s" % ("изменения не применены" if drift else "изменений нет"))
        return 0

    if not drift:
        print("deliver: изменений нет (версия %s)" % version)
        return 0
    apply(target, actions, lock_text, version)
    print("deliver: готово (версия %s, файлов: %d)" % (version, lock_text.count('"sha256"')))
    return 0


if __name__ == "__main__":
    sys.exit(main())
