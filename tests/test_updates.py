"""Tests app updates, index integrity (entry.json), the mandatory SDK sha256 and the language choice.

    python3 tests/test_updates.py
"""
import hashlib
import http.server
import json
import os
import sys
import tempfile
import threading
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

tmp = tempfile.mkdtemp()
for var in ("XDG_CONFIG_HOME", "XDG_DATA_HOME", "XDG_CACHE_HOME"):
    os.environ[var] = os.path.join(tmp, var)
for var in ("LANGUAGE", "LC_ALL", "LC_MESSAGES", "LANG"):
    os.environ.pop(var, None)

srv = os.path.join(tmp, "srv")
os.makedirs(srv)
apk_bytes = b"PK\x03\x04 new version"
apk_sha = hashlib.sha256(apk_bytes).hexdigest()
with open(os.path.join(srv, "org.a_5.apk"), "wb") as f:
    f.write(apk_bytes)


class Quiet(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *a, **kw):
        super().__init__(*a, directory=srv, **kw)

    def log_message(self, *a):
        pass


server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Quiet)
threading.Thread(target=server.serve_forever, daemon=True).start()
base = "http://127.0.0.1:%d" % server.server_port

import catalog  # noqa: E402
import store  # noqa: E402

events = []
store.pyotherside.send = lambda *a: events.append(a)


def app(pkg, code, apk=""):
    return {"id": pkg, "name": pkg.upper(), "summary": "", "icon": "", "version": "v%d" % code, "versionCode": code,
            "apk": apk, "sha256": apk_sha, "size": 1, "native": False, "minSdk": 21}


# ---- which apps have an update ----
store._catalog = [app("org.a", 5, base + "/org.a_5.apk"), app("org.b", 2), app("org.c", 9), app("org.l", 99),
                  app("org.new", 1)]
old_a = os.path.join(store.APK_DIR, "org.a_3.apk")
with open(old_a, "wb") as f:
    f.write(b"old")
store._write_json(store.LIBRARY_FILE, {
    "org.a": {"pkgId": "org.a", "name": "A", "version": "v3", "versionCode": 3, "apk": old_a},
    # no versionCode (older library): taken from the file name -> same version, no update
    "org.b": {"pkgId": "org.b", "name": "B", "version": "v2", "apk": "/x/org.b_2.apk"},
    # unknown version: no false alarm
    "org.c": {"pkgId": "org.c", "name": "C", "version": "?", "apk": "/x/whatever.apk"},
    # your own APK is never updated, even if the package is in the catalog
    "org.l": {"pkgId": "org.l", "name": "L", "version": "1", "versionCode": 1, "apk": "/x/org.l_local.apk", "local": True},
})
assert [u["pkgId"] for u in store.updates_available()] == ["org.a"], store.updates_available()
assert store.updates_available()[0]["newVersion"] == "v5"
flags = {a["pkgId"]: a["updateAvailable"] for a in store.list_installed()}
assert flags == {"org.a": True, "org.b": False, "org.c": False, "org.l": False}, flags
assert {a["pkgId"] for a in store.search("") if a["updateAvailable"]} == {"org.a"}

# ---- pages: the whole catalog can be reached, not only the first 80 ----
names = lambda page: [a["pkgId"] for a in page]  # noqa: E731
assert names(store.search("", limit=2, offset=0)) == ["org.a", "org.b"]
assert names(store.search("", limit=2, offset=2)) == ["org.c", "org.l"]
assert names(store.search("", limit=2, offset=4)) == ["org.new"]
assert store.search("", limit=2, offset=10) == []
store._catalog = store._catalog + [app("big.%04d" % i, 1) for i in range(300)]
assert len(store.search("", limit=1000)) == 305
assert len(store.search("", limit=60, offset=240)) == 60
store._catalog = store._catalog[:5]

# ---- update all ----
assert store.update_all() == 1
for _ in range(60):
    if any(e[0] == "installed" for e in events):
        break
    time.sleep(0.1)
assert ("installed", "org.a") in events, events
entry = store._read_json(store.LIBRARY_FILE, {})["org.a"]
assert entry["versionCode"] == 5 and entry["apk"].endswith("org.a_5.apk"), entry
assert not os.path.exists(old_a), "the old APK must be removed"
assert store.updates_available() == []
assert store.update_all() == 0

# ---- the index must match entry.json ----
index_file = os.path.join(tmp, "index-v2.json")
with open(index_file, "w") as f:
    json.dump({"packages": {}}, f)
assert store._check_index_integrity(base, index_file) is False  # repo without entry.json: skipped
with open(os.path.join(srv, "entry.json"), "w") as f:
    json.dump({"index": {"name": "/index-v2.json", "sha256": store._file_sha256(index_file)}}, f)
assert store._check_index_integrity(base, index_file) is True
with open(os.path.join(srv, "entry.json"), "w") as f:
    json.dump({"index": {"name": "/index-v2.json", "sha256": "0" * 64}}, f)
try:
    store._check_index_integrity(base, index_file)
    raise AssertionError("a different index must be rejected")
except ValueError as exc:
    assert "entry.json" in str(exc)

# ---- the SDK is refused without a sha256 ----
os.remove(os.path.join(srv, "entry.json"))
store.SDK_BASE = base
events.clear()
store._sdk_busy = True
store._install_sdk_worker()
assert any(e[0] == "sdk_error" and "sha256" in e[1] for e in events), events
assert not store.sdk_status()["installed"]

# ---- language ----
catalog.set_locales(None)
os.environ["LANGUAGE"] = "de_DE:fr"
assert catalog.preferred_locales() == ["de-DE", "de", "fr", "en-US", "en"], catalog.preferred_locales()
os.environ["LANGUAGE"] = "el_GR.UTF-8"
assert catalog.pick_localized({"en-US": "Hi", "el-GR": "Γεια"}) == "Γεια"
assert catalog.pick_localized({"en-US": "Hi", "de": "Hallo"}) == "Hi"          # no Greek: English
assert catalog.pick_localized({"fr": "Salut"}) == "Salut"                        # nothing known: the first one
assert catalog.pick_locale_key({"en": "x", "el": "y"}) == "el"
assert catalog.pick_localized(None, "dflt") == "dflt"
print("test_updates: OK")
