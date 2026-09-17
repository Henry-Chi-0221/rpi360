"""Optional loopback job API with explicit local source root and bounded concurrency."""

import asyncio
import hmac
import json
import os
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from .export import export


class ExportJob(BaseModel):
    request_id: str = Field(min_length=8, max_length=128)
    recipe: dict


def create_app(root, token, renderer=None, allowed_origins=()):
    if len(token) < 32:
        raise ValueError("worker token must contain at least 32 characters")
    root = Path(root).resolve()
    sources = root / "sources"
    outputs = root / "exports"
    sources.mkdir(parents=True, exist_ok=True)
    outputs.mkdir(exist_ok=True)
    executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="media-export")
    jobs = {}
    requests = {}
    lock = threading.Lock()

    def authorized(request: Request):
        if (
            request.headers.get("origin")
            and request.headers["origin"] not in allowed_origins
        ):
            raise HTTPException(403, "origin is not allowed")
        if not hmac.compare_digest(
            request.headers.get("authorization", ""), "Bearer " + token
        ):
            raise HTTPException(401, "worker token required")

    @asynccontextmanager
    async def lifespan(app):
        yield
        for job in jobs.values():
            job["cancel"].set()
        await asyncio.to_thread(executor.shutdown, wait=True, cancel_futures=True)

    app = FastAPI(
        title="RPI360 optional media worker",
        version="2.0.0-alpha.1",
        dependencies=[Depends(authorized)],
        lifespan=lifespan,
    )

    @app.post("/v1/jobs")
    def submit(body: ExportJob):
        canonical = json.dumps(body.recipe, sort_keys=True)
        with lock:
            if body.request_id in requests:
                job = jobs[requests[body.request_id]]
                if job["recipe"] != canonical:
                    raise HTTPException(
                        409, "request ID reused with a different recipe"
                    )
                return {k: v for k, v in job.items() if k not in ("cancel", "recipe")}
            if sum(j["state"] in ("queued", "running") for j in jobs.values()) >= 2:
                raise HTTPException(429, "worker queue is full")
            if len(jobs) >= 128:
                oldest = next(
                    k
                    for k, j in jobs.items()
                    if j["state"] not in ("queued", "running")
                )
                del jobs[oldest]
                for key in [k for k, v in requests.items() if v == oldest]:
                    del requests[key]
            job_id = uuid.uuid4().hex
            job = {
                "id": job_id,
                "state": "queued",
                "progress": 0.0,
                "cancel": threading.Event(),
                "recipe": canonical,
            }
            jobs[job_id] = job
            requests[body.request_id] = job_id

        def run():
            job["state"] = "running"
            try:
                report = export(
                    body.recipe,
                    sources,
                    outputs / (job_id + ".mp4"),
                    renderer,
                    lambda p: job.update(progress=p),
                    job["cancel"].is_set,
                )
                job.update(state="complete", report=report)
            except InterruptedError:
                job["state"] = "cancelled"
            except Exception as e:
                job.update(state="failed", error=str(e))

        executor.submit(run)
        return {"id": job_id, "state": job["state"], "progress": job["progress"]}

    def get(job_id):
        if job_id not in jobs:
            raise HTTPException(404, "job not found")
        return jobs[job_id]

    @app.get("/v1/jobs/{job_id}")
    def status(job_id: str):
        return {k: v for k, v in get(job_id).items() if k not in ("cancel", "recipe")}

    @app.delete("/v1/jobs/{job_id}")
    def cancel(job_id: str):
        get(job_id)["cancel"].set()
        return {"cancel_requested": True}

    @app.get("/v1/jobs/{job_id}/output")
    def output(job_id: str):
        if get(job_id)["state"] != "complete":
            raise HTTPException(409, "export is not complete")
        return FileResponse(outputs / (job_id + ".mp4"), media_type="video/mp4")

    return app


def main():
    import argparse

    import uvicorn

    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--root", type=Path, required=True)
    p.add_argument("--port", type=int, default=8766)
    p.add_argument("--renderer")
    p.add_argument("--origin", action="append", default=[])
    a = p.parse_args()
    token = os.environ.get("RPI360_WORKER_TOKEN", "")
    uvicorn.run(
        create_app(a.root, token, a.renderer, a.origin), host="127.0.0.1", port=a.port
    )


if __name__ == "__main__":
    main()
