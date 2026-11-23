"""Smart Traffic & Helmet Detection System — FastAPI backend.

Endpoints
---------
GET    /api/config                 model info + readiness
POST   /api/video/upload           upload a video -> background detection job
GET    /api/video/jobs/{job_id}    job progress / result
POST   /api/video/jobs/{job_id}/cancel
WS     /ws/live                    live camera frames (binary JPEG in, JSON boxes out)
GET    /api/history                stored sessions (database)
GET    /api/history/{id}           session + its detections
DELETE /api/history/{id}
GET    /api/stats                  aggregate dashboard numbers
"""

import json
import subprocess
import threading
import time
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

import cv2
import numpy as np
from fastapi import FastAPI, File, HTTPException, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from starlette.concurrency import run_in_threadpool

import database as db
from aux_detectors import aux_detectors
from detector import BASE_DIR, detector
from events import EventExtractor, VIOLATIONS_DIR

BACKEND_DIR = Path(__file__).resolve().parent
DATA_DIR = BACKEND_DIR / "data"
UPLOAD_DIR = DATA_DIR / "uploads"
RESULTS_DIR = DATA_DIR / "results"
for d in (UPLOAD_DIR, RESULTS_DIR):
    d.mkdir(parents=True, exist_ok=True)

FRONTEND_DIST = BASE_DIR / "frontend" / "dist"

ANALYSIS_FPS = 5          # how many frames per second are actually analysed in videos
LIVE_IMGSZ = 416          # smaller input for live mode -> faster on CPU
VIDEO_IMGSZ = 640
CONF = 0.35
MAX_UPLOAD_MB = 300
ALLOWED_EXT = {".mp4", ".avi", ".mov", ".mkv", ".webm", ".m4v"}

JOBS: dict = {}           # job_id -> progress dict (in-memory)


@asynccontextmanager
async def lifespan(_: FastAPI):
    db.init_db()

    def _load():
        try:
            detector.load()
        except Exception as exc:                     # pragma: no cover
            detector.error = str(exc)
            print(f"[detector] FAILED to load model: {exc}")
        try:
            aux_detectors.load()
        except Exception as exc:                     # pragma: no cover
            aux_detectors.error = str(exc)
            print(f"[aux] FAILED to load models: {exc}")

    threading.Thread(target=_load, daemon=True).start()
    yield


app = FastAPI(title="Smart Traffic & Helmet Detection API", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# Config / stats
# ---------------------------------------------------------------------------

@app.get("/api/config")
def get_config():
    available = list(detector.class_names.values()) if detector.ready else []
    configured = list(detector.config.get("classes", {}).values())
    missing = [c for c in configured
               if c.lower() not in {a.lower() for a in available}]
    note = None
    if detector.ready and missing:
        note = (f"Current weights ({detector.architecture}) do not include "
                f"{', '.join(missing)} classes. Detection works for the available "
                f"classes; put fine-tuned weights in the model folder to enable the rest.")
    return {
        "ready": detector.ready,
        "error": detector.error,
        "model_architecture": detector.architecture,
        "weights_file": detector.weights_path.name if detector.weights_path else None,
        "configured_classes": detector.config.get("classes", {}),
        "available_classes": available,
        "device": "cpu",
        "note": note,
        "extras_ready": aux_detectors.ready,
        "extras_error": aux_detectors.error,
    }


@app.get("/api/stats")
def get_stats():
    return db.global_stats()


# ---------------------------------------------------------------------------
# Video upload + background processing
# ---------------------------------------------------------------------------

def _ffmpeg_cmd(w: int, h: int, fps: float, out_path: Path):
    import imageio_ffmpeg
    return [
        imageio_ffmpeg.get_ffmpeg_exe(), "-y",
        "-f", "rawvideo", "-pix_fmt", "bgr24",
        "-s", f"{w}x{h}", "-r", f"{fps:.3f}", "-i", "pipe:0",
        "-an", "-c:v", "libx264", "-preset", "veryfast", "-crf", "23",
        "-pix_fmt", "yuv420p", "-movflags", "+faststart",
        str(out_path),
    ]


def _process_video(job_id: str, session_id: int, src_path: Path):
    job = JOBS[job_id]
    cap = cv2.VideoCapture(str(src_path))
    proc = None
    try:
        if not cap.isOpened():
            raise RuntimeError("Could not open the uploaded video")
        fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
        if fps <= 0 or fps > 120:
            fps = 25.0
        w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT)) or 0
        # H.264 needs even dimensions
        ow, oh = w - (w % 2), h - (h % 2)
        stride = max(1, round(fps / ANALYSIS_FPS))

        out_path = RESULTS_DIR / f"session_{session_id}.mp4"
        proc = subprocess.Popen(_ffmpeg_cmd(ow, oh, fps, out_path),
                                stdin=subprocess.PIPE,
                                stdout=subprocess.DEVNULL,
                                stderr=subprocess.DEVNULL)

        job.update(frames_total=total, fps=round(fps, 2), width=w, height=h)
        db.finish_session(session_id, status="processing",
                          meta={"fps": fps, "width": w, "height": h,
                                "frames_total": total, "upload": src_path.name})

        counts: dict = {}
        total_detections = 0
        violations = 0
        plates = 0
        extractor = EventExtractor(session_id)
        last_boxes = []
        idx = 0
        t_start = time.time()
        while True:
            if job.get("cancel"):
                raise RuntimeError("cancelled")
            ok, frame = cap.read()
            if not ok:
                break
            if idx % stride == 0:
                boxes, _ = detector.detect(frame, imgsz=VIDEO_IMGSZ, conf=CONF)
                last_boxes = boxes
                for ev in extractor.process(frame, boxes, idx, idx / fps):
                    if ev["type"] == "no_helmet":
                        violations += 1
                    else:
                        plates += 1
                if boxes:
                    db.add_detections(session_id, boxes, idx, idx / fps)
                    for b in boxes:
                        counts[b["class_name"]] = counts.get(b["class_name"], 0) + 1
                    total_detections += len(boxes)
            annotated = detector.draw(frame, last_boxes)
            if (ow, oh) != (w, h):
                annotated = cv2.resize(annotated, (ow, oh))
            proc.stdin.write(np.ascontiguousarray(annotated, dtype=np.uint8).tobytes())
            idx += 1
            if idx % 10 == 0 or idx == total:
                job.update(frames_done=idx,
                           progress=round(idx / total * 100, 1) if total else 0,
                           detections=total_detections,
                           violations=violations, plates=plates)
                db.update_progress(session_id, idx, total_detections, counts)

        proc.stdin.close()
        proc.wait(timeout=120)
        cap.release()

        duration = round(time.time() - t_start, 1)
        result_url = f"/static/results/{out_path.name}"
        job.update(status="completed", progress=100, frames_done=idx,
                   result_url=result_url, session_id=session_id,
                   violations=violations, plates=plates)
        db.finish_session(session_id, status="completed", frames=idx,
                          detections=total_detections, summary=counts,
                          result_video=result_url,
                          meta={"fps": fps, "width": w, "height": h,
                                "frames_total": total, "upload": src_path.name,
                                "processing_seconds": duration})
    except Exception as exc:
        status = "cancelled" if job.get("cancel") else "failed"
        job.update(status=status, error=str(exc))
        db.finish_session(session_id, status=status,
                          meta={"error": str(exc), "upload": src_path.name})
        if proc is not None:
            try:
                proc.stdin.close()
            except Exception:
                pass
            proc.kill()
    finally:
        cap.release()


@app.post("/api/video/upload")
async def upload_video(file: UploadFile = File(...)):
    if not detector.ready:
        raise HTTPException(503, "Model is still loading, please retry in a moment")
    ext = Path(file.filename or "video.mp4").suffix.lower()
    if ext not in ALLOWED_EXT:
        raise HTTPException(400, f"Unsupported file type '{ext}'. Allowed: {sorted(ALLOWED_EXT)}")
    job_id = uuid.uuid4().hex[:12]
    dest = UPLOAD_DIR / f"{job_id}{ext}"
    size = 0
    with open(dest, "wb") as out:
        while chunk := await file.read(1024 * 1024):
            size += len(chunk)
            if size > MAX_UPLOAD_MB * 1024 * 1024:
                out.close()
                dest.unlink(missing_ok=True)
                raise HTTPException(413, f"File too large (max {MAX_UPLOAD_MB} MB)")
            out.write(chunk)
    session_id = db.create_session("video", file.filename or dest.name)
    JOBS[job_id] = {"job_id": job_id, "session_id": session_id, "status": "processing",
                    "progress": 0, "frames_done": 0, "frames_total": 0,
                    "detections": 0, "result_url": None, "error": None, "cancel": False,
                    "violations": 0, "plates": 0}
    threading.Thread(target=_process_video, args=(job_id, session_id, dest),
                     daemon=True).start()
    return {"job_id": job_id, "session_id": session_id}


@app.get("/api/video/jobs/{job_id}")
def job_status(job_id: str):
    job = JOBS.get(job_id)
    if job is None:
        raise HTTPException(404, "Unknown job")
    return {k: v for k, v in job.items() if k != "cancel"}


@app.post("/api/video/jobs/{job_id}/cancel")
def job_cancel(job_id: str):
    job = JOBS.get(job_id)
    if job is None:
        raise HTTPException(404, "Unknown job")
    job["cancel"] = True
    return {"ok": True}


# ---------------------------------------------------------------------------
# Live camera (WebSocket)
# ---------------------------------------------------------------------------

@app.websocket("/ws/live")
async def ws_live(ws: WebSocket):
    await ws.accept()
    if not detector.ready:
        await ws.send_json({"type": "error", "message": "Model is still loading"})
        await ws.close()
        return
    session_id = db.create_session("live", "Live Camera")
    await ws.send_json({"type": "ready", "session_id": session_id})

    counts: dict = {}
    frames = 0
    total_detections = 0
    event_totals = {"no_helmet": 0, "plate": 0}
    extractor = EventExtractor(session_id)
    started = time.time()
    last_flush = started
    imgsz = LIVE_IMGSZ
    try:
        while True:
            msg = await ws.receive()
            if msg["type"] == "websocket.disconnect":
                break
            if msg.get("text"):
                try:
                    ctrl = json.loads(msg["text"])
                    if ctrl.get("type") == "config":
                        req = int(ctrl.get("imgsz", LIVE_IMGSZ))
                        imgsz = max(160, min(1280, req - req % 32))
                        await ws.send_json({"type": "config", "imgsz": imgsz})
                except Exception:
                    pass
                continue
            data = msg.get("bytes")
            if not data:
                continue
            frame = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)
            if frame is None:
                continue
            boxes, ms = await run_in_threadpool(detector.detect, frame, imgsz, CONF)
            frames += 1
            total_detections += len(boxes)
            frame_counts: dict = {}
            for b in boxes:
                counts[b["class_name"]] = counts.get(b["class_name"], 0) + 1
                frame_counts[b["class_name"]] = frame_counts.get(b["class_name"], 0) + 1
            now = time.time()
            new_events = []
            if now - last_flush >= 1.0:            # throttle DB writes + event extraction
                db.add_detections(session_id, boxes, frames, now - started)
                db.update_progress(session_id, frames, total_detections, counts)
                new_events = extractor.process(frame, boxes, frames, now - started)
                for ev in new_events:
                    event_totals[ev["type"]] += 1
                last_flush = now
            await ws.send_json({
                "type": "detections", "boxes": boxes,
                "frame_counts": frame_counts, "counts": counts,
                "total": total_detections, "frames": frames,
                "event_totals": event_totals, "new_events": new_events,
                "ms": round(ms, 1),
                "w": frame.shape[1], "h": frame.shape[0],
            })
    except WebSocketDisconnect:
        pass
    except Exception as exc:
        print(f"[ws/live] error: {exc}")
    finally:
        db.finish_session(session_id, status="completed", frames=frames,
                          detections=total_detections, summary=counts,
                          meta={"duration_seconds": round(time.time() - started, 1)})


# ---------------------------------------------------------------------------
# History (database)
# ---------------------------------------------------------------------------

@app.get("/api/history")
def history(mode: str | None = None, limit: int = 100):
    return db.list_sessions(mode=mode, limit=limit)


@app.get("/api/history/{session_id}")
def history_detail(session_id: int):
    sess = db.get_session(session_id)
    if sess is None:
        raise HTTPException(404, "Session not found")
    sess["detections"] = db.get_detections(session_id)
    return sess


@app.delete("/api/history/{session_id}")
def history_delete(session_id: int):
    event_rows = db.delete_session_events(session_id)
    sess = db.delete_session(session_id)
    if sess is None:
        raise HTTPException(404, "Session not found")
    # clean up files belonging to this session
    for ev in event_rows:
        (VIOLATIONS_DIR / str(ev["session_id"]) / Path(ev["image_path"]).name).unlink(
            missing_ok=True
        )
    if sess.get("result_video"):
        name = Path(sess["result_video"]).name
        (RESULTS_DIR / name).unlink(missing_ok=True)
    upload = (sess.get("meta") or {}).get("upload")
    if upload:
        (UPLOAD_DIR / Path(upload).name).unlink(missing_ok=True)
    return {"ok": True}


# ---------------------------------------------------------------------------
# Helmet violations + number plates (cropped images stored on disk)
# ---------------------------------------------------------------------------

@app.get("/api/events")
def events_list(session_id: int | None = None, type: str | None = None,
                limit: int = 200):
    return db.list_events(session_id=session_id, kind=type, limit=limit)


@app.delete("/api/events/{event_id}")
def events_delete(event_id: int):
    ev = db.delete_event(event_id)
    if ev is None:
        raise HTTPException(404, "Event not found")
    (VIOLATIONS_DIR / str(ev["session_id"]) / Path(ev["image_path"]).name).unlink(
        missing_ok=True
    )
    return {"ok": True}


# ---------------------------------------------------------------------------
# Static files: results + violations + built frontend
# ---------------------------------------------------------------------------

VIOLATIONS_DIR.mkdir(parents=True, exist_ok=True)
app.mount("/static/violations", StaticFiles(directory=VIOLATIONS_DIR), name="violations")
app.mount("/static/results", StaticFiles(directory=RESULTS_DIR), name="results")

if FRONTEND_DIST.exists():
    app.mount("/", StaticFiles(directory=FRONTEND_DIST, html=True), name="frontend")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="127.0.0.1", port=8000)
