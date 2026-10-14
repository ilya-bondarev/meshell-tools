import copy
import json
import unittest

from jsonschema import ValidationError
from catalog import ROOT, build_catalog, check, load, no_duplicate_keys, portable


class CatalogTests(unittest.TestCase):
    def test_example_and_index(self):
        result = build_catalog(ROOT, "local-test")
        self.assertEqual(result["tools"][0]["id"], "system-status")
        self.assertEqual(result["commit"], "local-test")

    def test_duplicate_identity_and_unknown_field(self):
        schema = load(ROOT / "contracts/module.schema.json")
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
        schema = load(ROOT / "contracts/module.schema.json")
        value = load(ROOT / "tools/system-status/module.json")
        value["actions"][0].update(cwd="/private/workspace", env_secrets={"TOKEN": "private-alias"})
        result = portable(value, schema)
        self.assertNotIn("cwd", result["actions"][0])
        self.assertEqual(result["actions"][0]["env_secrets"], {"TOKEN": "TOKEN"})
        check(result, schema)


if __name__ == "__main__":
    unittest.main()
