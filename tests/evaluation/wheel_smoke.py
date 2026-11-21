"""Run after `uv build`: install the wheel away from the checkout and verify it."""

import json
import subprocess
import sys
from hashlib import sha256
from pathlib import Path
from tempfile import TemporaryDirectory
from zipfile import ZipFile

ROOT = Path(__file__).resolve().parents[2]
FIXTURE = ROOT / "tests" / "fixtures" / "evaluation_request.json"
REPORT = Path(__file__).parent / "examples" / "evaluation_report.json"
PROBE = """
import sys
from hashlib import sha256
from pathlib import Path

lock, fixture, *target = map(Path, sys.argv[1:])
if target:
    sys.path.insert(0, str(target[0]))

from dreamlab.contracts import EvaluationRequest
from dreamlab.evaluation import provenance
from dreamlab.evaluation.engine import StatisticalEvaluator

package = Path(provenance.__file__).resolve().parents[1]
if target:
    assert package == (target[0] / "dreamlab").resolve(), package
else:
    assert package.is_relative_to(Path(sys.prefix).resolve()), package
shipped = (package / "uv.lock").read_bytes()
assert shipped == lock.read_bytes()
identity = provenance._source_identity(package)
assert identity["uv_lock"] == {
    "path": "uv.lock", "origin": "wheel", "sha256": sha256(shipped).hexdigest(),
}, identity
assert identity["git_revision"] is None, identity
request = EvaluationRequest.model_validate_json(fixture.read_bytes())
assert StatisticalEvaluator().evaluate(request).decision == "inconclusive"
"""


def _run(cwd, *args):
    subprocess.run(args, cwd=cwd, check=True, timeout=180)


def main():
    [wheel] = (ROOT / "dist").glob("dreamlab_hack-*.whl")
    lock = ROOT / "uv.lock"
    shipped = lock.read_bytes()
    with ZipFile(wheel) as archive:
        assert archive.read("dreamlab/uv.lock") == shipped

    with TemporaryDirectory(prefix="dream-eval-wheel-") as directory:
        work = Path(directory)
        requirements = work / "requirements.txt"
        _run(
            ROOT,
            "uv",
            "export",
            "--locked",
            "--extra",
            "eval",
            "--no-dev",
            "--no-emit-project",
            "--output-file",
            requirements,
            "--quiet",
        )
        env = work / "venv"
        _run(work, "uv", "venv", "--python", sys.executable, env)
        windows = sys.platform == "win32"
        scripts = env / ("Scripts" if windows else "bin")
        python = scripts / ("python.exe" if windows else "python")
        _run(work, "uv", "pip", "sync", "--python", python, "--require-hashes", requirements)
        _run(work, "uv", "pip", "install", "--python", python, "--no-deps", wheel)
        _run(work, python, "-I", "-c", PROBE, lock, FIXTURE)

        project = work / "unrelated-project"
        project.mkdir()
        (project / "pyproject.toml").write_text('[project]\nname="unrelated"\n', encoding="utf-8")
        (project / "uv.lock").write_bytes(b"unrelated project's lock\n")
        target = project / "src"  # `pip install --target` may be pointed at another project's src.
        _run(
            work, "uv", "pip", "install", "--python", python, "--target", target, "--no-deps", wheel
        )
        _run(work, python, "-I", "-c", PROBE, lock, FIXTURE, target)

        command = scripts / ("dream-eval.exe" if windows else "dream-eval")
        output = work / "result"
        result = subprocess.run(
            [command, "evaluate", "--input", "-", "--output-dir", output],
            cwd=work,
            input=FIXTURE.read_bytes(),
            capture_output=True,
            timeout=30,
            check=False,
        )
        if sys.platform == "linux":
            assert result.returncode == 0, result.stderr
            assert result.stdout == result.stderr == b""
            assert (output / "request.raw.json").read_bytes() == FIXTURE.read_bytes()
            assert (output / "report.json").read_bytes() == REPORT.read_bytes()
            manifest = json.loads((output / "manifest.json").read_bytes())
            assert manifest["source"]["uv_lock"] == {
                "path": "uv.lock",
                "origin": "wheel",
                "sha256": sha256(shipped).hexdigest(),
            }
        else:
            assert result.returncode == 5 and not output.exists(), result.stderr
            assert b"Secure artifact publication is supported only on Linux" in result.stderr
    print("Fresh wheel: lock bytes, target installation and platform CLI behavior verified.")


if __name__ == "__main__":
    main()
