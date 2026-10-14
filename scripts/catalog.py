import argparse
import hashlib
import json
from pathlib import Path
import subprocess

from jsonschema import Draft202012Validator, validators, ValidationError

ROOT = Path(__file__).resolve().parents[1]


def unique_by(validator, field, instance, schema):
    if not isinstance(instance, list):
        return
    seen = set()
    for item in instance:
        if not isinstance(item, dict) or field not in item:
            continue
        key = item[field]
        if not isinstance(key, str):
            continue
        if key in seen:
            yield ValidationError(f"duplicate {field}: {key}")
        seen.add(key)


ContractValidator = validators.extend(Draft202012Validator, {"x-uniqueBy": unique_by})


def no_duplicate_keys(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def load(path):
    return json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=no_duplicate_keys)


def check(value, schema):
    ContractValidator(schema).validate(value)
    if "x-maxJsonCharacters" in schema:
        compact = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
        if len(compact.encode("utf-16-le")) // 2 > schema["x-maxJsonCharacters"]:
            raise ValueError("definition exceeds the app's compact JSON limit")


def portable(value, schema):
    if isinstance(value, dict):
        if schema.get("x-portableAliases"):
            return {key: key for key in value}
        properties = schema.get("properties", {})
        return {key: portable(item, properties[key]) for key, item in value.items()
                if key in properties and not properties[key].get("x-local")}
    if isinstance(value, list):
        return [portable(item, schema["items"]) for item in value]
    return value


def build_catalog(root, commit):
    contract_path = root / "contracts/module.schema.json"
    upstream = load(root / "contracts/UPSTREAM.json")
    if hashlib.sha256(contract_path.read_bytes()).hexdigest() != upstream["sha256"]:
        raise ValueError("contract snapshot hash differs from UPSTREAM.json")
    module_schema = load(contract_path)
    metadata_schema = load(root / "schemas/catalog.schema.json")
    Draft202012Validator.check_schema(module_schema)
    Draft202012Validator.check_schema(metadata_schema)
    entries = []
    for folder in sorted((root / "tools").iterdir()):
        if not folder.is_dir() or folder.is_symlink():
            raise ValueError(f"invalid tool path: {folder.name}")
        allowed = {"module.json", "catalog.json", "README.md", "LICENSE", "CHANGELOG.md"}
        if {item.name for item in folder.iterdir()} != allowed:
            raise ValueError(f"unexpected or missing tool files: {folder.name}")
        for item in folder.iterdir():
            if not item.is_file() or item.is_symlink() or item.stat().st_size > 512000:
                raise ValueError(f"unsafe tool file: {folder.name}/{item.name}")
        definition_path = folder / "module.json"
        definition, metadata = load(definition_path), load(folder / "catalog.json")
        check(definition, module_schema)
        check(metadata, metadata_schema)
        if definition["id"] != folder.name:
            raise ValueError(f"ID differs from directory name: {folder.name}")
        if definition != portable(definition, module_schema):
            raise ValueError(f"not a portable export: {folder.name}")
        if not (folder / "README.md").read_text(encoding="utf-8").strip():
            raise ValueError(f"empty README: {folder.name}")
        if (folder / "LICENSE").read_bytes() != (root / "LICENSE").read_bytes():
            raise ValueError(f"tool license must match MIT-0: {folder.name}")
        entries.append({"id": definition["id"], "title": definition["title"], **metadata,
                        "definition": definition_path.relative_to(root).as_posix(),
                        "sha256": hashlib.sha256(definition_path.read_bytes()).hexdigest()})
    return {"format": 1, "commit": commit, "module_contract": upstream, "tools": entries}


def source_commit(root):
    return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip()


def main():
    parser = argparse.ArgumentParser(description="Validate portable modules; never execute their commands.")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = build_catalog(ROOT, source_commit(ROOT))
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        for entry in result["tools"]:
            target = args.output.parent / entry["definition"]
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes((ROOT / entry["definition"]).read_bytes())
    print(f"CATALOG_OK {len(result['tools'])}")


if __name__ == "__main__":
    main()
