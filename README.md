# 🚦 Smart Traffic & Helmet Detection System

ReactJS web UI + FastAPI backend powered by **YOLOv8** (configured through
`model/smart_traffic_system_model.pkl`). Detection only — bounding boxes,
**no segmentation**.

## Features

| Feature | Description |
|---|---|
| 🎬 **Video Upload** | Upload a traffic video → YOLO analyzes it → annotated H.264 video + per-object detections |
| 📹 **Live Camera** | Webcam frames stream over WebSocket → real-time bounding boxes, FPS & inference stats, quality selector, snapshot button |
| 🚨 **Violations & Plates** | Helmet-less riders and number plates are cropped into images, stored on disk + database, shown in a gallery with **download** option |
| 🗄️ **Database** | Every session (video/live) and its detections are stored in SQLite (`backend/data/traffic.db`) |
| 📊 **Dashboard & History** | Global stats, class distribution bars, filterable session history with detail view & delete |

## Project structure

```
Traffic_Helmet/
├── model/
│   └── smart_traffic_system_model.pkl   # model config (architecture, classes, weights URL)
├── backend/                             # FastAPI + Ultralytics YOLO + SQLite
│   ├── main.py                          # API: upload, jobs, WebSocket live, history, stats
│   ├── detector.py                      # loads pkl config + YOLO weights, runs detection
│   ├── database.py                      # SQLite storage layer
│   ├── requirements.txt
│   └── data/                            # created at runtime: traffic.db, uploads/, results/
├── frontend/                            # React 19 + Vite
│   ├── src/
│   │   ├── App.jsx                      # header, stats strip, tabs
│   │   └── components/                  # VideoUpload, LiveCamera, History, ClassBars
│   └── dist/                            # production build (served by the backend)
├── start.bat                            # one-click start (Windows)
└── README.md
```

## Quick start (Windows)

Double-click **`start.bat`**, then open **http://127.0.0.1:8000**

It installs Python dependencies, builds the React UI (first run only) and
starts the server. On the very first run the YOLO weights (~52 MB) are
downloaded automatically into `model/`.

## Manual start

```bat
:: 1. backend dependencies
python -m pip install -r backend\requirements.txt

:: 2. build the React UI (once, or after frontend changes)
cd frontend
npm install
npm run build
cd ..

:: 3. run the server (serves API + built UI)
cd backend
python main.py
:: (equivalent: python -m uvicorn main:app --host 127.0.0.1 --port 8000)
```

Open http://127.0.0.1:8000

> Using a virtual environment? Create/activate it inside `backend/`
> (`python -m venv .venv` then `.venv\Scripts\activate`), install
> `requirements.txt` into it, then run `python main.py`.
> `start.bat` automatically uses `backend\.venv` when it exists.

### Frontend development mode (hot reload)

```bat
:: terminal 1 — backend
cd backend
python -m uvicorn main:app --port 8000

:: terminal 2 — React dev server (proxies /api, /ws, /static to :8000)
cd frontend
npm run dev
```

Open http://localhost:5173

## API overview

- `GET /api/config` — model info & readiness
- `POST /api/video/upload` — multipart video upload → `{job_id, session_id}`
- `GET /api/video/jobs/{id}` — progress polling; `POST .../cancel` to stop
- `WS /ws/live` — send binary JPEG frames, receive JSON boxes; send
  `{"type":"config","imgsz":320|416|640}` to change live quality
- `GET /api/history`, `GET /api/history/{id}`, `DELETE /api/history/{id}`
- `GET /api/stats` — aggregate dashboard numbers
- `GET /api/events?type=no_helmet|plate&session_id=&limit=` — violation/plate images
- `DELETE /api/events/{id}` — delete one image + its record

## Helmet violation & number-plate images

Two small fine-tuned YOLO models (downloaded into `model/`) run alongside the
main detector on analyzed frames:

- `helmet_violation.pt` → `With Helmet` / `Without Helmet`
  (source: [iam-tsr/yolov8n-helmet-detection](https://huggingface.co/iam-tsr/yolov8n-helmet-detection), MIT)
- `plate_detector.pt` → `license_plate`
  (source: [Koushim/yolov8-license-plate-detection](https://huggingface.co/Koushim/yolov8-license-plate-detection), MIT)

When a rider without a helmet (or a plate) is seen:
1. the person/plate region is cropped from the frame,
2. saved as JPEG under `backend/data/violations/<session_id>/`,
3. recorded in the `events` SQLite table (with time, confidence, box),
4. shown in the **Violations & Plates** tab with a **Download** button.

Duplicate detections of the same rider/plate are filtered by IoU, so you get
one image per distinct object instead of one per frame. Deleting a session or
an event also removes its image file.

## ⚠️ About the model weights

`smart_traffic_system_model.pkl` is a **configuration file**: it specifies
`YOLOv8m` and points to the official COCO weights. Those weights detect
person, bicycle, car, motorcycle, bus, truck (and 74 other COCO classes) —
but **not** `Helmet` / `License_Plate`, which are listed as custom classes
(100/101) in the config.

The main detector therefore handles vehicles/persons; helmet and plate
detection comes from the auxiliary models above. If you later get a single
fine-tuned main model containing all classes, place it in `model/` as
`yolov8m.pt` — the backend picks it up automatically.

## Notes

- Runs on **CPU** (no GPU required). Live mode defaults to *Fast (320)*
  quality for smoother FPS; switch to 416/640 for better accuracy.
- Videos are analyzed at ~5 frames/second; boxes are held between analyzed
  frames so the output video stays smooth.
- Max upload size: 300 MB. Supported: mp4, avi, mov, mkv, webm, m4v.
- Database: SQLite with WAL mode — sessions + detections tables, cascade
  delete removes a session's detections and result video.
