"""Exercise agent setup through a fake CLI; never access an operator's state."""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = next(ROOT / "scripts" / name for name in (
    "configure_inference_agents.sh", "configure-oda-dinner-agent.sh"
) if (ROOT / "scripts" / name).exists())
TARGETS = (["familybot-briefing", "familybot-ukeplan"]
           if SCRIPT.name == "configure_inference_agents.sh" else ["familybot-oda-dinner"])

FAKE = r'''
import json, os, sys
from pathlib import Path
root=Path(os.environ["AGENT_TEST_DIR"])
args=sys.argv[1:]
with (root/"calls").open("a") as f:
    f.write(json.dumps(args)+"\n")
mode=os.environ["AGENT_TEST_MODE"]
state=json.loads((root/"state").read_text())
if args[:2]==["agents","list"]:
    if mode=="failed-list": sys.exit(7)
    if mode=="invalid-list": print("{}")
    else: print(json.dumps([{"id":x} for x in state]))
elif args[:2]==["agents","add"]:
    state.append(args[2])
    (root/"state").write_text(json.dumps(state))
    print("{}")
elif args[:2]==["config","get"]:
    assert args[2]=="agents"
    if mode=="invalid-config": print("{")
    elif mode=="missing-target": print(json.dumps({"entries": {"main": {}}}))
    elif mode=="mixed-invalid": print(json.dumps({"entries": None, "list": [{"id":x} for x in state]}))
    elif mode=="list": print(json.dumps({"list": [{"id":x} for x in state]}))
    elif mode=="duplicate": print(json.dumps({"list": [{"id":state[1]}, {"id":state[1]}]}))
    else: print(json.dumps({"entries": {x:{} for x in state}}))
elif args[:2]==["config","set"]:
    json.loads(args[3])
elif args!=["config","validate"]:
    sys.exit(8)
'''


class AgentSetupTests(unittest.TestCase):
    def run_setup(self, mode="entries", *, initial=None, extra=None, repeats=1):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "state").write_text(json.dumps(initial if initial is not None else ["main", *TARGETS]))
            cli = root / "openclaw"
            cli.write_text("#!" + sys.executable + "\n" + FAKE)
            cli.chmod(0o700)
            # Do not change HOME or create real agent directories.
            install = root / "install"
            install.write_text("#!/bin/sh\nexit 0\n")
            install.chmod(0o700)
            env = {**os.environ, "FAMILYBOT_OPENCLAW": str(cli),
                   "AGENT_TEST_DIR": directory, "AGENT_TEST_MODE": mode,
                   "PATH": directory + os.pathsep + os.environ.get("PATH", "")}
            for key in ("FAMILYBOT_BRIEFING_AGENT", "FAMILYBOT_UKEPLAN_AGENT",
                        "FAMILYBOT_ODA_DINNER_AGENT", "FAMILYBOT_BRIEFING_MODEL",
                        "FAMILYBOT_UKEPLAN_MODEL", "FAMILYBOT_ODA_DINNER_MODEL"):
                env.pop(key, None)
            env.update(extra or {})
            for _ in range(repeats):
                result = subprocess.run(["/bin/bash", str(SCRIPT)], env=env,
                                        capture_output=True, text=True, timeout=30, check=False)
                if result.returncode:
                    break
            calls = [json.loads(line) for line in (root / "calls").read_text().splitlines()] if (root / "calls").exists() else []
            return result, calls

    def test_both_rosters_preserve_tool_free_policy(self):
        for mode in ("entries", "list"):
            with self.subTest(mode=mode):
                result, calls = self.run_setup(mode)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertFalse(any(c[:2] == ["agents", "add"] for c in calls))
                writes = [c for c in calls if c[:2] == ["config", "set"]]
                for index, target in enumerate(TARGETS, 1):
                    prefix = "agents.entries." + target if mode == "entries" else f"agents.list[{index}]"
                    values = {c[2]: json.loads(c[3]) for c in writes}
                    self.assertEqual(values[prefix + ".tools.profile"], "minimal")
                    self.assertEqual(values[prefix + ".tools.allow"], [])
                    self.assertEqual(values[prefix + ".skills"], [])
                    self.assertFalse(values[prefix + ".tools.elevated.enabled"])
                    for tool in ("*", "group:fs", "group:runtime", "group:agents", "session_status"):
                        self.assertIn(tool, values[prefix + ".tools.deny"])
                self.assertTrue(all(not c[2].startswith("agents.entries.main.") for c in writes))

    def test_unreadable_or_ambiguous_roster_does_not_mutate(self):
        for mode in ("failed-list", "invalid-list", "invalid-config",
                     "missing-target", "mixed-invalid", "duplicate"):
            with self.subTest(mode=mode):
                result, calls = self.run_setup(mode)
                self.assertNotEqual(result.returncode, 0)
                self.assertFalse(any(c[:2] in (["agents", "add"], ["config", "set"]) for c in calls))

    def test_create_then_reconcile_is_repeatable(self):
        result, calls = self.run_setup(initial=["main"], repeats=2)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual([c[2] for c in calls if c[:2] == ["agents", "add"]], TARGETS)

    def test_invalid_identifiers_fail_before_cli(self):
        for key, value in (("AGENT", "../main"), ("MODEL", 'bad"model')):
            variable = ("FAMILYBOT_BRIEFING_" if len(TARGETS) == 2 else "FAMILYBOT_ODA_DINNER_") + key
            result, calls = self.run_setup(extra={variable: value})
            self.assertEqual(result.returncode, 64)
            self.assertEqual(calls, [])


if __name__ == "__main__":
    unittest.main()
