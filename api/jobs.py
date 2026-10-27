"""Tâches de fond : file à priorité, un seul exécuteur (le classeur ne calcule qu'un scénario
à la fois), événements de progression consommés en SSE.

Priorités : 0 = simulation demandée par l'utilisateur, 1 = sensibilités, 9 = précalcul du
surrogate (découpé en petites tâches pour ne jamais faire attendre l'utilisateur longtemps).
Une nouvelle simulation d'un même ``client_id`` annule celles encore en attente (debounce).
"""
from __future__ import annotations

import itertools
import logging
import queue
import threading
import time
import uuid
from collections.abc import Callable
from typing import Any, Literal

from pydantic import BaseModel, Field

log = logging.getLogger(__name__)

Status = Literal["queued", "running", "done", "error", "cancelled"]
STAGE_QUEUED = "en attente"
STAGE_PHYSICS = "simulation physique"
STAGE_EXCEL = "recalcul Excel"
STAGE_DONE = "terminé"
STAGE_ERROR = "erreur"
STAGE_CANCELLED = "annulé"


class JobEvent(BaseModel):
    job_id: str
    seq: int
    status: Status
    stage: str
    progress: float
    message: str = ""
    result_id: str | None = None
    ts: float = Field(default_factory=time.time)


class Job(BaseModel):
    id: str
    kind: str
    client_id: str | None = None
    status: Status = "queued"
    stage: str = STAGE_QUEUED
    progress: float = 0.0
    result_id: str | None = None
    error: str | None = None
    created_at: float = Field(default_factory=time.time)
    events: list[JobEvent] = Field(default_factory=list)

    @property
    def finished(self) -> bool:
        return self.status in ("done", "error", "cancelled")


class Cancelled(Exception):
    pass


class JobFailed(Exception):
    """Échec d'une tâche qui a tout de même produit un résultat partiel."""

    def __init__(self, message: str, result_id: str | None = None):
        super().__init__(message)
        self.result_id = result_id


class JobContext:
    """Passé à la fonction de la tâche pour publier sa progression."""

    def __init__(self, manager: "JobManager", job: Job):
        self.manager, self.job = manager, job

    def stage(self, stage: str, progress: float, message: str = "") -> None:
        if self.job.status == "cancelled":
            raise Cancelled()
        self.manager._emit(self.job, "running", stage, progress, message)


class JobManager:
    def __init__(self):
        self._queue: queue.PriorityQueue = queue.PriorityQueue()
        self._counter = itertools.count()
        self._jobs: dict[str, Job] = {}
        self._lock = threading.Condition()
        self._thread = threading.Thread(target=self._run, name="twin-jobs", daemon=True)
        self._stopping = False
        self._thread.start()

    # ------------------------------------------------------------------ API
    def submit(self, kind: str, fn: Callable[[JobContext], str | None], priority: int = 0,
               client_id: str | None = None, internal: bool = False) -> Job:
        job = Job(id=uuid.uuid4().hex[:12], kind=kind, client_id=client_id)
        with self._lock:
            if client_id is not None:
                for other in self._jobs.values():
                    if other.client_id == client_id and other.kind == kind and other.status == "queued":
                        self._emit(other, "cancelled", STAGE_CANCELLED, other.progress, "remplacée par une demande plus récente")
            if not internal:
                self._jobs[job.id] = job
                self._emit(job, "queued", STAGE_QUEUED, 0.0)
        self._queue.put((priority, next(self._counter), job, fn))
        return job

    def get(self, job_id: str) -> Job | None:
        return self._jobs.get(job_id)

    def events_since(self, job_id: str, seq: int, timeout: float = 15.0) -> list[JobEvent]:
        """Événements de numéro > seq ; attend jusqu'à ``timeout`` s s'il n'y en a pas."""
        deadline = time.time() + timeout
        with self._lock:
            while True:
                job = self._jobs.get(job_id)
                if job is None:
                    return []
                new = [e for e in job.events if e.seq > seq]
                remaining = deadline - time.time()
                if new or job.finished or remaining <= 0:
                    return new
                self._lock.wait(remaining)

    def wait(self, job_id: str, timeout: float = 600) -> Job:
        deadline = time.time() + timeout
        with self._lock:
            while not self._jobs[job_id].finished:
                remaining = deadline - time.time()
                if remaining <= 0:
                    raise TimeoutError(job_id)
                self._lock.wait(remaining)
            return self._jobs[job_id]

    def run_sync(self, kind: str, fn: Callable[[], Any], priority: int = 0, timeout: float = 600) -> Any:
        """Exécute ``fn`` sur le thread du classeur et attend son résultat."""
        box: dict[str, Any] = {}
        done = threading.Event()

        def task(_ctx):
            try:
                box["value"] = fn()
            except BaseException as exc:  # renvoyée à l'appelant
                box["error"] = exc
            finally:
                done.set()
            return None

        self.submit(kind, task, priority=priority, internal=True)
        if not done.wait(timeout):
            raise TimeoutError(kind)
        if "error" in box:
            raise box["error"]
        return box.get("value")

    def stop(self) -> None:
        self._stopping = True
        self._queue.put((-1, next(self._counter), None, None))
        self._thread.join(timeout=30)

    # ------------------------------------------------------------------ interne
    def _emit(self, job: Job, status: Status, stage: str, progress: float, message: str = "",
              result_id: str | None = None) -> None:
        with self._lock:
            job.status, job.stage, job.progress = status, stage, progress
            if result_id:
                job.result_id = result_id
            if status == "error":
                job.error = message
            job.events.append(JobEvent(job_id=job.id, seq=len(job.events) + 1, status=status, stage=stage,
                                       progress=progress, message=message, result_id=job.result_id))
            self._lock.notify_all()

    def _run(self) -> None:
        while not self._stopping:
            _priority, _n, job, fn = self._queue.get()
            if job is None:
                break
            if job.status == "cancelled":
                continue
            context = JobContext(self, job)
            try:
                with self._lock:
                    job.status = "running"
                result_id = fn(context)
                self._emit(job, "done", STAGE_DONE, 1.0, result_id=result_id)
            except Cancelled:
                self._emit(job, "cancelled", STAGE_CANCELLED, job.progress)
            except JobFailed as exc:
                self._emit(job, "error", STAGE_ERROR, job.progress, str(exc), result_id=exc.result_id)
            except Exception as exc:  # erreur publiée dans la tâche
                log.exception("tâche %s en erreur", job.id)
                self._emit(job, "error", STAGE_ERROR, job.progress, f"{type(exc).__name__}: {exc}")
