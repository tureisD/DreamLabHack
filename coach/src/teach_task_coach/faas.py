"""Durable dataset versions and explicit Dream Labs FaaS submissions."""

from __future__ import annotations

import dataclasses
import datetime as dt
import hashlib
import json
import os
import shutil
import sqlite3
import time
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Literal

from dream import DreamClient, fine_tuning
from dream.errors import (
    DreamAuthError,
    DreamConfigError,
    DreamDatasetError,
    DreamProtocolError,
    DreamServerError,
    DreamUploadError,
)
from pydantic import BaseModel, Field

from teach_task_coach.demos import DemoStore, read_demo
from teach_task_coach.storage import CoachDatabase
from teach_task_coach.tasks import TaskStore

DatasetStatus = Literal["pending_validation", "validated", "failed"]
TrainingStatus = Literal[
    "pending_upload", "processing", "pending_training", "training", "succeeded", "failed",
    "retry_requested", "retry_reconcile", "submit_reconcile"
]


class DatasetVersion(BaseModel):
    id: str
    task_id: str
    embodiment_name: str
    demo_ids: list[str]
    local_path: str
    remote_slug: str
    remote_id: str | None
    remote_name: str | None
    status: DatasetStatus
    validation_report: dict[str, Any] | None
    error: str | None
    created_at: str


class FineTuneRequest(BaseModel):
    steps: int = Field(default=1000, ge=500, le=10000, multiple_of=100)
    lr_schedule: Literal["cosine", "constant"] = "cosine"
    base_share: Literal[0.0, 0.5] = 0.5
    use_eef: bool = False
    resume_from: str | None = None


class FineTuneRecord(FineTuneRequest):
    failed_phase: str | None = None
    failed_at: str | None = None
    failure_reason: str | None = None
    retry_used: bool = False
    id: str
    dataset_version_id: str
    suffix: str
    remote_job_id: str | None
    remote_status: str | None = None
    checkpoint: str | None
    status: TrainingStatus
    failure_phase: str | None = None
    error: str | None
    created_at: str


class FineTuneAlreadySubmitted(ValueError):
    pass


def _now() -> str:
    return dt.datetime.now(dt.UTC).isoformat(timespec="seconds")


class FaaSStore:
    def __init__(self, data_dir: Path | None = None) -> None:
        self.db = CoachDatabase(data_dir)

    def _schema(self, connection: sqlite3.Connection) -> None:
        connection.executescript(
            """CREATE TABLE IF NOT EXISTS dataset_versions (
                id TEXT PRIMARY KEY,
                task_id TEXT NOT NULL REFERENCES tasks(id),
                embodiment_name TEXT NOT NULL,
                demo_ids_json TEXT NOT NULL,
                local_path TEXT NOT NULL,
                remote_slug TEXT NOT NULL UNIQUE,
                remote_id TEXT,
                remote_name TEXT,
                status TEXT NOT NULL,
                validation_report_json TEXT,
                error TEXT,
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS fine_tune_jobs (
                id TEXT PRIMARY KEY,
                dataset_version_id TEXT NOT NULL REFERENCES dataset_versions(id),
                suffix TEXT NOT NULL UNIQUE,
                steps INTEGER NOT NULL,
                lr_schedule TEXT NOT NULL,
                base_share REAL NOT NULL,
                use_eef INTEGER NOT NULL,
                remote_job_id TEXT,
                remote_status TEXT,
                checkpoint TEXT,
                status TEXT NOT NULL,
                failure_phase TEXT,
                error TEXT,
                created_at TEXT NOT NULL,
                resume_from TEXT
            );
            CREATE INDEX IF NOT EXISTS datasets_task_id ON dataset_versions(task_id);
            CREATE INDEX IF NOT EXISTS finetunes_dataset_id ON fine_tune_jobs(dataset_version_id);
            """
        )
        columns = {row["name"] for row in connection.execute("PRAGMA table_info(fine_tune_jobs)")}
        for name, sql_type in (
            ("resume_from", "TEXT"), ("remote_status", "TEXT"), ("failure_phase", "TEXT"),
            ("failed_phase", "TEXT"), ("failed_at", "TEXT"), ("failure_reason", "TEXT"),
            ("retry_used", "INTEGER NOT NULL DEFAULT 0"),
        ):
            if name not in columns:
                connection.execute(f"ALTER TABLE fine_tune_jobs ADD COLUMN {name} {sql_type}")

    def create_dataset(self, task_id: str, embodiment_name: str, demo_ids: list[str]) -> DatasetVersion:
        identifier = uuid.uuid4().hex
        version = DatasetVersion(
            id=identifier,
            task_id=task_id,
            embodiment_name=embodiment_name,
            demo_ids=demo_ids,
            local_path=str((self.db.data_dir / "datasets" / identifier).resolve()),
            remote_slug=f"ttc-{identifier[:20]}",
            remote_id=None,
            remote_name=None,
            status="pending_validation",
            validation_report=None,
            error=None,
            created_at=_now(),
        )
        with self.db.connect() as connection:
            self._schema(connection)
            connection.execute(
                "INSERT INTO dataset_versions VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    version.id, version.task_id, version.embodiment_name,
                    json.dumps(version.demo_ids), version.local_path, version.remote_slug,
                    None, None, version.status, None, None, version.created_at,
                ),
            )
        return version

    def get_dataset(self, version_id: str) -> DatasetVersion | None:
        with self.db.connect() as connection:
            self._schema(connection)
            row = connection.execute(
                "SELECT * FROM dataset_versions WHERE id = ?", (version_id,)
            ).fetchone()
        return None if row is None else self._dataset(row)

    def list_datasets(self, task_id: str | None = None) -> list[DatasetVersion]:
        with self.db.connect() as connection:
            self._schema(connection)
            rows = connection.execute(
                "SELECT * FROM dataset_versions WHERE (? IS NULL OR task_id = ?) ORDER BY created_at DESC, rowid DESC",
                (task_id, task_id),
            ).fetchall()
        return [self._dataset(row) for row in rows]

    def update_dataset(self, version_id: str, **changes: Any) -> DatasetVersion:
        allowed = {"remote_id", "remote_name", "status", "validation_report_json", "error"}
        if not changes.keys() <= allowed:
            raise ValueError("Unsupported dataset field update.")
        with self.db.connect() as connection:
            self._schema(connection)
            assignments = ", ".join(f"{key} = ?" for key in changes)
            connection.execute(
                f"UPDATE dataset_versions SET {assignments} WHERE id = ?",
                (*changes.values(), version_id),
            )
        result = self.get_dataset(version_id)
        assert result is not None
        return result

    def create_finetune(self, version_id: str, settings: FineTuneRequest) -> FineTuneRecord:
        identifier = uuid.uuid4().hex
        job = FineTuneRecord(
            id=identifier,
            dataset_version_id=version_id,
            suffix=f"ttc-{identifier[:20]}",
            remote_job_id=None,
            remote_status=None,
            checkpoint=None,
            status="pending_upload",
            failure_phase=None,
            error=None,
            created_at=_now(),
            **settings.model_dump(),
        )
        with self.db.connect() as connection:
            self._schema(connection)
            inserted = connection.execute(
                """INSERT INTO fine_tune_jobs
                   (id, dataset_version_id, suffix, steps, lr_schedule, base_share, use_eef,
                    remote_job_id, remote_status, checkpoint, status, failure_phase, error, created_at, resume_from)
                   SELECT ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
                   WHERE NOT EXISTS (
                       SELECT 1 FROM fine_tune_jobs
                       WHERE (? IS NULL AND dataset_version_id = ?) OR resume_from = ?
                   )""",
                (
                    job.id, job.dataset_version_id, job.suffix, job.steps, job.lr_schedule,
                    job.base_share, int(job.use_eef), None, None, None, job.status, None, None,
                    job.created_at, job.resume_from,
                    job.resume_from, job.dataset_version_id, job.resume_from,
                ),
            )
            if not inserted.rowcount:
                raise FineTuneAlreadySubmitted(
                    "This checkpoint already has a continuation job." if job.resume_from
                    else "This dataset version already has a fine-tune job."
                )
        return job

    def get_finetune(self, job_id: str) -> FineTuneRecord | None:
        with self.db.connect() as connection:
            self._schema(connection)
            row = connection.execute("SELECT * FROM fine_tune_jobs WHERE id = ?", (job_id,)).fetchone()
        return None if row is None else self._finetune(row)

    def list_finetunes(self, task_id: str | None = None) -> list[FineTuneRecord]:
        with self.db.connect() as connection:
            self._schema(connection)
            rows = connection.execute(
                """SELECT fine_tune_jobs.* FROM fine_tune_jobs
                   JOIN dataset_versions ON dataset_versions.id = fine_tune_jobs.dataset_version_id
                   WHERE (? IS NULL OR dataset_versions.task_id = ?)
                   ORDER BY fine_tune_jobs.created_at DESC, fine_tune_jobs.rowid DESC""",
                (task_id, task_id),
            ).fetchall()
        return [self._finetune(row) for row in rows]

    def claim(self, job_id: str, expected: str, target: str) -> bool:
        with self.db.connect() as db:
            self._schema(db)
            return db.execute(
                "UPDATE fine_tune_jobs SET status = ? WHERE id = ? AND status = ?",
                (target, job_id, expected),
            ).rowcount == 1

    def request_retry(self, job_id: str) -> FineTuneRecord:
        job = self.get_finetune(job_id)
        if not job:
            raise KeyError(job_id)
        version = self.get_dataset(job.dataset_version_id)
        if not version or version.status != 'validated' or not version.remote_id or not version.remote_name or job.remote_job_id or job.checkpoint:
            raise ValueError('No validated remote dataset available for processing retry.')
        verify_manifest(version)
        with self.db.connect() as db:
            self._schema(db)
            updated = db.execute(
                """UPDATE fine_tune_jobs SET status='retry_requested', retry_used=1,
                          failed_at=COALESCE(failed_at, ?), failure_reason=COALESCE(failure_reason, error),
                          error=NULL
                   WHERE id=? AND status='failed' AND retry_used=0
                         AND remote_job_id IS NULL AND checkpoint IS NULL
                         AND (failed_phase='processing'
                              OR (failure_phase='dataset_processing' AND remote_status='failed'))""",
                (_now(), job_id),
            )
            if updated.rowcount != 1:
                raise ValueError('No confirmed, untried processing failure. No new submission was authorized.')
        result = self.get_finetune(job_id)
        assert result is not None
        return result

    def update_finetune(self, job_id: str, **changes: Any) -> FineTuneRecord:
        allowed = {
            "remote_job_id", "remote_status", "checkpoint", "status", "failure_phase", "error",
            "failed_phase", "failed_at", "failure_reason",
        }
        if not changes.keys() <= allowed:
            raise ValueError("Unsupported fine-tune field update.")
        with self.db.connect() as connection:
            self._schema(connection)
            assignments = ", ".join(f"{key} = ?" for key in changes)
            connection.execute(
                f"UPDATE fine_tune_jobs SET {assignments} WHERE id = ?",
                (*changes.values(), job_id),
            )
        result = self.get_finetune(job_id)
        assert result is not None
        return result

    @staticmethod
    def _dataset(row: sqlite3.Row) -> DatasetVersion:
        return DatasetVersion(
            id=row["id"], task_id=row["task_id"], embodiment_name=row["embodiment_name"],
            demo_ids=json.loads(row["demo_ids_json"]), local_path=row["local_path"],
            remote_slug=row["remote_slug"], remote_id=row["remote_id"],
            remote_name=row["remote_name"], status=row["status"],
            validation_report=(json.loads(row["validation_report_json"]) if row["validation_report_json"] else None),
            error=row["error"], created_at=row["created_at"],
        )

    @staticmethod
    def _finetune(row: sqlite3.Row) -> FineTuneRecord:
        return FineTuneRecord(
            id=row["id"], dataset_version_id=row["dataset_version_id"], suffix=row["suffix"],
            steps=row["steps"], lr_schedule=row["lr_schedule"], base_share=row["base_share"],
            use_eef=bool(row["use_eef"]), remote_job_id=row["remote_job_id"],
            remote_status=row["remote_status"],
            checkpoint=row["checkpoint"], status=row["status"],
            failure_phase=row["failure_phase"], error=row["error"],
            created_at=row["created_at"], resume_from=row["resume_from"],
            failed_phase=row["failed_phase"], failed_at=row["failed_at"],
            failure_reason=row["failure_reason"], retry_used=bool(row["retry_used"]),
        )


class DreamGateway:
    """The narrow public-SDK seam; replaceable with a fake in tests."""

    @property
    def client(self) -> DreamClient:
        # Reload the SDK credentials after the local account wizard saves a key.
        return DreamClient()

    def embodiments(self) -> list[Any]:
        return self.client.get_embodiments()

    def validate(self, path: str, config: dict[str, Any]) -> Any:
        return self.client.validate_dataset(path, config)

    def datasets(self) -> list[Any]:
        return self.client.get_datasets()

    def upload(self, path: str, name: str, embodiment: str) -> Any:
        return self.client.upload_dataset(path, name, embodiment)

    def dataset_status(self, dataset_id: str) -> Any:
        return self.client.get_dataset_status(dataset_id)

    def retry_dataset(self, dataset_id: str) -> Any:
        return self.client.retry_dataset(dataset_id)

    def finetunes(self) -> list[dict[str, Any]]:
        return fine_tuning.list()

    def submit(self, dataset: str, suffix: str, settings: FineTuneRequest) -> dict[str, Any]:
        return self.client.finetune(
            dataset,
            suffix,
            steps=settings.steps,
            lr_schedule=settings.lr_schedule,
            base_share=settings.base_share,
            use_eef=settings.use_eef,
            resume_from=settings.resume_from,
        )

    def finetune_status(self, job_id: str) -> dict[str, Any]:
        return self.client.get_finetuning_status(job_id)


def _files_manifest(root: Path) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.name.startswith(".coach-"):
            continue
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
        entries.append({"path": path.relative_to(root).as_posix(), "sha256": digest.hexdigest(), "bytes": path.stat().st_size})
    return entries


def verify_manifest(version: DatasetVersion) -> None:
    root = Path(version.local_path)
    manifest = json.loads((root / '.coach-manifest.json').read_text(encoding='utf-8'))
    if (manifest.get('task_id') != version.task_id or manifest.get('demo_ids') != version.demo_ids
            or manifest.get('files') != _files_manifest(root)):
        raise ValueError('Dataset files or identity changed after validation.')


class FaaSWorker:
    def __init__(
        self, store: FaaSStore, tasks: TaskStore, demos: DemoStore, gateway: DreamGateway
    ) -> None:
        self.store, self.tasks, self.demos, self.gateway = store, tasks, demos, gateway

    def tick(self) -> int:
        """Advance each unfinished dataset/job one external step, then return work attempted."""
        attempted = 0
        for dataset in self.store.list_datasets():
            if dataset.status == "pending_validation":
                task = self.tasks.get_task(dataset.task_id)
                if task is None or task.offline_mode:
                    self.store.update_dataset(dataset.id, status="failed", error="Offline or missing task cannot enter Dream validation.")
                    continue
                attempted += 1
                self._validate(dataset)
        for job in self.store.list_finetunes():
            version = self.store.get_dataset(job.dataset_version_id)
            task = None if version is None else self.tasks.get_task(version.task_id)
            if task is None or task.offline_mode:
                if job.status not in ("failed", "succeeded"):
                    self.store.update_finetune(job.id, status="failed", error="Offline or missing task cannot contact Dream training.")
                continue
            if job.status in ("pending_upload", "processing", "pending_training", "training", "retry_requested", "retry_reconcile", "submit_reconcile"):
                attempted += 1
                self._advance(job)
        return attempted

    def _validate(self, version: DatasetVersion) -> None:
        task = self.tasks.get_task(version.task_id)
        if task is None or task.offline_mode:
            self.store.update_dataset(version.id, status="failed", error="Offline or missing task cannot enter Dream validation.")
            return
        source_demos = [self.demos.get(demo_id) for demo_id in version.demo_ids]
        if any(
            demo is None or demo.task_id != version.task_id
            or demo.decision != "keep" or not demo.valid
            or demo.origin not in ("human", "scripted_reference")
            for demo in source_demos
        ):
            self.store.update_dataset(version.id, status="failed", error="Dataset contains a missing, changed, or ineligible demonstration.")
            return
        try:
            embodiment = next(
                (body for body in self.gateway.embodiments() if body.name == version.embodiment_name),
                None,
            )
            if embodiment is None:
                self.store.update_dataset(version.id, status="failed", error="Embodiment is not in this Dream account.")
                return
            root = Path(version.local_path)
            if not root.exists():
                size = sum(
                    path.stat().st_size
                    for demo in source_demos if demo is not None
                    for path in Path(demo.source_path).rglob("*") if path.is_file()
                )
                root.parent.mkdir(parents=True, exist_ok=True)
                if shutil.disk_usage(root.parent).free < size * 2:
                    self.store.update_dataset(version.id, status="failed", error="Not enough disk space for dataset and upload zip.")
                    return
                temporary = root.with_name(root.name + ".tmp")
                if temporary.exists():
                    shutil.rmtree(temporary)
                temporary.mkdir()
                for demo in source_demos:
                    assert demo is not None
                    copied = temporary / demo.id
                    shutil.copytree(demo.source_path, copied)
                    receipt = {
                        "origin": demo.origin,
                        "source_identity": demo.source_identity,
                        "source_episode_id": demo.source_episode_id,
                        "task_id": demo.task_id,
                    }
                    (copied / "coach-demo.json").write_text(json.dumps(receipt, sort_keys=True), encoding="utf-8")
                    checked = read_demo(copied, version.task_id)
                    expected = set(embodiment.embodiment_config.get('video', {}).values())
                    if (not checked.valid or checked.origin not in ("human", "scripted_reference")
                            or checked.source_identity != demo.source_identity
                            or checked.evidence_sha256 != demo.evidence_sha256
                            or set(checked.camera_keys) != expected or checked.task_text != demo.task_text):
                        raise ValueError('Frozen demonstration failed provenance, frame, action, task or camera-role checks.')
                manifest = {"task_id": version.task_id, "demo_ids": version.demo_ids, "files": _files_manifest(temporary)}
                (temporary / ".coach-manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
                os.replace(temporary, root)
            report = self.gateway.validate(str(root), embodiment.embodiment_config)
            report_data = dataclasses.asdict(report)
            self.store.update_dataset(
                version.id,
                status="validated" if report.ok else "failed",
                validation_report_json=json.dumps(report_data),
                error=None if report.ok else report.error,
            )
        except (DreamAuthError, DreamProtocolError) as exc:
            self.store.update_dataset(version.id, error=f"{type(exc).__name__}: configure or reconnect Dream credentials.")
        except DreamServerError as exc:
            if getattr(exc, "retryable", False):
                self.store.update_dataset(version.id, error="Dream data service is unavailable; retrying.")
            else:
                self.store.update_dataset(version.id, status="failed", error=str(exc))
        except (DreamConfigError, DreamDatasetError, OSError, ValueError) as exc:
            self.store.update_dataset(version.id, status="failed", error=str(exc))

    def _advance(self, job: FineTuneRecord) -> None:
        version = self.store.get_dataset(job.dataset_version_id)
        if version is None:
            self.store.update_finetune(job.id, status="failed", error="Training dataset is missing.")
            return
        task = self.tasks.get_task(version.task_id)
        if task is None or task.offline_mode:
            self.store.update_finetune(job.id, status="failed", error="Offline or missing task cannot contact Dream training.")
            return
        phase = {
            "pending_upload": "upload", "processing": "dataset_processing",
            "retry_requested": "dataset_processing", "retry_reconcile": "dataset_processing",
            "pending_training": "training_submission", "submit_reconcile": "training_submission",
            "training": "training",
        }.get(job.status)
        try:
            if job.status == "pending_upload":
                self._upload(job, version)
            elif job.status == "processing":
                self._processing(job, version)
            elif job.status in ('retry_requested','retry_reconcile'):
                self._retry_processing(job, version)
            elif job.status in ('pending_training','submit_reconcile'):
                self._start_training(job, version)
            elif job.status == "training":
                self._training(job)
        except (DreamAuthError, DreamProtocolError, DreamUploadError, TimeoutError, ConnectionError) as exc:
            self.store.update_finetune(job.id, error=f"{type(exc).__name__}: check credentials or connection; reconcile remote state before another action.")
        except DreamServerError as exc:
            if getattr(exc, "retryable", False):
                self.store.update_finetune(job.id, error=f"{type(exc).__name__}: service unavailable; retrying.")
            else:
                self.store.update_finetune(
                    job.id, status="failed", failure_phase=phase, error=str(exc)
                )
        except (DreamConfigError, DreamDatasetError, OSError, ValueError) as exc:
            self.store.update_finetune(
                job.id, status="failed", failure_phase=phase, error=str(exc)
            )

    def _upload(self, job: FineTuneRecord, version: DatasetVersion) -> None:
        verify_manifest(version)
        remote = next(
            (
                item for item in self.gateway.datasets()
                if item.name.rsplit("/", 1)[-1] == version.remote_slug
                and item.embodiment == version.embodiment_name
            ),
            None,
        )
        if remote is None or remote.status == 'uploading':
            remote = self.gateway.upload(version.local_path, version.remote_slug, version.embodiment_name)
        self.store.update_dataset(version.id, remote_id=remote.id, remote_name=remote.name)
        self.store.update_finetune(
            job.id, status="processing", remote_status=remote.status,
            failure_phase=None, error=None,
        )

    def _processing(self, job: FineTuneRecord, version: DatasetVersion) -> None:
        if version.remote_id is None:
            self.store.update_finetune(job.id, status="pending_upload")
            return
        remote = self.gateway.dataset_status(version.remote_id)
        if remote.status == "processed":
            self.store.update_finetune(
                job.id, status="pending_training", remote_status=remote.status,
                failure_phase=None, error=None,
            )
        elif remote.status == "failed":
            reason = remote.error or "Dataset processing failed."
            self.store.update_finetune(
                job.id, status="failed", remote_status=remote.status,
                failure_phase="dataset_processing", failed_phase="processing",
                failed_at=job.failed_at or _now(), failure_reason=job.failure_reason or reason,
                error=reason,
            )
        elif remote.status in ("uploading", "ready_to_process", "processing"):
            self.store.update_finetune(job.id, remote_status=remote.status, error=None)
        else:
            self.store.update_finetune(
                job.id, status="failed", remote_status=remote.status,
                failure_phase="dataset_processing",
                error=f"Unexpected Dream dataset status: {remote.status}. Create a new dataset version.",
            )
    def _retry_processing(self, job: FineTuneRecord, version: DatasetVersion) -> None:
        verify_manifest(version)
        if not version.remote_id:
            raise ValueError("Missing remote dataset ID.")
        expected = (version.remote_id, version.remote_name, version.embodiment_name)
        remote = self.gateway.dataset_status(version.remote_id)
        if (remote.id, remote.name, remote.embodiment) != expected:
            raise ValueError("Remote dataset identity mismatch. Processing was not requested.")
        if remote.status == "failed" and job.status == "retry_requested":
            if not self.store.claim(job.id, "retry_requested", "retry_reconcile"):
                return
            remote = self.gateway.retry_dataset(version.remote_id)
            if (remote.id, remote.name, remote.embodiment) != expected:
                raise ValueError("Retry returned a different remote dataset.")
            if remote.status == "failed":
                self.store.update_finetune(
                    job.id, status="failed", remote_status=remote.status,
                    failure_phase="dataset_processing", error=remote.error or "Processing retry failed.",
                )
                return
        if remote.status == "processed":
            self.store.update_finetune(
                job.id, status="pending_training", remote_status=remote.status, failure_phase=None, error=None,
            )
        elif remote.status in ("ready_to_process", "processing"):
            self.store.update_finetune(
                job.id, status="processing", remote_status=remote.status, failure_phase=None, error=None,
            )
        else:
            self.store.update_finetune(
                job.id, remote_status=remote.status, error="Waiting for Dream to confirm the retry outcome.",
            )

    def _start_training(self, job: FineTuneRecord, version: DatasetVersion) -> None:
        existing = next((item for item in self.gateway.finetunes() if item.get("suffix") == job.suffix), None)
        if existing is None:
            if job.status == 'submit_reconcile':
                self.store.update_finetune(job.id,error='Submission outcome unknown: waiting for this suffix; will not submit again.')
                return
            verify_manifest(version)
            if not self.store.claim(job.id,'pending_training','submit_reconcile'):return
            assert version.remote_name is not None
            existing = self.gateway.submit(
                version.remote_name,
                job.suffix,
                FineTuneRequest(
                    steps=job.steps, lr_schedule=job.lr_schedule,
                    base_share=job.base_share, use_eef=job.use_eef,
                    resume_from=job.resume_from,
                ),
            )
        self.store.update_finetune(
            job.id, remote_job_id=existing["id"], remote_status=existing.get("status"),
            status="training", failure_phase=None, error=None,
        )

    def _training(self, job: FineTuneRecord) -> None:
        if job.remote_job_id is None:
            self.store.update_finetune(job.id, status="pending_training")
            return
        remote = self.gateway.finetune_status(job.remote_job_id)
        if remote.get("fine_tuned_model"):
            self.store.update_finetune(
                job.id, status="succeeded", remote_status=remote.get("status"), failure_phase=None,
                checkpoint=remote["fine_tuned_model"], error=None
            )
        elif remote.get("status") in ("failed", "cancelled"):
            self.store.update_finetune(
                job.id, status="failed", remote_status=remote["status"], failure_phase="training",
                error=remote.get("error") or remote["status"],
            )
        elif remote.get("status"):
            self.store.update_finetune(job.id, remote_status=remote["status"], error=None)


def run_worker(store: FaaSStore, tasks: TaskStore, demos: DemoStore, interval_s: float = 30) -> None:
    with exclusive_worker_lock(store.db.data_dir / "worker.lock"):
        gateway = DreamGateway()
        worker = FaaSWorker(store, tasks, demos, gateway)
        while True:
            worker.tick()
            time.sleep(interval_s)


@contextmanager
def exclusive_worker_lock(path: Path) -> Iterator[None]:
    """Permit only one local worker; the OS releases the lock after a crash."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+b") as stream:
        if stream.tell() == 0:
            stream.write(b"\0")
            stream.flush()
        stream.seek(0)
        try:
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            raise RuntimeError("Another Teach it a task worker is already running.") from exc
        try:
            yield
        finally:
            stream.seek(0)
            if os.name == "nt":
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)
