"""End-to-end test for helmet-violation + plate event extraction."""
import asyncio
import json
import time
import urllib.request
from pathlib import Path

import cv2
import numpy as np

BASE = "http://127.0.0.1:8000"
TMP = Path(r"C:\Users\nurha\AppData\Local\Temp\opencode")


def get(p):
    with urllib.request.urlopen(BASE + p, timeout=30) as r:
        return json.loads(r.read())


def make_video():
    names = ["helmet_sample.jpg", "rider1.jpg", "rider2.jpg", "plate1.jpg"]
    out = TMP / "test_events.mp4"
    w, h = 640, 480
    writer = cv2.VideoWriter(str(out), cv2.VideoWriter_fourcc(*"mp4v"), 10, (w, h))
    for name in names:
        img = cv2.imread(str(TMP / name))
        img = cv2.resize(img, (w, h))
        for _ in range(15):
            writer.write(img)
    writer.release()
    return out


def upload(video):
    boundary = "----testboundary123"
    data = video.read_bytes()
    body = (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="file"; filename="test_events.mp4"\r\n'
        f"Content-Type: video/mp4\r\n\r\n"
    ).encode() + data + f"\r\n--{boundary}--\r\n".encode()
    req = urllib.request.Request(
        BASE + "/api/video/upload", data=body,
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
    )
    return json.loads(urllib.request.urlopen(req, timeout=120).read())


def wait_ready():
    while True:
        cfg = get("/api/config")
        if cfg["ready"]:
            print("config extras_ready:", cfg["extras_ready"], "| error:", cfg["extras_error"])
            assert cfg["extras_ready"]
            return
        time.sleep(3)


async def live_test():
    import websockets
    img = cv2.resize(cv2.imread(str(TMP / "rider2.jpg")), (640, 480))
    ok, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 70])
    async with websockets.connect("ws://127.0.0.1:8000/ws/live") as ws:
        ready = json.loads(await ws.recv())
        print("WS session", ready["session_id"])
        for _ in range(12):
            await ws.send(buf.tobytes())
            msg = json.loads(await ws.recv())
            await asyncio.sleep(0.12)
        print("live event_totals:", msg["event_totals"])
        return ready["session_id"]


def main():
    wait_ready()
    video = make_video()
    res = upload(video)
    print("uploaded:", res)
    job_id = res["job_id"]
    for _ in range(200):
        job = get(f"/api/video/jobs/{job_id}")
        if job["status"] in ("completed", "failed", "cancelled"):
            print("job:", {k: job[k] for k in ("status", "violations", "plates", "detections")})
            assert job["status"] == "completed"
            assert job["violations"] > 0, "no helmet violation images saved"
            assert job["plates"] > 0, "no plate images saved"
            break
        time.sleep(2)
    else:
        raise SystemExit("job timed out")

    for kind in ("no_helmet", "plate"):
        evs = get(f"/api/events?type={kind}&limit=10")
        print(f"{kind}: {len(evs)} events; first =", evs[0]["image_path"] if evs else None)
        assert len(evs) > 0
        with urllib.request.urlopen(BASE + evs[0]["image_path"], timeout=10) as r:
            data = r.read()
        print(f"  image download OK: {len(data)} bytes, content-type={r.headers.get('Content-Type')}")
        assert len(data) > 500

    live_sid = asyncio.run(live_test())
    live_events = get(f"/api/events?session_id={live_sid}")
    print("live stored events:", len(live_events))

    # cleanup
    for s in get("/api/history"):
        urllib.request.urlopen(
            urllib.request.Request(BASE + f"/api/history/{s['id']}", method="DELETE"),
            timeout=10,
        )
    stats = get("/api/stats")
    print("after cleanup:", {k: stats[k] for k in ("sessions", "detections", "event_totals")})
    assert stats["sessions"] == 0
    print("EVENT TESTS PASSED")


if __name__ == "__main__":
    main()
