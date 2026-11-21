"""Collect reproducibility metadata for the standalone runner."""

import json
import os
import platform
import subprocess
from hashlib import sha256
from importlib.metadata import PackageNotFoundError, distribution, version
from pathlib import Path
from urllib.parse import urlsplit
from urllib.request import url2pathname

from dreamlab.contracts import EvaluationPlan, EvaluationReport


def _package_version(name: str) -> str | None:
    try:
        return version(name)
    except PackageNotFoundError:
        return None


def _git_revision(checkout: Path) -> str | None:
    if not (checkout / ".git").exists():
        return None
    try:
        result = subprocess.run(
            ["git", "-C", str(checkout), "rev-parse", "--verify", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return result.stdout.strip() or None


def _raise_walk_error(error: OSError) -> None:
    raise error


def _editable_root(package: Path) -> Path | None:
    # A pip --target wheel install can also live in an unrelated project's
    # src/ directory. Only the distribution's editable metadata identifies a checkout.
    try:
        direct_url = distribution("dreamlab-hack").read_text("direct_url.json")
        metadata = json.loads(direct_url) if direct_url is not None else None
        if not isinstance(metadata, dict) or not isinstance(metadata.get("dir_info"), dict):
            return None
        if metadata["dir_info"].get("editable") is not True:
            return None
        url = metadata.get("url")
        if not isinstance(url, str):
            return None
        location = urlsplit(url)
        if location.scheme != "file" or location.query or location.fragment:
            return None
        host = location.netloc
        if host.lower() in {"", "localhost"}:
            path = location.path
        elif os.name == "nt":
            path = f"//{host}{location.path}"
        else:
            return None
        root = Path(url2pathname(path))
        if root.is_absolute():
            root = root.resolve(strict=True)
            if (root / "src" / "dreamlab").resolve(strict=True) == package.resolve(strict=True):
                return root
    except (PackageNotFoundError, OSError, ValueError, RuntimeError):
        return None
    return None


def _source_identity(package: Path) -> dict:
    # Hash the Python source actually installed or imported from the checkout.
    # Git alone would miss tracked edits and as-yet untracked implementation files.
    checksums = {
        (directory / name).relative_to(package).as_posix(): sha256(
            (directory / name).read_bytes()
        ).hexdigest()
        for directory, _, files in package.walk(on_error=_raise_walk_error)
        for name in files
        if name.endswith(".py")
    }
    tree = json.dumps(checksums, sort_keys=True, separators=(",", ":")).encode("utf-8")
    root = _editable_root(package)
    lock = (root if root is not None else package) / "uv.lock"
    try:
        lock_sha256 = sha256(lock.read_bytes()).hexdigest()
    except FileNotFoundError:
        lock_sha256 = None
    return {
        "tree_sha256": sha256(tree).hexdigest(),
        "git_revision": _git_revision(root) if root is not None else None,
        "uv_lock": {
            "path": "uv.lock",
            "origin": "source_tree" if root is not None else "wheel",
            "sha256": lock_sha256,
        },
    }


def build_manifest(
    plan: EvaluationPlan, report: EvaluationReport, *, submitted: bytes, canonical: bytes
) -> dict:
    arm_alpha = plan.alpha
    if plan.mode == "group_sequential":
        arm_alpha /= 2 * len(plan.planned_looks)
    return {
        "schema_version": 1,
        "input": {
            "submitted": {
                "path": "request.raw.json",
                "size_bytes": len(submitted),
                "sha256": sha256(submitted).hexdigest(),
            },
            "canonical": {"path": "request.json", "sha256": sha256(canonical).hexdigest()},
        },
        "plan": plan.model_dump(mode="json"),
        "engine": {
            "version": report.engine_version,
            "method": report.method,
            "settings": {
                "arm_interval_alpha": arm_alpha,
                "difference_interval_alpha": plan.alpha,
                "uses_rng": False,
            },
        },
        "runtime": {
            "python": platform.python_version(),
            "python_implementation": platform.python_implementation(),
            "platform": platform.platform(),
            "packages": {
                name: _package_version(name)
                for name in (
                    "dreamlab-hack",
                    "pydantic",
                    "pydantic-core",
                    "numpy",
                    "scipy",
                    "statsmodels",
                )
            },
        },
        "source": _source_identity(Path(__file__).resolve().parents[1]),
    }
