#!/usr/bin/env python3
"""Python fallback for marks. Same envelope as cmd/marks."""

from __future__ import annotations

import json
import os
import platform
import re
import secrets
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

DROP = {
    "utm_source",
    "utm_medium",
    "utm_campaign",
    "utm_term",
    "utm_content",
    "utm_id",
    "fbclid",
    "gclid",
    "gclsrc",
    "dclid",
    "mc_eid",
    "mc_cid",
    "igshid",
    "si",
    "ref",
    "ref_src",
    "ref_url",
    "yclid",
    "msclkid",
    "twclid",
}


FORBIDDEN = ("/keys", "keys/", "licenses.json", "kraken_catalog", "topta.co")


def _check_dir(path: Path) -> Path:
    text = str(path.resolve()).replace("\\", "/").lower()
    for part in FORBIDDEN:
        if part in text:
            raise PermissionError(f"forbidden store path {part}")
    return path


def resolve(payload: dict | None = None) -> tuple[Path, str]:
    payload = payload or {}
    explicit = payload.get("dir") or os.environ.get("KRAKEN_MARKS_DIR")
    if explicit:
        p = Path(os.path.expandvars(str(explicit)))
        if p.name == "marks" and p.parent.name == "data":
            return _check_dir(p), "dir"
        if p.name == ".kraken":
            return _check_dir(p / "data" / "marks"), "dir"
        return _check_dir(p / ".kraken" / "data" / "marks"), "dir"
    scope = (
        payload.get("scope") or os.environ.get("KRAKEN_MARKS_SCOPE") or "home"
    ).lower()
    if scope == "project":
        cur = Path.cwd()
        while True:
            cand = cur / ".kraken"
            if cand.is_dir():
                return cand / "data" / "marks", "project"
            if cur.parent == cur:
                break
            cur = cur.parent
        scope = "home"
    if scope == "system":
        sysroot = Path(os.environ.get("KRAKEN_SYSTEM") or "/etc/kraken")
        return sysroot / "data" / "marks", "system"
    root = os.environ.get("KRAKEN_HOME") or str(Path.home())
    return Path(root) / ".kraken" / "data" / "marks", "home"


def home(payload: dict | None = None) -> Path:
    d, _ = resolve(payload)
    return d


def load(payload: dict | None = None) -> dict:
    p = home(payload) / "store.json"
    if not p.exists():
        return {"token": "", "bookmarks": []}
    return json.loads(p.read_text(encoding="utf-8"))


def save(st: dict, payload: dict | None = None) -> None:
    d = home(payload)
    d.mkdir(parents=True, exist_ok=True)
    (d / "store.json").write_text(json.dumps(st, indent=2), encoding="utf-8")
    os.chmod(d / "store.json", 0o600)


def clean_url(raw: str) -> tuple[str, str]:
    raw = (raw or "").strip()
    if not raw:
        raise ValueError("empty_url")
    # A scheme-looking prefix (`javascript:`, `data:`, `file:`, ...) must be
    # rejected, not laundered into https:// by the bare-host default below.
    scheme_head = raw.split(":", 1)[0].strip().lower() if ":" in raw else ""
    if scheme_head and "://" not in scheme_head and "/" not in scheme_head:
        if not re.fullmatch(r"[a-z][a-z0-9+.-]*", scheme_head):
            raise ValueError("unsupported_scheme")
        if scheme_head not in ("http", "https"):
            raise ValueError("unsupported_scheme")
    if "://" not in raw:
        raw = "https://" + raw
    u = urlparse(raw)
    if u.scheme not in ("http", "https"):
        raise ValueError("unsupported_scheme")
    if not u.hostname:
        raise ValueError("no_host")
    q = [
        (k, v)
        for k, v in parse_qsl(u.query, keep_blank_values=True)
        if k.lower() not in DROP and not k.lower().startswith("utm_")
    ]
    cleaned = urlunparse((u.scheme, u.netloc, u.path, u.params, urlencode(q), ""))
    host = (u.hostname or "").lower().removeprefix("www.")
    return cleaned, host


def ensure_token(st: dict, payload: dict | None = None) -> str:
    if not st.get("token"):
        st["token"] = secrets.token_hex(16)
        save(st, payload)
    return st["token"]


def add(st: dict, payload: dict) -> dict:
    url, domain = clean_url(payload.get("url") or payload.get("href") or "")
    title = payload.get("title") or domain
    folder = payload.get("folder") or domain
    tags = payload.get("tags") or []
    if isinstance(tags, str):
        tags = [tags]
    bm = {
        "id": secrets.token_hex(6),
        "url": url,
        "title": title,
        "domain": domain,
        "folder": folder,
        "tags": [str(t).lower() for t in tags],
        "note": payload.get("note") or payload.get("selection") or "",
        "created": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    }
    for i, exist in enumerate(st["bookmarks"]):
        if exist.get("url") == url:
            exist.update({k: bm[k] for k in ("title", "folder", "note") if bm[k]})
            exist["tags"] = sorted(set(exist.get("tags", []) + bm["tags"]))
            st["bookmarks"][i] = exist
            return exist
    st["bookmarks"].append(bm)
    return bm


def ok(result, ident=None):
    return {"v": 1, "id": ident, "ok": True, "result": result}


def err(code, message, ident=None):
    return {
        "v": 1,
        "id": ident,
        "ok": False,
        "error": {"code": code, "message": message},
    }


def dispatch(req: dict) -> dict:
    action = req.get("action") or "ping"
    payload = req.get("payload") or {}
    ident = req.get("id")
    # The store path is jailed. A refusal is an error envelope, never a
    # traceback: every response must be exactly one JSON object on stdout.
    try:
        st = load(payload)
        dest, scope = resolve(payload)
    except PermissionError as exc:
        return err("forbidden", str(exc), ident)
    except ValueError as exc:
        return err("bad_payload", str(exc), ident)
    if action == "ping":
        return ok(
            {
                "arm": "marks",
                "version": "0.1.0",
                "protocol": 1,
                "platform": f"{sys.platform}-{platform.machine()}",
                "scope": scope,
                "dir": str(dest),
            },
            ident,
        )
    if action == "where":
        return ok(
            {
                "arm": "marks",
                "scope": scope,
                "dir": str(dest),
                "hint": "API keys in ~/.kraken/keys are licenses, not this store",
            },
            ident,
        )
    if action == "token":
        if payload.get("rotate"):
            st["token"] = ""
        return ok({"token": ensure_token(st, payload), "path": str(dest)}, ident)
    if action == "strip":
        try:
            url, domain = clean_url(payload.get("url") or "")
        except ValueError as e:
            return err("bad_url", str(e), ident)
        return ok({"url": url, "domain": domain}, ident)
    if action == "add":
        try:
            bm = add(st, payload)
        except ValueError as e:
            return err("bad_url", str(e), ident)
        save(st, payload)
        return ok(
            {"arm": "marks", "bookmark": bm, "count": len(st["bookmarks"])}, ident
        )
    if action in ("list", "search"):
        q = (payload.get("q") or payload.get("query") or "").lower()
        folder = payload.get("folder") or ""
        hits = []
        for b in st["bookmarks"]:
            if folder and b.get("folder") != folder:
                continue
            blob = " ".join(
                [
                    b.get("title", ""),
                    b.get("url", ""),
                    b.get("domain", ""),
                    " ".join(b.get("tags") or []),
                ]
            ).lower()
            if q and q not in blob:
                continue
            hits.append(b)
        return ok({"arm": "marks", "bookmarks": hits, "count": len(hits)}, ident)
    if action == "get":
        for b in st["bookmarks"]:
            if b.get("id") == payload.get("id"):
                return ok({"bookmark": b}, ident)
        return err("not_found", "no bookmark", ident)
    if action == "remove":
        before = len(st["bookmarks"])
        st["bookmarks"] = [
            b for b in st["bookmarks"] if b.get("id") != payload.get("id")
        ]
        if len(st["bookmarks"]) == before:
            return err("not_found", "no bookmark", ident)
        save(st, payload)
        return ok({"removed": True}, ident)
    if action == "folder":
        for b in st["bookmarks"]:
            if b.get("id") == payload.get("id"):
                b["folder"] = payload.get("folder") or b["folder"]
                save(st, payload)
                return ok({"bookmark": b}, ident)
        return err("not_found", "no bookmark", ident)
    if action in ("tag", "untag"):
        for b in st["bookmarks"]:
            if b.get("id") == payload.get("id"):
                extra = payload.get("tags") or []
                if payload.get("tag"):
                    extra = list(extra) + [payload["tag"]]
                extra = [str(x).lower() for x in extra]
                if action == "tag":
                    b["tags"] = sorted(set((b.get("tags") or []) + extra))
                else:
                    b["tags"] = [t for t in (b.get("tags") or []) if t not in extra]
                save(st, payload)
                return ok({"bookmark": b}, ident)
        return err("not_found", "no bookmark", ident)
    if action == "export":
        fmt = payload.get("format") or "json"
        path = dest / f"export.{fmt}"
        dest.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(st["bookmarks"], indent=2), encoding="utf-8")
        return ok(
            {"path": str(path), "format": fmt, "count": len(st["bookmarks"])}, ident
        )
    if action == "import":
        raw = payload.get("json")
        if not raw:
            raw = Path(payload.get("path") or payload.get("file") or "").read_text(
                encoding="utf-8"
            )
        items = json.loads(raw)
        for it in items:
            if it.get("url"):
                add(st, it)
        save(st, payload)
        return ok({"count": len(st["bookmarks"])}, ident)
    if action == "bookmarklet":
        tok = ensure_token(st, payload)
        port = int(payload.get("port") or 7437)
        js = (
            "javascript:(function(){var u=location.href,t=document.title||u;"
            f"window.open('http://127.0.0.1:{port}/add?token={tok}&url='+encodeURIComponent(u)"
            "+'&title='+encodeURIComponent(t),'_blank','noopener,width=480,height=240');})();"
        )
        html = dest / "bookmarklet.html"
        dest.mkdir(parents=True, exist_ok=True)
        html.write_text(f'<a href="{js}">save to marks</a>', encoding="utf-8")
        return ok(
            {"javascript": js, "html": str(html), "port": port, "bind": "127.0.0.1"},
            ident,
        )
    if action == "listen":
        return ok(
            {
                "arm": "marks",
                "bind": "127.0.0.1",
                "port": int(payload.get("port") or 7437),
                "mode": "plan",
                "hint": "use the Go binary for once/daemon listen",
            },
            ident,
        )
    if action == "finish":
        raw = dict(payload.get("raw") or {"arm": "marks"})
        raw.update(payload.get("patch") or {})
        raw["finished"] = True
        return ok(raw, ident)
    if action == "clear":
        st["bookmarks"] = []
        save(st, payload)
        return ok({"cleared": True}, ident)
    return err("unknown_action", f"unknown action {action}", ident)


def main() -> int:
    raw = sys.stdin.read()
    ident = None
    try:
        req = json.loads(raw) if raw.strip() else {"action": "ping", "payload": {}}
        ident = req.get("id")
    except json.JSONDecodeError:
        json.dump(err("bad_json", "stdin must be JSON"), sys.stdout)
        sys.stdout.write("\n")
        return 1
    try:
        out = dispatch(req)
    except Exception as exc:  # noqa: BLE001 — the envelope is the contract
        out = err("internal", f"{type(exc).__name__}: {exc}"[:300], ident)
    json.dump(out, sys.stdout)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
