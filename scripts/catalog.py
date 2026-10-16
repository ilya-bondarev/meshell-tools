import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess

from jsonschema import Draft202012Validator, validators, ValidationError

ROOT = Path(__file__).resolve().parents[1]
REPOSITORY = os.environ.get("GITHUB_REPOSITORY", "ilya-bondarev/meshell-tools")
TOOL_FILES = {"module.json", "catalog.json", "README.md", "LICENSE", "CHANGELOG.md"}
# App built-in module IDs; the app also refuses to install a custom module under them.
RESERVED_IDS = {"notes", "device", "mascot", "github"}
# The first MeShell release that reads this index and the permission contract.
MIN_APP_VERSION = "0.10.0"
README_LIMIT = 4000
FILE_LIMIT = 512000
# Catalogue policy on top of the app contract: no fetched or hidden code, no installed binaries.
FORBIDDEN = [
    (re.compile(r"\|\s*(?:sudo\s+|env\s+)*(?:ba|z|da|k|a)?sh\b(?!\s+-c\b)"), "pipes text into a shell"),
    (re.compile(r"\|\s*(?:sudo\s+|env\s+)*(?:python[0-9.]*|perl|ruby|node|php|lua)\s*(?:-\s*)?(?:$|[;&|)])", re.M), "pipes text into an interpreter"),
    (re.compile(r"\beval\b"), "evaluates generated code"),
    (re.compile(r"(?:\bsource\b|(?<![\w/.])\.)\s+<\("), "sources generated code"),
    (re.compile(r"<\(\s*(?:curl|wget)\b|\b(?:ba|z|da|k)?sh\s+(?:-c\s+)?[\"']?\$\(\s*(?:curl|wget)\b"), "runs downloaded code"),
    (re.compile(r"\bbase64\s+(?:-[A-Za-z]*d|--decode)\b"), "decodes hidden content"),
    (re.compile(r"\bchmod\s+(?:[ugoa]*\+[rwX]*x|[0-7]*[1357][0-7]{0,2}\b)"), "makes a file executable"),
    (re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9]{30,}|github_pat_\w{40,}|sk-[A-Za-z0-9_-]{20,}|AKIA[0-9A-Z]{16}|xox[abposr]-[A-Za-z0-9-]{10,}|AIza[0-9A-Za-z_-]{35})"
                r"|-----BEGIN [A-Z ]*PRIVATE KEY-----"), "contains a credential; use env_secrets"),
]


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
    return loads(path.read_text(encoding="utf-8"))


def loads(text):
    return json.loads(text, object_pairs_hook=no_duplicate_keys)


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


def vocabulary(schema):
    return schema["properties"][schema["x-permissions"]]["items"]["enum"]


def needs(value, schema, found):
    if schema.get("x-impliesPermission") and isinstance(value, (dict, list)) and value:
        found.add(schema["x-impliesPermission"])
    if isinstance(value, str):
        for permission, pattern in schema.get("x-permissionPatterns", {}).items():
            if re.search(pattern, value):
                found.add(permission)
    if isinstance(value, dict):
        properties = schema.get("properties", {})
        for key, item in value.items():
            if key in properties:
                needs(item, properties[key], found)
    if isinstance(value, list) and "items" in schema:
        for item in value:
            needs(item, schema["items"], found)


def implied(value, schema):
    """Permissions implied by contract annotations, mirroring ModuleDefinition.required in the app."""
    found = set()
    needs(value, schema, found)
    return [name for name in vocabulary(schema) if name in found]


def permissions(value, schema):
    declared = set(value.get(schema["x-permissions"], []))
    found = set(implied(value, schema)) | declared
    return [name for name in vocabulary(schema) if name in found]


def check_permissions(value, schema):
    missing = [name for name in implied(value, schema) if name not in value.get(schema["x-permissions"], [])]
    if missing:
        raise ValueError("undeclared permissions: " + ", ".join(missing))


def forbidden(value):
    return sorted({f"{action['id']}: {reason}" for action in value.get("actions", [])
                   for pattern, reason in FORBIDDEN if pattern.search(action.get("command", ""))})


def version_key(value):
    return tuple(int(part) for part in value.split("."))


def readme_text(text):
    """README body without its title, bounded for the index."""
    lines = text.strip().splitlines()
    if lines and lines[0].startswith("# "):
        lines = lines[1:]
    body = "\n".join(lines).strip()
    if len(body) > README_LIMIT:
        cut = body.rfind("\n\n", 0, README_LIMIT)
        body = body[:cut if cut > 0 else README_LIMIT].rstrip() + "\n\n…"
    return body


def updated(root, tool):
    try:
        value = subprocess.check_output(
            ["git", "log", "-1", "--format=%cd", "--date=format-local:%Y-%m-%dT%H:%M:%SZ", "--", f"tools/{tool}"],
            cwd=root, text=True, stderr=subprocess.DEVNULL, env={**os.environ, "TZ": "UTC"}).strip()
        return value
    except (OSError, subprocess.CalledProcessError):
        return ""


def schemas(root):
    contract_path = root / "contracts/module.schema.json"
    upstream = load(root / "contracts/UPSTREAM.json")
    if hashlib.sha256(contract_path.read_bytes()).hexdigest() != upstream["sha256"]:
        raise ValueError("contract snapshot hash differs from UPSTREAM.json")
    module_schema = load(contract_path)
    metadata_schema = load(root / "schemas/catalog.schema.json")
    Draft202012Validator.check_schema(module_schema)
    Draft202012Validator.check_schema(metadata_schema)
    return upstream, module_schema, metadata_schema


def tool_entry(root, folder, module_schema, metadata_schema, repository):
    """Validates one tool directory and returns its index entry."""
    name = folder.name
    if not folder.is_dir() or folder.is_symlink():
        raise ValueError(f"invalid tool path: {name}")
    if {item.name for item in folder.iterdir()} != TOOL_FILES:
        raise ValueError(f"unexpected or missing tool files: {name}")
    for item in folder.iterdir():
        if not item.is_file() or item.is_symlink() or item.stat().st_size > FILE_LIMIT:
            raise ValueError(f"unsafe tool file: {name}/{item.name}")
    definition_path = folder / "module.json"
    definition, metadata = load(definition_path), load(folder / "catalog.json")
    check(definition, module_schema)
    check(metadata, metadata_schema)
    if definition["id"] != name:
        raise ValueError(f"ID differs from directory name: {name}")
    if name in RESERVED_IDS:
        raise ValueError(f"ID is an app built-in: {name}")
    if definition != portable(definition, module_schema):
        raise ValueError(f"not a portable export: {name}")
    try:
        check_permissions(definition, module_schema)
    except ValueError as error:
        raise ValueError(f"{name}: {error}") from None
    rejected = forbidden(definition)
    if rejected:
        raise ValueError(f"{name}: " + "; ".join(rejected))
    if version_key(metadata["min_app_version"]) < version_key(MIN_APP_VERSION):
        raise ValueError(f"{name}: min_app_version must be {MIN_APP_VERSION} or later")
    readme = (folder / "README.md").read_text(encoding="utf-8")
    if not readme_text(readme):
        raise ValueError(f"empty README: {name}")
    if (folder / "LICENSE").read_bytes() != (root / "LICENSE").read_bytes():
        raise ValueError(f"tool license must match MIT-0: {name}")
    if not re.search(rf"^## {re.escape(metadata['version'])}\s*$", (folder / "CHANGELOG.md").read_text(encoding="utf-8"), re.M):
        raise ValueError(f"CHANGELOG.md has no '## {metadata['version']}' section: {name}")
    data = definition_path.read_bytes()
    entry = {"id": name, "title": definition["title"], "description": definition.get("description", ""), **metadata}
    entry.update({
        "permissions": permissions(definition, module_schema),
        "packages": definition.get("packages", []),
        "actions": [{"id": action["id"], "label": action.get("label") or action["id"]} for action in definition["actions"]],
        "size": len(data),
        "sha256": hashlib.sha256(data).hexdigest(),
        "definition": definition_path.relative_to(root).as_posix(),
        "download": release_asset(repository, name, metadata["version"]),
        "updated": updated(root, name),
        "readme": readme_text(readme),
    })
    return entry


def release_asset(repository, tool, version):
    """GitHub counts downloads of release assets, so installs use this URL."""
    return f"https://github.com/{repository}/releases/download/{tool}@{version}/module.json"


def build_catalog(root, commit, repository=REPOSITORY):
    upstream, module_schema, metadata_schema = schemas(root)
    entries = [tool_entry(root, folder, module_schema, metadata_schema, repository)
               for folder in sorted((root / "tools").iterdir())]
    return {"format": 2, "repository": repository, "commit": commit, "module_contract": upstream, "tools": entries}


def git(root, *args):
    return subprocess.run(["git", *args], cwd=root, capture_output=True, check=False)


def review_changes(root, base, author, maintainer):
    """Pull request rules: authors change only their own tool directories and bump the version with the commands."""
    result = git(root, "diff", "--name-only", base, "HEAD")
    if result.returncode:
        raise ValueError("cannot compare with the base revision")
    paths = [line for line in result.stdout.decode().splitlines() if line]
    privileged = author.lower() == maintainer.lower()
    errors = []
    outside = [path for path in paths if not path.startswith("tools/")]
    if outside and not privileged:
        errors.append("only tools/<id>/ may change in a contribution: " + ", ".join(outside[:10]))
    for tool in sorted({path.split("/")[1] for path in paths if path.startswith("tools/") and path.count("/") >= 2}):
        old = git(root, "show", f"{base}:tools/{tool}/catalog.json")
        before = loads(old.stdout.decode()) if old.returncode == 0 else None
        folder = root / "tools" / tool
        if not folder.is_dir():
            if not privileged and (before is None or before["github"].lower() != author.lower()):
                errors.append(f"tools/{tool}: only its author or the maintainer removes it")
            continue
        after = load(folder / "catalog.json")
        owner = (before or after)["github"]
        if not privileged and owner.lower() != author.lower():
            errors.append(f"tools/{tool} belongs to @{owner}; open an issue or a PR from that account")
        if before is None:
            continue
        if after["github"] != before["github"] and not privileged:
            errors.append(f"tools/{tool}: only the maintainer transfers ownership")
        if version_key(after["version"]) < version_key(before["version"]):
            errors.append(f"tools/{tool}: version decreased")
        old_module = git(root, "show", f"{base}:tools/{tool}/module.json")
        if old_module.returncode == 0 and old_module.stdout != (folder / "module.json").read_bytes() \
                and version_key(after["version"]) <= version_key(before["version"]):
            errors.append(f"tools/{tool}: module.json changed, increase the version")
    if errors:
        raise ValueError("\n".join(errors))
    return paths


def source_commit(root):
    return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip()


def write_site(result, root, output):
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    for entry in result["tools"]:
        target = output.parent / entry["definition"]
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes((root / entry["definition"]).read_bytes())


def main():
    parser = argparse.ArgumentParser(description="Validate portable modules; never execute their commands.")
    parser.add_argument("--root", type=Path, default=ROOT, help="catalogue checkout to validate")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--base", help="pull request base revision")
    parser.add_argument("--pr-author", help="pull request author login")
    parser.add_argument("--maintainer", default=REPOSITORY.split("/")[0])
    args = parser.parse_args()
    root = args.root.resolve()
    result = build_catalog(root, source_commit(root))
    if args.base and args.pr_author:
        review_changes(root, args.base, args.pr_author, args.maintainer)
    if args.output:
        write_site(result, root, args.output)
    print(f"CATALOG_OK {len(result['tools'])}")


if __name__ == "__main__":
    main()
