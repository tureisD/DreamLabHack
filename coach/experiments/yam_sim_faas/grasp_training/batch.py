"""Verify a frozen simulator dataset or prepare it on the current Dream account."""
import argparse
import hashlib
import json
import os
import time
from getpass import getpass
from pathlib import Path
from tempfile import TemporaryDirectory
from zipfile import ZipFile

from dream import DreamClient, datasets

ROOT = Path(__file__).resolve().parent
HOLDOUT = {901, 902, 903, 904}
CONFIRMATION = {905, 906, 907, 908}
SEEDS = {
    "control": set(range(41, 49)),
    "varied": set(range(41, 49)) | set(range(101, 117)),
    "independent": set(range(201, 225)),
}


def verify(batch, destination, bundle_dir=ROOT):
    manifest = json.loads((bundle_dir / f"{batch}.json").read_text(encoding="utf-8"))
    archive = bundle_dir / f"{batch}.zip"
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    if digest != manifest["sha256"]:
        raise ValueError("Archive differs from its committed manifest. Fetch the complete batch.")
    seeds = SEEDS[batch]
    sessions = manifest["sessions"]
    if {s["seed"] for s in sessions} != seeds or len(sessions) != len(seeds) or seeds & (HOLDOUT | CONFIRMATION):
        raise ValueError("Training split differs from the frozen protocol")
    with ZipFile(archive) as package:
        for name in package.namelist():
            path = (destination / name).resolve()
            if not path.is_relative_to(destination) or path.relative_to(destination).parts[0] not in {
                f"apple-seed-{seed}" for seed in seeds
            }:
                raise ValueError(f"Unexpected archive entry: {name}")
        package.extractall(destination)
    config = manifest["embodiment"]
    report = datasets.validate_dataset(str(destination), config)
    if not report.ok or report.episodes != len(seeds) or report.frames != manifest["frames"]:
        raise ValueError(f"Dataset validation failed: {report}")
    print(f"{batch}: {report.episodes} episodes, {report.frames} rows, {report.fps} Hz. SHA-256 {digest}", flush=True)
    return config, f"apple-grasp-{batch}-{digest[:12]}"


def prepare(root, config, slug, account, episodes):
    key = os.environ.get("DREAM_API_KEY") or getpass("Dream API key for this account (hidden): ").strip()
    if not key:
        raise ValueError("A Dream API key is required for upload")
    client = DreamClient(api_key=key)
    bodies = client.get_embodiments()
    if any(body.name.split("/", 1)[0] != account for body in bodies):
        raise ValueError("The key belongs to a different Dream account")
    name = f"{account}/yam-simulator"
    body = next((b for b in bodies if b.name == name), None)
    if body is None:
        body = client.add_embodiment("yam-simulator", config)
    if body.name != name or any(body.embodiment_config.get(k) != v for k, v in config.items()):
        raise ValueError(f"Expected the matching YAM embodiment on {account}; verify the account and config.")
    full_name = f"{account}/{slug}"
    data = next((d for d in client.get_datasets() if d.name == full_name), None)
    if data is None:
        data = client.upload_dataset(str(root), slug, body.name)
    if data.embodiment != name or data.episodes != episodes:
        raise ValueError(f"Unexpected remote dataset metadata for {data.name}")
    if data.status == "uploading":
        raise RuntimeError(f"Prior upload is incomplete. Check the Datasets page for {data.id} before retrying.")
    print(f"{data.name}  {data.id}  {data.status}", flush=True)
    previous = data.status
    while data.status not in {"processed", "failed"}:
        time.sleep(15)
        data = client.get_dataset_status(data.id)
        if data.status != previous:
            print(data.status, flush=True)
            previous = data.status
    if data.status == "failed":
        raise RuntimeError(f"{data.name}: {data.error}")
    print(f"Ready on {account}: {data.name}. Use the Fine-tune form to review the price.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("verify", "prepare"))
    parser.add_argument("batch", choices=SEEDS)
    parser.add_argument("--bundle-dir", type=Path, default=ROOT, help="Directory with the archive and manifest")
    parser.add_argument("--account", help="Dream username on the account receiving the upload")
    args = parser.parse_args()
    if args.action == "prepare" and not args.account:
        parser.error("prepare requires --account YOUR_DREAM_USERNAME")
    with TemporaryDirectory() as staging:
        path = Path(staging).resolve()
        config, slug = verify(args.batch, path, args.bundle_dir)
        if args.action == "prepare":
            prepare(path, config, slug, args.account, len(SEEDS[args.batch]))
