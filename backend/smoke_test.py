"""End-to-end smoke test for the Smart Traffic backend."""
import asyncio
import json
import time
import urllib.request
from pathlib import Path

import cv2
import numpy as np

BASE = "http://127.0.0.1:8000"
TMP = Path(r"C:\Users\nurha\AppData\Local\Temp\opencode")


def get(path):
    with urllib.request.urlopen(BASE + path, timeout=30) as r:
        return json.loads(r.read())


def wait_ready(timeout=600):
    t0 = time.time()
    while time.time() - t0 < timeout:
        try:
            cfg = get("/api/config")
            if cfg["ready"]:
                print("MODEL READY:", cfg["model_architecture"], "| classes:", cfg["available_classes"])
                if cfg.get("note"):
                    print("NOTE:", cfg["note"])
                return cfg
            if cfg.get("error"):
                raise SystemExit("Model load error: " + cfg["error"])
        except Exception as e:
            print("waiting...", e)
        time.sleep(5)
    raise SystemExit("Timed out waiting for model")


def test_video():
    boundary = "----testboundary123"
    data = (TMP / "test_traffic.mp4").read_bytes()
    body = (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="file"; filename="test_traffic.mp4"\r\n'
        f"Content-Type: video/mp4\r\n\r\n"
    ).encode() + data + f"\r\n--{boundary}--\r\n".encode()
    req = urllib.request.Request(
        BASE + "/api/video/upload", data=body,
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
    )
    with urllib.request.urlopen(req, timeout=120) as r:
        res = json.loads(r.read())
    print("UPLOAD:", res)
    job_id = res["job_id"]
    t0 = time.time()
    while time.time() - t0 < 600:
        j = get(f"/api/video/jobs/{job_id}")
        if j["status"] in ("completed", "failed", "cancelled"):
            print("JOB:", json.dumps(j, indent=1))
            assert j["status"] == "completed", j
            assert j["detections"] > 0, "expected detections on bus.jpg video"
            out = Path(__file__).parent / "data" / "results" / f"session_{j['session_id']}.mp4"
            assert out.exists(), f"missing result video {out}"
            cap = cv2.VideoCapture(str(out))
            n = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
            cap.release()
            print(f"RESULT VIDEO OK: {out.name}, {n} frames, {out.stat().st_size} bytes")
            return j["session_id"]
        time.sleep(3)
    raise SystemExit("video job timed out")


async def test_live():
    import websockets
    img = cv2.imread(str(TMP / "bus.jpg"))
    img = cv2.resize(img, (640, 480))
    ok, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 70])
    async with websockets.connect("ws://127.0.0.1:8000/ws/live") as ws:
        ready = json.loads(await ws.recv())
        print("WS READY:", ready)
        assert ready["type"] == "ready"
        for i in range(5):
            await ws.send(buf.tobytes())
            msg = json.loads(await ws.recv())
            assert msg["type"] == "detections", msg
            print(f"WS frame {i+1}: {len(msg['boxes'])} boxes, {msg['ms']} ms, counts={msg['frame_counts']}")
        assert msg["total"] > 0
    await asyncio.sleep(1)
    return ready["session_id"]


def test_history(video_sid, live_sid):
    hist = get("/api/history")
    ids = [s["id"] for s in hist]
    assert video_sid in ids and live_sid in ids, ids
    detail = get(f"/api/history/{video_sid}")
    print(f"HISTORY OK: {len(hist)} sessions; video session has {len(detail['detections'])} detection rows")
    assert len(detail["detections"]) > 0
    stats = get("/api/stats")
    print("STATS:", json.dumps({k: v for k, v in stats.items() if k != 'recent'}))
    assert stats["detections"] > 0
    live = get(f"/api/history/{live_sid}")
    assert live["status"] == "completed" and live["mode"] == "live"
    print("LIVE SESSION SAVED:", {k: live[k] for k in ('id', 'mode', 'status', 'frames_processed', 'detections_count')})


if __name__ == "__main__":
    wait_ready()
    vsid = test_video()
    lsid = asyncio.run(test_live())
    test_history(vsid, lsid)
    print("\nALL TESTS PASSED")
