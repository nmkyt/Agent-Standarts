"""Тесты доставки и проверок стандартов. Временные репозитории, без сети."""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

CENTER = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TEMPLATE = os.path.join(CENTER, "starter")
ENV = dict(os.environ, PYTHON=sys.executable, PYTHONIOENCODING="utf-8")


def run(args, cwd, env=None):
    return subprocess.run(args, cwd=cwd, env=env or ENV, capture_output=True, text=True, encoding="utf-8")


def copy_center(dest):
    shutil.copytree(CENTER, dest, ignore=shutil.ignore_patterns(".git", ".idea", "__pycache__"))


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.service = os.path.join(self.tmp, "service")
        shutil.copytree(TEMPLATE, self.service)
        subprocess.run(["git", "init", "-q"], cwd=self.service, check=True)

    def deliver(self, *args, center=CENTER):
        script = os.path.join(center, "delivery", "deliver.py")
        return run([sys.executable, script, self.service] + list(args), cwd=self.tmp)

    def check_script(self):
        return run(["bash", ".agent-rules/tools/check.sh"], cwd=self.service)

    def path(self, rel):
        return os.path.join(self.service, *rel.split("/"))

    def read(self, rel):
        with open(self.path(rel), "r", encoding="utf-8") as f:
            return f.read()

    def write(self, rel, text):
        with open(self.path(rel), "w", encoding="utf-8", newline="\n") as f:
            f.write(text)

    def fill_scaffold(self, gate="#!/usr/bin/env bash\nexit 0\n"):
        text = self.read("AGENTS.md")
        import re
        self.write("AGENTS.md", re.sub(r"\{\{[A-Z_]+\}\}", "x", text))
        self.write("ci/gate.sh", gate)


class DeliveryTests(Base):
    def test_initial_delivery(self):
        result = self.deliver()
        self.assertEqual(result.returncode, 0, result.stderr)
        for rel in (".agent-rules/workflow.md", ".agent-rules/tools/check.sh", ".agent-rules.version", ".agent-rules.lock"):
            self.assertTrue(os.path.isfile(self.path(rel)), rel)
        lock = json.loads(self.read(".agent-rules.lock"))
        self.assertEqual(lock["version"], self.read(".agent-rules.version").strip())
        self.assertTrue(lock["managed"][".agent-rules/tools/integrity.sh"]["exec"])
        self.assertFalse(lock["managed"][".agent-rules/workflow.md"]["exec"])
        self.assertFalse(os.path.exists(self.path(".claude")))

    def test_dry_run_writes_nothing(self):
        result = self.deliver("--dry-run")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(os.path.exists(self.path(".agent-rules")))
        self.assertFalse(os.path.exists(self.path(".agent-rules.lock")))

    def test_idempotent(self):
        self.assertEqual(self.deliver().returncode, 0)
        before = self.read(".agent-rules.lock")
        again = self.deliver()
        self.assertEqual(again.returncode, 0)
        self.assertIn("изменений нет", again.stdout)
        self.assertEqual(self.read(".agent-rules.lock"), before)
        self.assertEqual(self.deliver("--check").returncode, 0)

    def test_check_fails_on_drift(self):
        self.assertEqual(self.deliver().returncode, 0)
        center = os.path.join(self.tmp, "center")
        copy_center(center)
        with open(os.path.join(center, "rules", "workflow.md"), "a", encoding="utf-8") as f:
            f.write("\nНовое правило.\n")
        drifted = self.deliver("--check", center=center)
        self.assertEqual(drifted.returncode, 1)
        self.assertIn("update", drifted.stdout)
        # После deliver из обновлённого центра дрейфа нет.
        self.assertEqual(self.deliver(center=center).returncode, 0)
        self.assertIn("Новое правило", self.read(".agent-rules/workflow.md"))
        self.assertEqual(self.deliver("--check", center=center).returncode, 0)

    def test_check_fails_when_file_missing(self):
        self.assertEqual(self.deliver().returncode, 0)
        os.remove(self.path(".agent-rules/workflow.md"))
        self.assertEqual(self.deliver("--check").returncode, 1)

    def test_refuses_to_overwrite_local_edit(self):
        self.assertEqual(self.deliver().returncode, 0)
        self.write(".agent-rules/workflow.md", "локальная правка\n")
        center = os.path.join(self.tmp, "center")
        copy_center(center)
        with open(os.path.join(center, "rules", "workflow.md"), "a", encoding="utf-8") as f:
            f.write("\nобновление\n")
        result = self.deliver(center=center)
        self.assertEqual(result.returncode, 1)
        self.assertIn("изменён локально", result.stderr)
        self.assertEqual(self.read(".agent-rules/workflow.md"), "локальная правка\n")

    def test_refuses_unmanaged_existing_file(self):
        os.makedirs(self.path(".agent-rules"))
        self.write(".agent-rules/workflow.md", "чужой файл\n")
        result = self.deliver()
        self.assertEqual(result.returncode, 1)
        self.assertEqual(self.read(".agent-rules/workflow.md"), "чужой файл\n")
        self.assertFalse(os.path.exists(self.path(".agent-rules.lock")))

    def test_path_protection(self):
        bad_dests = ["../escape.md", "/abs.md", "C:/abs.md", ".git/hooks/pre-commit", "docs/other.md", ".agent-rules/../x.md"]
        for dest in bad_dests:
            with self.subTest(dest=dest):
                center = os.path.join(self.tmp, "center-" + str(abs(hash(dest))))
                copy_center(center)
                with open(os.path.join(center, "delivery", "manifest.txt"), "a", encoding="utf-8") as f:
                    f.write("\nrules/workflow.md %s\n" % dest)
                result = self.deliver("--dry-run", center=center)
                self.assertEqual(result.returncode, 1, dest)
                self.assertFalse(os.path.exists(self.path(".agent-rules")))

    def test_source_path_protection(self):
        center = os.path.join(self.tmp, "center")
        copy_center(center)
        with open(os.path.join(center, "delivery", "manifest.txt"), "a", encoding="utf-8") as f:
            f.write("\n../outside.md .agent-rules/outside.md\n")
        self.assertEqual(self.deliver("--dry-run", center=center).returncode, 1)

    def test_clients(self):
        self.assertEqual(self.deliver("--agent", "claude").returncode, 0)
        self.assertTrue(os.path.isfile(self.path(".claude/commands/check.md")))
        self.assertFalse(os.path.exists(self.path(".kilo")))
        # Клиенты запоминаются в lock.
        self.assertEqual(self.deliver("--check").returncode, 0)
        self.assertEqual(self.deliver("--agent", "kilo", "--agent", "cursor").returncode, 0)
        self.assertTrue(os.path.isfile(self.path(".kilo/command/check.md")))
        self.assertTrue(os.path.isfile(self.path(".cursor/commands/check.md")))
        self.assertFalse(os.path.exists(self.path(".claude/commands/check.md")))

    def test_stale_file_removed_only_if_unmodified(self):
        self.assertEqual(self.deliver().returncode, 0)
        center = os.path.join(self.tmp, "center")
        copy_center(center)
        manifest = os.path.join(center, "delivery", "manifest.txt")
        with open(manifest, "r", encoding="utf-8") as f:
            lines = [l for l in f if ".agent-rules/commands/check.md" not in l]
        with open(manifest, "w", encoding="utf-8", newline="\n") as f:
            f.writelines(lines)

        self.write(".agent-rules/commands/check.md", "локально изменён\n")
        blocked = self.deliver(center=center)
        self.assertEqual(blocked.returncode, 1)
        self.assertTrue(os.path.isfile(self.path(".agent-rules/commands/check.md")))

        self.assertEqual(self.deliver(center=CENTER, ).returncode, 1)  # правка всё ещё блокирует и обычный deliver
        os.remove(self.path(".agent-rules/commands/check.md"))
        self.assertEqual(self.deliver().returncode, 0)  # восстановили из центра
        self.assertEqual(self.deliver(center=center).returncode, 0)
        self.assertFalse(os.path.exists(self.path(".agent-rules/commands")))
        self.assertNotIn(".agent-rules/commands/check.md", json.loads(self.read(".agent-rules.lock"))["managed"])

    def test_refuses_to_deliver_to_center_itself(self):
        result = run([sys.executable, os.path.join(CENTER, "delivery", "deliver.py"), CENTER, "--dry-run"], cwd=self.tmp)
        self.assertEqual(result.returncode, 1)


class ConsumerChecksTests(Base):
    def setUp(self):
        super().setUp()
        self.assertEqual(self.deliver().returncode, 0)

    def test_verify_detects_local_edit(self):
        self.write(".agent-rules/workflow.md", "правка\n")
        result = run(["bash", ".agent-rules/tools/integrity.sh"], cwd=self.service)
        self.assertEqual(result.returncode, 1)
        self.assertIn("изменён локально", result.stderr)

    def test_verify_detects_missing_file(self):
        os.remove(self.path(".agent-rules/tools/contract.sh"))
        result = run(["bash", ".agent-rules/tools/integrity.sh"], cwd=self.service)
        self.assertEqual(result.returncode, 1)
        self.assertIn("отсутствует", result.stderr)

    def test_verify_detects_version_mismatch(self):
        self.write(".agent-rules.version", "9.9.9\n")
        self.assertEqual(run(["bash", ".agent-rules/tools/integrity.sh"], cwd=self.service).returncode, 1)

    @unittest.skipIf(os.name == "nt", "бит исполняемости не проверяется на Windows")
    def test_verify_detects_lost_executable_bit(self):
        os.chmod(self.path(".agent-rules/tools/contract.sh"), 0o644)
        self.assertEqual(run(["bash", ".agent-rules/tools/integrity.sh"], cwd=self.service).returncode, 1)

    def test_unfilled_scaffold_fails(self):
        result = self.check_script()
        self.assertEqual(result.returncode, 1)
        self.assertIn("{{", result.stderr)
        self.assertIn("заглушка", result.stderr)

    def test_stub_gate_fails_even_with_filled_agents(self):
        self.fill_scaffold(gate=self.read("ci/gate.sh"))
        result = self.check_script()
        self.assertEqual(result.returncode, 1)
        self.assertIn("заглушка", result.stderr)

    def test_filled_scaffold_passes(self):
        self.fill_scaffold()
        result = self.check_script()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_failing_gate_propagates(self):
        self.fill_scaffold(gate="#!/usr/bin/env bash\necho gate-failed >&2\nexit 3\n")
        result = self.check_script()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("gate-failed", result.stderr)

    def test_missing_gate_fails(self):
        self.fill_scaffold()
        os.remove(self.path("ci/gate.sh"))
        self.assertNotEqual(self.check_script().returncode, 0)

    def test_contract_requires_workflow_reference(self):
        self.fill_scaffold()
        self.write("AGENTS.md", "# без ссылки\n")
        result = run(["bash", ".agent-rules/tools/contract.sh"], cwd=self.service)
        self.assertEqual(result.returncode, 1)
        self.assertIn("workflow", result.stderr)

    def test_doctor_checks_context_and_docs(self):
        self.fill_scaffold()
        self.write(".agent-rules.json", json.dumps({"schema": 1, "read_first": ["AGENTS.md"], "docs": ["docs/missing.md"]}))
        result = run(["bash", ".agent-rules/tools/contract.sh"], cwd=self.service)
        self.assertEqual(result.returncode, 1)
        self.assertIn("docs/missing.md", result.stderr)

    def test_doctor_rejects_escaping_paths(self):
        self.fill_scaffold()
        self.write(".agent-rules.json", json.dumps({"schema": 1, "read_first": ["../x"], "docs": []}))
        self.assertEqual(run(["bash", ".agent-rules/tools/contract.sh"], cwd=self.service).returncode, 1)


class TemplateTests(unittest.TestCase):
    def test_template_agents_references_workflow(self):
        with open(os.path.join(TEMPLATE, "AGENTS.md"), encoding="utf-8") as f:
            self.assertIn(".agent-rules/workflow.md", f.read())

    def test_every_manifest_source_exists(self):
        sys.path.insert(0, os.path.join(CENTER, "rules", "tools"))
        import core as st
        with open(os.path.join(CENTER, "delivery", "manifest.txt"), encoding="utf-8") as f:
            for line in f:
                line = line.split("#", 1)[0].strip()
                if line:
                    src = line.split()[0]
                    self.assertTrue(os.path.isfile(os.path.join(CENTER, *src.split("/"))), src)


if __name__ == "__main__":
    unittest.main()
