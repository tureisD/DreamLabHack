"""Check provenance with real on-disk distribution metadata and install layouts."""

import json
from hashlib import sha256

import pytest

from dreamlab.evaluation import provenance


def _install_metadata(installation, direct_url, monkeypatch):
    metadata = installation / "dreamlab_hack-0.1.0.dist-info"
    metadata.mkdir(parents=True)
    (metadata / "METADATA").write_text(
        "Metadata-Version: 2.1\nName: dreamlab-hack\nVersion: 0.1.0\n", encoding="utf-8"
    )
    if direct_url is not None:
        (metadata / "direct_url.json").write_text(json.dumps(direct_url), encoding="utf-8")
    monkeypatch.syspath_prepend(str(installation))


def test_editable_source_hash_changes_for_dirty_or_untracked_python_files(tmp_path, monkeypatch):
    root = tmp_path / "checkout #1"
    package = root / "src" / "dreamlab"
    package.mkdir(parents=True)
    (root / "uv.lock").write_bytes(b"checkout lock\n")
    (package / "uv.lock").write_bytes(b"wheel lock\n")
    _install_metadata(
        tmp_path / "site-packages",
        {"url": root.as_uri(), "dir_info": {"editable": True}},
        monkeypatch,
    )
    source = package / "engine.py"
    source.write_bytes(b"mode = 1\n")
    before = provenance._source_identity(package)
    source.write_bytes(b"mode = 2\n")
    dirty = provenance._source_identity(package)
    (package / "new.py").write_bytes(b"mode = 1\n")
    new = provenance._source_identity(package)
    assert len({identity["tree_sha256"] for identity in (before, dirty, new)}) == 3
    assert before["uv_lock"]["origin"] == "source_tree"
    assert before["uv_lock"]["sha256"] == sha256(b"checkout lock\n").hexdigest()
    assert before["git_revision"] is None


@pytest.mark.parametrize("kind", ["registry", "local-wheel", "not-editable", "unrelated-editable"])
def test_target_install_in_other_project_src_uses_only_packaged_lock(tmp_path, monkeypatch, kind):
    project = tmp_path / "other-project"
    installation = project / "src"
    package = installation / "dreamlab"
    package.mkdir(parents=True)
    (project / "pyproject.toml").write_text('[project]\nname="other-project"\n', encoding="utf-8")
    (project / "uv.lock").write_bytes(b"unrelated lock\r\n")
    (project / ".git").mkdir()
    shipped = b"bytes embedded in wheel\n"
    lock = package / "uv.lock"
    lock.write_bytes(shipped)
    editable_root = tmp_path / "other-checkout"
    (editable_root / "src" / "dreamlab").mkdir(parents=True)
    direct_url = {
        "registry": None,
        "local-wheel": {
            "url": (tmp_path / "dreamlab_hack-0.1.0-py3-none-any.whl").as_uri(),
            "archive_info": {},
        },
        "not-editable": {"url": project.as_uri(), "dir_info": {"editable": False}},
        "unrelated-editable": {"url": editable_root.as_uri(), "dir_info": {"editable": True}},
    }[kind]
    _install_metadata(installation, direct_url, monkeypatch)
    monkeypatch.setattr(provenance, "_git_revision", lambda _: pytest.fail("not a source install"))
    identity = provenance._source_identity(package)
    assert identity["git_revision"] is None
    assert identity["uv_lock"] == {
        "path": "uv.lock",
        "origin": "wheel",
        "sha256": sha256(shipped).hexdigest(),
    }
    lock.unlink()
    assert provenance._source_identity(package)["uv_lock"]["sha256"] is None
