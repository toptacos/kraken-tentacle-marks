#!/usr/bin/env python3
"""marks contract tests. Offline, temp KRAKEN_HOME, no vendor calls.

Covers the JSON v1 envelope, URL tracking-param stripping, the path jail,
the loopback-only bookmarklet, and the store file mode.
"""

import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def invoke(action, payload=None, env=None, cwd=None, raw=None):
    run = os.environ.copy()
    run["KRAKEN_OFFLINE"] = "1"
    if env:
        run.update(env)
    body = (
        raw
        if raw is not None
        else json.dumps(
            {"v": 1, "id": None, "action": action, "payload": payload or {}}
        )
    )
    proc = subprocess.run(
        ["sh", str(ROOT / "handler.sh")],
        input=body,
        text=True,
        capture_output=True,
        env=run,
        cwd=cwd,
        check=False,
    )
    lines = [ln for ln in proc.stdout.splitlines() if ln.startswith("{")]
    if not lines:
        raise AssertionError(
            f"no JSON on stdout: rc={proc.returncode} err={proc.stderr[:400]}"
        )
    return json.loads(lines[-1])


class Marks(unittest.TestCase):
    def setUp(self):
        self.home = tempfile.mkdtemp()
        self.env = {"KRAKEN_HOME": self.home}
        self.store = Path(self.home) / ".kraken" / "data" / "marks"

    def call(self, action, payload=None, **kw):
        kw.setdefault("env", self.env)
        return invoke(action, payload, **kw)

    def add(self, url, **extra):
        return self.call("add", {"url": url, **extra})

    # --- envelope ---------------------------------------------------------

    def test_ping(self):
        r = self.call("ping")
        self.assertTrue(r["ok"])
        self.assertEqual(r["v"], 1)
        self.assertEqual(r["result"]["arm"], "marks")
        self.assertIn("platform", r["result"])

    def test_ping_on_empty_stdin(self):
        r = invoke(None, env=self.env, raw="")
        self.assertTrue(r["ok"])

    def test_error_envelope_shape(self):
        r = self.call("nope")
        self.assertFalse(r["ok"])
        self.assertEqual(set(r["error"]), {"code", "message"})
        self.assertNotIn("result", r)

    def test_where_reports_home_scope(self):
        r = self.call("where")
        self.assertTrue(r["ok"])
        self.assertEqual(r["result"]["scope"], "home")
        self.assertEqual(r["result"]["dir"], str(self.store))

    # --- URL hygiene ------------------------------------------------------

    def test_strips_tracking_params(self):
        r = self.call(
            "strip",
            {"url": "https://kraken.topta.co/x?utm_source=n&gclid=9&id=7&fbclid=z"},
        )
        self.assertTrue(r["ok"])
        self.assertNotIn("utm_source", r["result"]["url"])
        self.assertNotIn("gclid", r["result"]["url"])
        self.assertNotIn("fbclid", r["result"]["url"])
        self.assertIn("id=7", r["result"]["url"])
        self.assertEqual(r["result"]["domain"], "kraken.topta.co")

    def test_strips_utm_prefix_variants(self):
        r = self.call("strip", {"url": "https://example.com/p?utm_medium=a&utm_zzz=b"})
        self.assertNotIn("utm_", r["result"]["url"])

    def test_strips_fragment(self):
        r = self.call("strip", {"url": "https://example.com/p#section"})
        self.assertNotIn("#", r["result"]["url"])

    def test_adds_scheme_when_missing(self):
        r = self.call("strip", {"url": "example.com/p"})
        self.assertTrue(r["result"]["url"].startswith("https://example.com/p"))

    def test_www_stripped_from_domain(self):
        r = self.call("strip", {"url": "https://www.example.com/p"})
        self.assertEqual(r["result"]["domain"], "example.com")

    def test_rejects_non_http_scheme(self):
        r = self.call("strip", {"url": "javascript:alert(1)"})
        self.assertFalse(r["ok"])
        self.assertEqual(r["error"]["code"], "bad_url")

    def test_rejects_empty_url(self):
        r = self.call("add", {"url": ""})
        self.assertFalse(r["ok"])
        self.assertEqual(r["error"]["code"], "bad_url")

    # --- add / dedupe -----------------------------------------------------

    def test_add_defaults_folder_to_registrable_host(self):
        r = self.add("https://kraken.topta.co/docs")
        bm = r["result"]["bookmark"]
        self.assertEqual(bm["folder"], "kraken.topta.co")
        self.assertEqual(bm["domain"], "kraken.topta.co")

    def test_add_dedupes_and_merges_tags(self):
        self.add("https://example.com/a", tags=["cli"])
        r = self.add("https://example.com/a", tags=["docs"], title="Example A")
        self.assertEqual(r["result"]["count"], 1)
        bm = r["result"]["bookmark"]
        self.assertEqual(bm["tags"], ["cli", "docs"])
        self.assertEqual(bm["title"], "Example A")

    def test_tags_are_lowercased(self):
        r = self.add("https://example.com/b", tags=["CLI", "HomeLab"])
        self.assertEqual(r["result"]["bookmark"]["tags"], ["cli", "homelab"])

    def test_note_does_not_escape_store(self):
        r = self.add("https://example.com/c", note="<b>hi</b>")
        self.assertEqual(r["result"]["bookmark"]["note"], "<b>hi</b>")

    # --- list / search ----------------------------------------------------

    def test_list_and_search(self):
        self.add("https://kraken.topta.co/cli", title="Kraken CLI", tags=["cli"])
        self.add("https://tacos.topta.co/", title="Tacos", tags=["food"])
        self.assertEqual(self.call("list")["result"]["count"], 2)
        self.assertEqual(self.call("search", {"q": "kraken"})["result"]["count"], 1)
        self.assertEqual(self.call("search", {"q": "food"})["result"]["count"], 1)
        self.assertEqual(
            self.call("search", {"q": "nothing-here"})["result"]["count"], 0
        )

    def test_search_scopes_to_folder(self):
        self.add("https://kraken.topta.co/x", folder="cli")
        self.add("https://example.com/y", folder="misc")
        r = self.call("search", {"folder": "cli"})
        self.assertEqual(r["result"]["count"], 1)
        self.assertEqual(r["result"]["bookmarks"][0]["folder"], "cli")

    # --- get / remove / folder / tags -------------------------------------

    def test_get_remove_roundtrip(self):
        bid = self.add("https://example.com/d")["result"]["bookmark"]["id"]
        self.assertEqual(self.call("get", {"id": bid})["result"]["bookmark"]["id"], bid)
        self.assertTrue(self.call("remove", {"id": bid})["ok"])
        self.assertEqual(self.call("get", {"id": bid})["error"]["code"], "not_found")
        self.assertEqual(self.call("remove", {"id": bid})["error"]["code"], "not_found")

    def test_folder_move(self):
        bid = self.add("https://example.com/e")["result"]["bookmark"]["id"]
        r = self.call("folder", {"id": bid, "folder": "archive"})
        self.assertEqual(r["result"]["bookmark"]["folder"], "archive")

    def test_tag_and_untag(self):
        bid = self.add("https://example.com/f", tags=["a"])["result"]["bookmark"]["id"]
        r = self.call("tag", {"id": bid, "tag": "B"})
        self.assertEqual(r["result"]["bookmark"]["tags"], ["a", "b"])
        r = self.call("untag", {"id": bid, "tag": "a"})
        self.assertEqual(r["result"]["bookmark"]["tags"], ["b"])

    def test_mutations_on_missing_id_are_not_found(self):
        for action in ("get", "remove", "folder", "tag", "untag"):
            r = self.call(action, {"id": "nope"})
            self.assertFalse(r["ok"], action)
            self.assertEqual(r["error"]["code"], "not_found", action)

    # --- token + bookmarklet ----------------------------------------------

    def test_token_is_stable_then_rotatable(self):
        first = self.call("token")["result"]["token"]
        self.assertEqual(len(first), 32)
        self.assertEqual(self.call("token")["result"]["token"], first)
        second = self.call("token", {"rotate": True})["result"]["token"]
        self.assertNotEqual(second, first)

    def test_bookmarklet_binds_loopback_only(self):
        r = self.call("bookmarklet")
        self.assertTrue(r["ok"])
        self.assertEqual(r["result"]["bind"], "127.0.0.1")
        self.assertIn("127.0.0.1", r["result"]["javascript"])
        self.assertIn(self.call("token")["result"]["token"], r["result"]["javascript"])
        self.assertTrue(Path(r["result"]["html"]).is_file())

    def test_listen_is_plan_only_and_loopback(self):
        r = self.call("listen", {"port": 9999})
        self.assertEqual(r["result"]["bind"], "127.0.0.1")
        self.assertEqual(r["result"]["port"], 9999)
        self.assertEqual(r["result"]["mode"], "plan")

    def test_no_public_bind_in_any_response(self):
        for action in ("bookmarklet", "listen", "ping", "where"):
            blob = json.dumps(self.call(action))
            self.assertNotIn("0.0.0.0", blob, action)

    # --- import / export ---------------------------------------------------

    def test_export_then_import(self):
        self.add("https://example.com/g", title="G")
        out = self.call("export")["result"]["path"]
        self.assertTrue(Path(out).is_file())

        other = tempfile.mkdtemp()
        r = self.call("import", {"path": out}, env={"KRAKEN_HOME": other})
        self.assertEqual(r["result"]["count"], 1)

    def test_import_inline_json(self):
        payload = json.dumps([{"url": "https://example.com/h", "title": "H"}])
        r = self.call("import", {"json": payload})
        self.assertEqual(r["result"]["count"], 1)

    # --- path jail --------------------------------------------------------

    def test_jail_refuses_keys_dir(self):
        r = self.call(
            "where", {"dir": str(Path(self.home) / ".kraken" / "keys" / "marks")}
        )
        self.assertFalse(r["ok"])

    def test_jail_refuses_catalog_path(self):
        r = self.call(
            "where", {"dir": str(Path(self.home) / "kraken_catalog" / "marks")}
        )
        self.assertFalse(r["ok"])

    def test_explicit_store_dir_is_used(self):
        target = Path(self.home) / "custom-marks"
        r = self.call("where", {"dir": str(target)})
        self.assertTrue(r["ok"])
        self.assertEqual(r["result"]["dir"], str(target / ".kraken" / "data" / "marks"))

    def test_project_scope(self):
        proj = Path(self.home) / "proj"
        (proj / ".kraken").mkdir(parents=True)
        r = invoke("ping", {"scope": "project"}, env=self.env, cwd=str(proj))
        self.assertEqual(r["result"]["scope"], "project")
        self.assertIn(str(proj), r["result"]["dir"])

    # --- storage hygiene ---------------------------------------------------

    def test_store_file_is_owner_only(self):
        self.add("https://example.com/i")
        mode = (self.store / "store.json").stat().st_mode & 0o777
        self.assertEqual(mode, 0o600)

    def test_clear_empties_but_keeps_token(self):
        self.add("https://example.com/j")
        before = self.call("token")["result"]["token"]
        self.assertTrue(self.call("clear")["ok"])
        self.assertEqual(self.call("list")["result"]["count"], 0)
        self.assertEqual(self.call("token")["result"]["token"], before)


if __name__ == "__main__":
    unittest.main()
