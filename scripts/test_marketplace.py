import json
import unittest

import catalog
import marketplace
from marketplace import aggregate, closure_size, downloads, fenced, parse_rating, parse_submission, prepare, termux_index, wanted


def issue(number, login, title, body="", created="2026-10-01T00:00:00Z", labels=(), state="open", kind="User", reactions=0):
    return {"number": number, "title": title, "body": body, "created_at": created, "state": state, "html_url": f"https://example.invalid/{number}",
            "user": {"login": login, "id": 1000 + number, "type": kind}, "labels": [{"name": name} for name in labels],
            "reactions": {"+1": reactions}}


def rating_body(tool, stars, text=""):
    # The body MeShell's MarketRules.ratingBody writes.
    return f"Module: {tool}\nVersion: 1.0.0\nRating: {stars}/5\n" + (f"\n{text}\n" if text else "")


def submission_body(module, version="1.0.0", category="fun"):
    data = {"format": 1, "module": module, "catalog": {"version": version, "category": category, "license": "MIT-0", "min_app_version": "0.10.0"},
            "readme": "Says hello."}
    return "MeShell module submission.\n\n```json\n" + json.dumps(data, indent=2) + "\n```\n"


HELLO = {"id": "hello", "title": "Hello", "description": "Greets", "actions": [{"id": "hi", "label": "Hi", "command": "echo hi"}]}


class FakeGitHub:
    repository = "owner/tools"

    def __init__(self, roles=None):
        self.roles, self.log, self.labels, self.comments, self.commits = roles or {}, [], set(), [], []

    def ensure_labels(self):
        pass

    def label(self, number, *names):
        self.labels.update(names)

    def unlabel(self, number, name):
        self.labels.discard(name)

    def comment(self, number, text):
        self.comments.append(text)

    def close(self, number, reason="completed"):
        self.log.append(("close", reason))

    def permission(self, login):
        return self.roles.get(login, "none")

    def display_name(self, login):
        return login.title()

    def commit(self, files, message):
        self.commits.append((files, message))


class ProtocolTests(unittest.TestCase):
    def test_rating_protocol(self):
        self.assertEqual(parse_rating("[rating] battery", rating_body("battery", 4, "Nice")),
                         {"id": "battery", "version": "1.0.0", "stars": 4, "text": "Nice"})
        self.assertEqual(parse_rating("[Rating]  battery ", "Rating: ★★★☆☆\n\n<!-- hint -->Ok")["stars"], 3)
        for title, body in (("[rating] battery", "Rating: 6/5"), ("[rating] battery", "no rating"), ("[rating] Bad Id", "Rating: 3/5"),
                            ("[rating] battery", "Module: weather\nRating: 3/5"), ("battery", "Rating: 3/5")):
            self.assertIsNone(parse_rating(title, body), (title, body))

    def test_aggregate_counts_one_vote_per_account(self):
        owners = {"battery": "author", "weather": "author"}
        issues = [
            issue(1, "ann", "[rating] battery", rating_body("battery", 2), "2026-10-01T00:00:00Z"),
            issue(2, "Ann", "[rating] battery", rating_body("battery", 5, "Changed my mind"), "2026-10-02T00:00:00Z"),
            issue(3, "bob", "[rating] battery", rating_body("battery", 4), "2026-10-03T00:00:00Z"),
            issue(4, "author", "[rating] battery", rating_body("battery", 5)),
            issue(5, "bot", "[rating] battery", rating_body("battery", 1), kind="Bot"),
            issue(6, "eve", "[rating] battery", rating_body("battery", 1), labels=("spam",)),
            issue(7, "carl", "[rating] missing", rating_body("missing", 1)),
        ]
        result = aggregate(issues, owners)
        self.assertEqual((result["battery"]["votes"], result["battery"]["rating"], result["battery"]["histogram"]), (2, 4.5, [0, 0, 0, 1, 1]))
        self.assertEqual([review["login"] for review in result["battery"]["reviews"]], ["Ann"])
        self.assertEqual(result["weather"], {"rating": 0, "votes": 0, "histogram": [0] * 5, "reviews": []})

    def test_requests_downloads_and_packages(self):
        requests = wanted([issue(1, "a", "[request] Torch toggle", reactions=2), issue(2, "b", "[request] Clipboard", reactions=5),
                           issue(3, "c", "[request] Done", state="closed", reactions=9), issue(4, "d", "[rating] x")])
        self.assertEqual([item["title"] for item in requests], ["Clipboard", "Torch toggle"])
        releases = [{"tag_name": "battery@1.0.0", "assets": [{"name": "module.json", "download_count": 3}]},
                    {"tag_name": "battery@1.1.0", "assets": [{"name": "module.json", "download_count": 4}, {"name": "other", "download_count": 50}]},
                    {"tag_name": "v1", "assets": [{"name": "module.json", "download_count": 9}]}]
        self.assertEqual(downloads(releases), {"battery": 7})
        index = termux_index("Package: jq\nDepends: oniguruma (>= 6), libc++ | libc\nSize: 100\n\nPackage: oniguruma\nSize: 20\n\n"
                             "Package: libc++\nSize: 3\nDescription: x\n continued: line\n")
        self.assertEqual(closure_size(["jq"], index), 123)
        self.assertEqual(closure_size(["unknown"], index), 0)

    def test_fence_survives_backticks(self):
        text = fenced("echo ```` done")
        self.assertTrue(text.startswith("`````sh\n") and text.endswith("\n`````"))


class SubmissionTests(unittest.TestCase):
    def setUp(self):
        self.tools = {tool["id"]: tool for tool in catalog.build_catalog(catalog.ROOT, "test")["tools"]}

    def test_new_module(self):
        prepared = prepare(catalog.ROOT, issue(9, "maker", "[submit] hello"), parse_submission(submission_body(HELLO)), self.tools, "Maker", "owner")
        self.assertEqual(prepared["problems"], [])
        self.assertEqual(prepared["entry"]["github"], "maker")
        self.assertEqual(prepared["entry"]["author"], "Maker")
        self.assertEqual(prepared["entry"]["download"], "https://github.com/ilya-bondarev/meshell-tools/releases/download/hello@1.0.0/module.json")
        files = prepared["files"]
        self.assertEqual(sorted(name.split("/")[-1] for name in files), sorted(catalog.TOOL_FILES))
        self.assertIn("## 1.0.0\n\nInitial version.", files["tools/hello/CHANGELOG.md"])
        self.assertEqual(json.loads(files["tools/hello/module.json"]), HELLO)

    def test_problems_block_publishing(self):
        def problems(module, login="maker", title=None, version="1.0.0"):
            body = submission_body(module, version)
            return prepare(catalog.ROOT, issue(9, login, title or f"[submit] {module['id']}"), parse_submission(body), self.tools, "X", "owner")["problems"]
        network = {**HELLO, "actions": [{"id": "hi", "command": "curl https://example.org"}]}
        self.assertTrue(any("undeclared permissions: network" in item for item in problems(network)))
        self.assertTrue(any("pipes text into a shell" in item for item in problems({**HELLO, "actions": [{"id": "x", "command": "cat x | sh"}]})))
        self.assertTrue(any("belongs to" in item for item in problems({**HELLO, "id": "battery"}, version="9.0.0")))
        owner = self.tools["battery"]["github"]
        self.assertTrue(any("must be newer" in item for item in problems({**HELLO, "id": "battery"}, owner, version="1.0.0")))
        self.assertEqual(problems({**HELLO, "id": "battery"}, owner, version="9.0.0"), [])
        self.assertTrue(any("title names" in item for item in problems(HELLO, title="[submit] other")))
        self.assertTrue(any("app built-in" in item for item in problems({**HELLO, "id": "notes"})))
        with self.assertRaises(ValueError):
            parse_submission("no json here")

    def test_triage_and_approval(self):
        gh = FakeGitHub({"owner": "admin"})
        submitted = issue(9, "maker", "[submit] hello", submission_body(HELLO), labels=())
        marketplace.triage(gh, {"action": "opened", "issue": submitted}, catalog.ROOT)
        self.assertEqual(gh.labels, {"submission"})
        self.assertIn("Ready for review", gh.comments[-1])
        self.assertIn("```sh\necho hi\n```", gh.comments[-1])
        stranger = {"action": "labeled", "label": {"name": "approved"}, "issue": submitted, "sender": {"login": "maker"}}
        self.assertFalse(marketplace.triage(gh, stranger, catalog.ROOT))
        self.assertEqual(gh.commits, [])
        approval = {**stranger, "sender": {"login": "owner"}}
        self.assertTrue(marketplace.triage(gh, approval, catalog.ROOT))
        files, message = gh.commits[0]
        self.assertIn("tools/hello/module.json", files)
        self.assertIn("Co-authored-by: maker <1009+maker@users.noreply.github.com>", message)
        self.assertIn(("close", "completed"), gh.log)

    def test_triage_rating(self):
        gh = FakeGitHub()
        good = issue(5, "fan", "[rating] battery", rating_body("battery", 5))
        self.assertTrue(marketplace.triage(gh, {"action": "opened", "issue": good}, catalog.ROOT))
        self.assertEqual(gh.labels, {"rating"})
        self.assertIn(("close", "completed"), gh.log)
        own = issue(6, self.tools["battery"]["github"], "[rating] battery", rating_body("battery", 5))
        gh = FakeGitHub()
        self.assertFalse(marketplace.triage(gh, {"action": "opened", "issue": own}, catalog.ROOT))
        self.assertEqual(gh.labels, {"invalid"})

    def test_site(self):
        index = catalog.build_catalog(catalog.ROOT, "test")
        page = marketplace.site(index, {"generated": "now", "tools": {"battery": {"downloads": 9, "rating": 4.5, "votes": 2}},
                                        "requests": [{"title": "<b>Torch</b>", "url": "https://example.invalid/1", "votes": 3}]})
        self.assertIn("★ 4.5 (2)", page)
        self.assertIn("&lt;b&gt;Torch&lt;/b&gt;", page)
        self.assertLess(page.index('id="battery"'), page.index('id="weather"'))


if __name__ == "__main__":
    unittest.main()
