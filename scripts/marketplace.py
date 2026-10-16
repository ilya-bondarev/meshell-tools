"""Catalogue marketplace: releases, statistics, issue triage and the static site.

Issue content is untrusted data: it is parsed here and never reaches a shell. Module commands are never executed.
"""
import argparse
from datetime import datetime, timezone
import html
import json
import os
from pathlib import Path
import re
import shutil
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request

import catalog

API = "https://api.github.com"
UPLOADS = "https://uploads.github.com"
TERMUX = "https://packages.termux.dev/apt/termux-main/dists/stable/main/binary-aarch64/Packages"
APP = "https://github.com/ilya-bondarev/meshell"
MARK = "<!-- meshell-catalogue -->"
REVIEWS = 10
REVIEW_LIMIT = 500
REQUESTS = 20
LABELS = {
    "rating": ("f2c94c", "Module rating"),
    "submission": ("2f9e44", "Module submission"),
    "approved": ("1d76db", "Maintainer approved the submission"),
    "invalid": ("b60205", "Needs changes"),
    "request": ("a371f7", "Wanted module"),
    "report": ("d93f0b", "Problem with a module"),
    "spam": ("000000", "Ignored by the catalogue"),
}
KINDS = ("rating", "submit", "request", "report")
MAINTAINER_ROLES = {"admin", "maintain", "write"}


class GitHubError(Exception):
    def __init__(self, status, message):
        super().__init__(f"GitHub {status}: {message}")
        self.status = status


class GitHub:
    def __init__(self, repository, token):
        self.repository, self.token = repository, token

    def call(self, method, path, body=None, raw=None, content_type="application/json"):
        url = path if path.startswith("https://") else API + path
        data = raw if raw is not None else (json.dumps(body).encode() if body is not None else None)
        headers = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28",
                   "User-Agent": "meshell-tools", "Authorization": f"Bearer {self.token}"}
        if data is not None:
            headers["Content-Type"] = content_type
        for attempt in range(4):
            try:
                with urllib.request.urlopen(urllib.request.Request(url, data=data, method=method, headers=headers), timeout=60) as response:
                    payload = response.read()
                    return json.loads(payload) if payload else None
            except urllib.error.HTTPError as error:
                text = error.read().decode("utf-8", "replace")[:500]
                retry = error.code >= 500 or (error.code in (403, 429) and "rate limit" in text.lower())
                if retry and attempt < 3:
                    time.sleep(5 * 2 ** attempt)
                    continue
                raise GitHubError(error.code, text) from None
            except urllib.error.URLError:
                if attempt < 3:
                    time.sleep(5 * 2 ** attempt)
                    continue
                raise

    def pages(self, path):
        separator = "&" if "?" in path else "?"
        page = 1
        while True:
            items = self.call("GET", f"{path}{separator}per_page=100&page={page}")
            yield from items
            if len(items) < 100:
                return
            page += 1

    def repo(self, path=""):
        return f"/repos/{self.repository}{path}"

    def ensure_labels(self):
        existing = {label["name"] for label in self.pages(self.repo("/labels"))}
        for name, (color, description) in LABELS.items():
            if name not in existing:
                self.call("POST", self.repo("/labels"), {"name": name, "color": color, "description": description})

    def label(self, number, *names):
        self.call("POST", self.repo(f"/issues/{number}/labels"), {"labels": list(names)})

    def unlabel(self, number, name):
        try:
            self.call("DELETE", self.repo(f"/issues/{number}/labels/{urllib.parse.quote(name)}"))
        except GitHubError as error:
            if error.status != 404:
                raise

    def comment(self, number, text):
        """One catalogue comment per issue, updated in place."""
        body = MARK + "\n" + text
        for item in self.pages(self.repo(f"/issues/{number}/comments")):
            if MARK in (item.get("body") or "") and item["user"].get("type") == "Bot":
                self.call("PATCH", self.repo(f"/issues/comments/{item['id']}"), {"body": body})
                return
        self.call("POST", self.repo(f"/issues/{number}/comments"), {"body": body})

    def close(self, number, reason="completed"):
        self.call("PATCH", self.repo(f"/issues/{number}"), {"state": "closed", "state_reason": reason})

    def permission(self, login):
        try:
            return self.call("GET", self.repo(f"/collaborators/{urllib.parse.quote(login)}/permission"))["permission"]
        except GitHubError as error:
            if error.status == 404:
                return "none"
            raise

    def display_name(self, login):
        try:
            return (self.call("GET", f"/users/{urllib.parse.quote(login)}").get("name") or login).strip()[:100] or login
        except GitHubError:
            return login

    def dispatch(self, workflow="publish.yml"):
        branch = self.call("GET", self.repo())["default_branch"]
        self.call("POST", self.repo(f"/actions/workflows/{workflow}/dispatches"), {"ref": branch})

    def commit(self, files, message):
        """Commits text files on the default branch through the Git data API; fails instead of overwriting a newer head."""
        branch = self.call("GET", self.repo())["default_branch"]
        head = self.call("GET", self.repo(f"/git/ref/heads/{branch}"))["object"]["sha"]
        tree = self.call("GET", self.repo(f"/git/commits/{head}"))["tree"]["sha"]
        entries = [{"path": path, "mode": "100644", "type": "blob", "content": text} for path, text in sorted(files.items())]
        tree = self.call("POST", self.repo("/git/trees"), {"base_tree": tree, "tree": entries})["sha"]
        sha = self.call("POST", self.repo("/git/commits"), {"message": message, "tree": tree, "parents": [head]})["sha"]
        self.call("PATCH", self.repo(f"/git/refs/heads/{branch}"), {"sha": sha, "force": False})
        return sha


# Issue protocol, written by MeShell's MarketRules and by people on GitHub.

def issue_kind(title):
    match = re.match(r"^\s*\[(rating|submit|request|report)\]\s*(.*?)\s*$", title or "", re.I | re.S)
    return (match.group(1).lower(), match.group(2)) if match else (None, "")


def parse_rating(title, body):
    """{"id", "version", "stars", "text"} from a `[rating] <id>` issue, or None."""
    kind, subject = issue_kind(title)
    if kind != "rating" or not re.fullmatch(r"[a-z0-9_-]{1,40}", subject):
        return None
    fields, rest, lines = {}, [], (body or "").replace("\r\n", "\n").split("\n")
    for number, line in enumerate(lines):
        match = re.match(r"^\s*(Module|Version|Rating)\s*:\s*(.*?)\s*$", line, re.I)
        if match:
            fields[match.group(1).lower()] = match.group(2)
        elif line.strip() and fields:
            rest = lines[number:]
            break
    stars = re.fullmatch(r"([1-5])(?:\s*/\s*5)?|([★☆]{5})", fields.get("rating", ""))
    if not stars or fields.get("module", subject) != subject:
        return None
    count = int(stars.group(1)) if stars.group(1) else stars.group(2).count("★")
    if not 1 <= count <= 5:
        return None
    text = re.sub(r"<!--.*?-->", "", "\n".join(rest), flags=re.S).strip()
    version = fields.get("version", "")
    return {"id": subject, "version": version if re.fullmatch(r"[0-9]{1,6}\.[0-9]{1,6}\.[0-9]{1,6}", version) else "",
            "stars": count, "text": text}


def counted(issue, vote, owners):
    labels = {label["name"] for label in issue.get("labels", [])}
    login = issue["user"]["login"]
    return vote is not None and vote["id"] in owners and not labels & {"spam", "invalid"} \
        and issue["user"].get("type") != "Bot" and login.lower() != owners[vote["id"]].lower()


def aggregate(issues, owners):
    """Ratings per module: one vote per account (its latest), none from bots, the module author or flagged issues."""
    votes = {}
    for issue in sorted((item for item in issues if "pull_request" not in item), key=lambda item: item["created_at"]):
        vote = parse_rating(issue["title"], issue.get("body"))
        if counted(issue, vote, owners):
            votes[(vote["id"], issue["user"]["login"].lower())] = (issue, vote)
    result = {tool: {"rating": 0, "votes": 0, "histogram": [0] * 5, "reviews": []} for tool in owners}
    for (tool, _), (issue, vote) in votes.items():
        item = result[tool]
        item["histogram"][vote["stars"] - 1] += 1
        item["votes"] += 1
        if vote["text"]:
            item["reviews"].append({"login": issue["user"]["login"], "rating": vote["stars"], "version": vote["version"],
                                    "date": issue["created_at"], "text": vote["text"][:REVIEW_LIMIT], "url": issue["html_url"]})
    for item in result.values():
        if item["votes"]:
            item["rating"] = round(sum((stars + 1) * count for stars, count in enumerate(item["histogram"])) / item["votes"], 2)
        item["reviews"] = sorted(item["reviews"], key=lambda review: review["date"], reverse=True)[:REVIEWS]
    return result


def wanted(issues):
    """Open module requests, most voted first: the list authors build from."""
    result = []
    for issue in issues:
        kind, subject = issue_kind(issue["title"])
        labels = {label["name"] for label in issue.get("labels", [])}
        if kind == "request" and issue["state"] == "open" and "pull_request" not in issue and not labels & {"spam", "invalid"} and subject:
            result.append({"number": issue["number"], "title": subject[:120], "votes": issue.get("reactions", {}).get("+1", 0),
                           "url": issue["html_url"], "date": issue["created_at"]})
    return sorted(result, key=lambda item: (-item["votes"], item["date"]))[:REQUESTS]


def downloads(releases):
    """Counted downloads of every release asset named module.json, per module ID."""
    result = {}
    for release in releases:
        tool, _, version = release["tag_name"].rpartition("@")
        if tool and version:
            result[tool] = result.get(tool, 0) + sum(asset["download_count"] for asset in release.get("assets", []) if asset["name"] == "module.json")
    return result


def termux_index(text):
    packages = {}
    for block in text.replace("\r\n", "\n").split("\n\n"):
        fields = dict(line.split(": ", 1) for line in block.split("\n") if ": " in line and not line.startswith(" "))
        if "Package" in fields:
            depends = ",".join(fields.get(key, "") for key in ("Depends", "Pre-Depends"))
            names = [re.split(r"[\s(]", part.split("|")[0].strip())[0] for part in depends.split(",") if part.strip()]
            packages[fields["Package"]] = (int(fields.get("Size", "0") or 0), names)
    return packages


def closure_size(names, packages):
    """Download size of the packages and their dependencies: the most a first run fetches."""
    seen, pending, total = set(), list(names), 0
    while pending:
        name = pending.pop()
        if name in seen or name not in packages:
            continue
        seen.add(name)
        size, depends = packages[name]
        total += size
        pending.extend(depends)
    return total


def stats(gh, index, termux_text=None):
    owners = {tool["id"]: tool["github"] for tool in index["tools"]}
    issues = list(gh.pages(gh.repo("/issues?state=all&sort=created&direction=asc")))
    counts = downloads(gh.pages(gh.repo("/releases")))
    ratings = aggregate(issues, owners)
    packages = termux_index(termux_text) if termux_text else {}
    tools = {}
    for tool in index["tools"]:
        tools[tool["id"]] = {"downloads": counts.get(tool["id"], 0), **ratings[tool["id"]],
                             "packages_size": closure_size(tool["packages"], packages)}
    return {"format": 1, "generated": now(), "tools": tools, "requests": wanted(issues)}


def now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# Releases: the counted, immutable download of each module version.

def changelog_section(text, version):
    match = re.search(rf"^## {re.escape(version)}\s*\n(.*?)(?=^## |\Z)", text, re.M | re.S)
    return match.group(1).strip() if match else ""


def release_notes(root, tool):
    permissions = ", ".join(tool["permissions"]) or "none"
    changes = changelog_section((root / "tools" / tool["id"] / "CHANGELOG.md").read_text(encoding="utf-8"), tool["version"])
    return (f"**{tool['title']}** {tool['version']} by @{tool['github']}\n\n{tool['description']}\n\n"
            f"Install in MeShell: **Modules → Catalogue**. Permissions: {permissions}.\n\n"
            + (f"### Changes\n\n{changes}\n\n" if changes else "")
            + f"SHA-256 of module.json: `{tool['sha256']}`\n")


def publish(gh, root, index):
    releases = {release["tag_name"]: release for release in gh.pages(gh.repo("/releases"))}
    created = []
    for tool in index["tools"]:
        tag = f"{tool['id']}@{tool['version']}"
        release = releases.get(tag)
        if release is None:
            release = gh.call("POST", gh.repo("/releases"), {
                "tag_name": tag, "target_commitish": index["commit"], "name": f"{tool['title']} {tool['version']}",
                "body": release_notes(root, tool), "make_latest": "false"})
        assets = [asset for asset in release.get("assets", []) if asset["name"] == "module.json"]
        if not assets:
            gh.call("POST", f"{UPLOADS}/repos/{gh.repository}/releases/{release['id']}/assets?name=module.json",
                    raw=(root / tool["definition"]).read_bytes(), content_type="application/json")
            created.append(tag)
            continue
        digest = assets[0].get("digest") or ""
        published = digest.split(":", 1)[1] if digest.startswith("sha256:") else None
        if published is None:
            match = re.search(r"SHA-256 of module.json: `([0-9a-f]{64})`", release.get("body") or "")
            published = match.group(1) if match else None
        if published != tool["sha256"] and not (published is None and assets[0]["size"] == tool["size"]):
            raise ValueError(f"{tag}: module.json differs from the published release; increase the version")
    return created


# Submissions: an issue carrying a portable export, reviewed and approved by a maintainer.

def parse_submission(body):
    match = re.search(r"```json[^\n]*\n(.*?)\n```", (body or "").replace("\r\n", "\n"), re.S)
    if not match:
        raise ValueError("no ```json block with the submission")
    try:
        data = catalog.loads(match.group(1))
    except ValueError as error:
        raise ValueError(f"the JSON block is not valid JSON: {error}") from None
    if not isinstance(data, dict) or data.get("format") != 1 or not isinstance(data.get("module"), dict) or not isinstance(data.get("catalog"), dict):
        raise ValueError("the JSON block needs format 1 with module and catalog objects")
    return data


def prepare(root, issue, data, tools, author_name, maintainer):
    """Tool files for a submission, its index entry and the problems that block publishing."""
    module, metadata, login = data["module"], data["catalog"], issue["user"]["login"]
    tool = module.get("id") if isinstance(module.get("id"), str) else ""
    existing = tools.get(tool)
    problems = []
    _, subject = issue_kind(issue["title"])
    if subject and subject != tool:
        problems.append(f"the title names `{subject}` but the module ID is `{tool}`")
    privileged = login.lower() == maintainer.lower()
    if existing and existing["github"].lower() != login.lower() and not privileged:
        problems.append(f"`{tool}` belongs to @{existing['github']}; choose another module ID")
    version = metadata.get("version") if isinstance(metadata.get("version"), str) else ""
    if existing and re.fullmatch(r"[0-9]{1,6}\.[0-9]{1,6}\.[0-9]{1,6}", version) \
            and catalog.version_key(version) <= catalog.version_key(existing["version"]):
        problems.append(f"version {version} must be newer than the published {existing['version']}")
    previous = (root / "tools" / tool) if existing else None
    keep = catalog.load(previous / "catalog.json") if previous else {}
    entry_meta = {
        "version": version,
        "author": keep["author"] if keep and (privileged or keep["github"].lower() == login.lower()) else author_name,
        "github": keep.get("github", login) if privileged and keep else login,
        "license": metadata.get("license"),
        "min_app_version": max(keep.get("min_app_version", catalog.MIN_APP_VERSION), catalog.MIN_APP_VERSION, key=catalog.version_key),
        "category": metadata.get("category"),
        "requirements": metadata.get("requirements", keep.get("requirements", ["MeShell ADB-shell broker"])),
    }
    for key in ("icon", "translations"):
        if key in metadata or key in keep:
            entry_meta[key] = metadata.get(key, keep.get(key))
    readme = data.get("readme") if isinstance(data.get("readme"), str) else ""
    title = module.get("title") if isinstance(module.get("title"), str) else tool
    changes = data.get("changes") if isinstance(data.get("changes"), str) and data["changes"].strip() else \
        (f"Submitted in #{issue['number']}." if existing else "Initial version.")
    history = (previous / "CHANGELOG.md").read_text(encoding="utf-8") if previous else "# Changes\n"
    head, _, tail = history.partition("\n")
    files = {
        "module.json": json.dumps(module, ensure_ascii=False, indent=2) + "\n",
        "catalog.json": json.dumps(entry_meta, ensure_ascii=False, indent=2) + "\n",
        "README.md": f"# {title.strip()}\n\n{readme.strip() or module.get('description', title)}\n",
        "CHANGELOG.md": f"{head}\n\n## {version}\n\n{changes.strip()}\n{tail}".rstrip("\n") + "\n",
        "LICENSE": (root / "LICENSE").read_text(encoding="utf-8"),
    }
    entry = None
    if not re.fullmatch(r"[a-z0-9_-]{1,40}", tool):
        problems.append("the module ID must be 1-40 characters of a-z, 0-9, _ and -")
    else:
        _, module_schema, metadata_schema = catalog.schemas(root)
        with tempfile.TemporaryDirectory() as temporary:
            scratch = Path(temporary)
            shutil.copyfile(root / "LICENSE", scratch / "LICENSE")
            folder = scratch / "tools" / tool
            folder.mkdir(parents=True)
            for name, text in files.items():
                (folder / name).write_bytes(text.encode("utf-8"))
            try:
                entry = catalog.tool_entry(scratch, folder, module_schema, metadata_schema, gh_repository())
            except (ValueError, catalog.ValidationError) as error:
                problems.append(describe(error))
    return {"id": tool, "files": {f"tools/{tool}/{name}": text for name, text in files.items()}, "entry": entry,
            "problems": problems, "update": bool(existing)}


def describe(error):
    if isinstance(error, catalog.ValidationError):
        where = "/".join(str(part) for part in error.absolute_path)
        return f"{where or 'definition'}: {error.message}"
    return str(error)


def gh_repository():
    return os.environ.get("GITHUB_REPOSITORY", catalog.REPOSITORY)


def cell(value):
    return str(value).replace("\\", "\\\\").replace("|", "\\|").replace("\n", " ").replace("@", "@\u200b")


def fenced(text, language="sh"):
    longest = max((len(run) for run in re.findall(r"`+", text)), default=0)
    fence = "`" * max(3, longest + 1)
    return f"{fence}{language}\n{text}\n{fence}"


def report(issue, prepared):
    entry, problems = prepared["entry"], prepared["problems"]
    module = catalog.loads(prepared["files"][f"tools/{prepared['id']}/module.json"]) if prepared["id"] else {}
    lines = ["### " + ("❌ Needs changes" if problems else "✅ Ready for review"), ""]
    if problems:
        lines += [f"- {cell(problem)}" for problem in problems] + ["", "Edit this issue to fix the submission; this report updates automatically.", ""]
    if entry:
        lines += ["| | |", "|---|---|",
                  f"| Module | **{cell(entry['title'])}** `{entry['id']}` {entry['version']} ({'update' if prepared['update'] else 'new'}) |",
                  f"| Author | @{issue['user']['login']} |",
                  f"| Category | {entry['category']} |",
                  f"| Permissions | {', '.join(entry['permissions']) or 'none'} |",
                  f"| Packages | {', '.join(entry['packages']) or 'none'} |",
                  f"| Size | {entry['size']} bytes, SHA-256 `{entry['sha256'][:16]}` |", ""]
    for action in module.get("actions", []) if isinstance(module.get("actions"), list) else []:
        if isinstance(action, dict) and isinstance(action.get("command"), str):
            lines += [f"**{cell(action.get('label') or action.get('id'))}** `{cell(action.get('id'))}`", "", fenced(action["command"]), ""]
    readme = prepared["files"].get(f"tools/{prepared['id']}/README.md", "")
    lines += ["<details><summary>README.md</summary>", "", fenced(readme.strip(), "markdown"), "", "</details>", ""]
    if not problems:
        lines += ["Maintainers: read every command, then add the `approved` label to publish. Editing the submission updates this report."]
    return "\n".join(lines)


# Triage of issues opened from MeShell or on GitHub.

def triage(gh, event, root):
    issue, action = event.get("issue"), event.get("action")
    if not issue or "pull_request" in issue or issue["user"].get("type") == "Bot":
        return False
    kind, _ = issue_kind(issue["title"])
    labels = {label["name"] for label in issue.get("labels", [])}
    if kind is None or "spam" in labels:
        return False
    gh.ensure_labels()
    index = catalog.build_catalog(root, "triage", gh.repository)
    tools = {tool["id"]: tool for tool in index["tools"]}
    maintainer = gh.repository.split("/")[0]
    if action == "labeled":
        if event.get("label", {}).get("name") == "approved" and kind == "submit":
            return approve(gh, event, issue, root, tools, maintainer)
        return False
    if action not in ("opened", "edited", "reopened"):
        return False
    if kind == "rating":
        return rating(gh, issue, tools)
    if kind == "submit":
        submission(gh, issue, root, tools, maintainer)
        return False
    if action == "opened":
        if kind == "request":
            gh.label(issue["number"], "request")
            gh.comment(issue["number"], "Thanks! This request is listed for module authors in the catalogue; 👍 it to vote.\n\n"
                       "Anyone can build it: describe the module in MeShell (**Modules → + → Create with GPT**), "
                       "then long-press it → **Publish to catalogue**. Rules: [CONTRIBUTING.md](../blob/main/CONTRIBUTING.md).")
        else:
            gh.label(issue["number"], "report")
            gh.comment(issue["number"], "Thanks for the report. A maintainer reviews it; harmful modules are removed from the catalogue.")
    return False


def rating(gh, issue, tools):
    vote, login, number = parse_rating(issue["title"], issue.get("body")), issue["user"]["login"], issue["number"]
    problem = None
    if vote is None:
        problem = "A rating needs the module ID in the title, `[rating] <module-id>`, and a `Rating: N/5` line with N from 1 to 5."
    elif vote["id"] not in tools:
        problem = f"There is no `{vote['id']}` module in the catalogue."
    elif tools[vote["id"]]["github"].lower() == login.lower():
        problem = "Authors' ratings of their own modules do not count."
    if problem:
        gh.label(number, "invalid")
        gh.comment(number, problem + " Edit this issue to fix it.")
        if issue["state"] == "open":
            gh.close(number, "not_planned")
        return False
    gh.unlabel(number, "invalid")
    gh.label(number, "rating")
    stars = "★" * vote["stars"] + "☆" * (5 - vote["stars"])
    gh.comment(number, f"Thanks, @{login}! {stars} for **{cell(tools[vote['id']]['title'])}** appears in the catalogue within the hour. "
               "Only your latest rating of a module counts; edit this issue to change it.")
    if issue["state"] == "open":
        gh.close(number)
    return True


def evaluate(gh, issue, root, tools, maintainer):
    try:
        data = parse_submission(issue.get("body"))
    except ValueError as error:
        return None, str(error)
    return prepare(root, issue, data, tools, gh.display_name(issue["user"]["login"]), maintainer), None


def submission(gh, issue, root, tools, maintainer):
    number = issue["number"]
    prepared, error = evaluate(gh, issue, root, tools, maintainer)
    labels = {label["name"] for label in issue.get("labels", [])}
    if "approved" in labels:
        gh.unlabel(number, "approved")
    if prepared is None:
        gh.label(number, "submission", "invalid")
        gh.comment(number, f"### ❌ Needs changes\n\n- {cell(error)}\n\nPublish from MeShell (long-press a module → **Publish to catalogue**) "
                   "or keep the JSON block it generates. Edit this issue to fix it.")
        return
    if prepared["problems"]:
        gh.label(number, "submission", "invalid")
    else:
        gh.label(number, "submission")
        gh.unlabel(number, "invalid")
    gh.comment(number, report(issue, prepared))


def approve(gh, event, issue, root, tools, maintainer):
    number, sender = issue["number"], event["sender"]["login"]
    if gh.permission(sender) not in MAINTAINER_ROLES:
        gh.unlabel(number, "approved")
        return False
    prepared, error = evaluate(gh, issue, root, tools, maintainer)
    if prepared is None or prepared["problems"]:
        gh.unlabel(number, "approved")
        gh.label(number, "invalid")
        gh.comment(number, report(issue, prepared) if prepared else f"### ❌ Needs changes\n\n- {cell(error)}")
        return False
    entry, login, user = prepared["entry"], issue["user"]["login"], issue["user"]["id"]
    message = (f"{'Update' if prepared['update'] else 'Add'} {entry['id']} {entry['version']}\n\n"
               f"Submitted by @{login} in #{number}, approved by @{sender}.\n\n"
               f"Co-authored-by: {login} <{user}+{login}@users.noreply.github.com>\n")
    gh.commit(prepared["files"], message)
    gh.unlabel(number, "invalid")
    gh.comment(number, f"🎉 Published **{cell(entry['title'])}** {entry['version']} by @{login}. It appears in MeShell → **Modules → Catalogue** "
               f"in a few minutes. Source: [tools/{entry['id']}](../tree/main/tools/{entry['id']}).\n\n"
               "Share it: ratings and downloads from other people move it up the catalogue.")
    if issue["state"] == "open":
        gh.close(number)
    return True


# Static catalogue page: the same index, readable and shareable without the app.

CATEGORY_ICONS = {"system": "⚙️", "network": "📡", "files": "📁", "developer": "🧑‍💻", "productivity": "✅", "media": "🖼️", "fun": "🎲"}


def site(index, statistics):
    numbers = statistics.get("tools", {})
    tools = sorted(index["tools"], key=lambda tool: (-numbers.get(tool["id"], {}).get("downloads", 0), tool["id"]))
    cards = []
    for tool in tools:
        item = numbers.get(tool["id"], {})
        votes = item.get("votes", 0)
        score = f"★ {item.get('rating', 0):.1f} ({votes})" if votes else "☆ no ratings yet"
        permissions = "".join(f"<span class=chip>{html.escape(name)}</span>" for name in tool["permissions"]) or "<span class=chip>no permissions</span>"
        cards.append(
            f"<article id=\"{html.escape(tool['id'])}\"><div class=icon>{CATEGORY_ICONS.get(tool['category'], '🧩')}</div><div>"
            f"<h2>{html.escape(tool['title'])} <small>{html.escape(tool['version'])}</small></h2>"
            f"<p class=by>by <a href=\"https://github.com/{html.escape(tool['github'])}\">@{html.escape(tool['github'])}</a> · {html.escape(tool['category'])}</p>"
            f"<p>{html.escape(tool['description'])}</p>"
            f"<p class=meta>{score} · ↓ {item.get('downloads', 0)} · {tool['size']} B</p><p>{permissions}</p>"
            f"<p><a href=\"https://github.com/{html.escape(index['repository'])}/tree/main/tools/{html.escape(tool['id'])}\">Source and commands</a></p>"
            "</div></article>")
    wanted_items = "".join(f"<li><a href=\"{html.escape(item['url'])}\">{html.escape(item['title'])}</a> <small>👍 {item['votes']}</small></li>"
                           for item in statistics.get("requests", []))
    repository = html.escape(index["repository"])
    return f"""<!doctype html>
<html lang=en><head><meta charset=utf-8><meta name=viewport content="width=device-width,initial-scale=1">
<title>MeShell modules</title><meta name=description content="Community modules for MeShell, the Android agent workspace.">
<style>
:root{{--bg:#0f1412;--card:#18201d;--ink:#e8f0ec;--soft:#9fb3aa;--mint:#5fd3a6;--line:#26322d}}
@media (prefers-color-scheme:light){{:root{{--bg:#f4f7f5;--card:#fff;--ink:#14201b;--soft:#5b6e66;--mint:#11865b;--line:#dfe7e3}}}}
body{{margin:0;background:var(--bg);color:var(--ink);font:15px/1.5 system-ui,sans-serif}}
main{{max-width:880px;margin:auto;padding:24px 16px 48px}}
a{{color:var(--mint)}} h1{{margin:0 0 4px;font-size:28px}} .lead{{color:var(--soft);margin:0 0 20px}}
.actions a{{display:inline-block;margin:0 8px 8px 0;padding:8px 14px;border-radius:20px;border:1px solid var(--line);text-decoration:none}}
.actions a.primary{{background:var(--mint);color:var(--bg);border-color:var(--mint)}}
article{{display:flex;gap:14px;background:var(--card);border:1px solid var(--line);border-radius:16px;padding:14px 16px;margin:12px 0}}
.icon{{font-size:28px;line-height:1}} h2{{margin:0;font-size:18px}} h2 small{{color:var(--soft);font-weight:400;font-size:13px}}
p{{margin:4px 0}} .by,.meta{{color:var(--soft);font-size:13px}}
.chip{{display:inline-block;font-size:12px;padding:1px 8px;border-radius:10px;border:1px solid var(--line);margin:0 4px 4px 0;color:var(--soft)}}
section{{margin-top:28px}} li{{margin:4px 0}}
</style></head><body><main>
<h1>MeShell modules</h1>
<p class=lead>{len(tools)} community modules for <a href="{APP}">MeShell</a>. Install them in the app: <b>Modules → Catalogue</b>.</p>
<p class=actions><a class=primary href="{APP}/releases/latest">Get MeShell</a><a href="https://github.com/{repository}/blob/main/CONTRIBUTING.md">Publish a module</a><a href="https://github.com/{repository}/issues/new?title=%5Brequest%5D+">Request a module</a></p>
{''.join(cards)}
<section><h2>Wanted modules</h2>{f'<ul>{wanted_items}</ul>' if wanted_items else '<p class=meta>No open requests yet.</p>'}</section>
<p class=meta>Updated {html.escape(statistics.get('generated', ''))}. Modules are shell commands reviewed by a maintainer, not sandboxed apps.</p>
</main></body></html>
"""


def main():
    parser = argparse.ArgumentParser(description="Catalogue marketplace automation; never executes module commands.")
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("publish", "stats", "site"):
        command = commands.add_parser(name)
        command.add_argument("--index", type=Path, required=True)
        if name != "publish":
            command.add_argument("--output", type=Path, required=True)
        if name == "site":
            command.add_argument("--stats", type=Path, required=True)
    commands.add_parser("triage").add_argument("--event", type=Path, required=True)
    args = parser.parse_args()
    root = catalog.ROOT
    if args.command == "site":
        args.output.write_text(site(catalog.load(args.index), catalog.load(args.stats)), encoding="utf-8")
        print("SITE_OK")
        return
    gh = GitHub(gh_repository(), os.environ["GITHUB_TOKEN"])
    if args.command == "publish":
        print("RELEASES_OK", " ".join(publish(gh, root, catalog.load(args.index))) or "unchanged")
    elif args.command == "stats":
        index = catalog.load(args.index)
        termux = None
        if any(tool["packages"] for tool in index["tools"]):
            try:
                with urllib.request.urlopen(urllib.request.Request(TERMUX, headers={"User-Agent": "meshell-tools"}), timeout=60) as response:
                    termux = response.read(64 * 1024 * 1024).decode("utf-8", "replace")
            except OSError as error:
                print(f"Termux index unavailable: {error}", file=sys.stderr)
        result = stats(gh, index, termux)
        args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print("STATS_OK", sum(item["votes"] for item in result["tools"].values()), "votes")
    else:
        event = json.loads(args.event.read_text(encoding="utf-8"))
        if triage(gh, event, root):
            gh.dispatch()
            print("TRIAGE_OK dispatched publish")
        else:
            print("TRIAGE_OK")


if __name__ == "__main__":
    main()
