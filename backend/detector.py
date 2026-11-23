"""Model loader + inference for the Smart Traffic / Helmet Detection system.

Reads the configuration stored in model/smart_traffic_system_model.pkl,
resolves the YOLO weights (downloads them on first run) and exposes a
thread-safe `detect()` that returns bounding boxes only (no segmentation).
"""

import pickle
import threading
import time
import urllib.request
from pathlib import Path

import cv2
import numpy as np

BASE_DIR = Path(__file__).resolve().parent.parent          # Traffic_Helmet/
MODEL_DIR = BASE_DIR / "model"
PKL_PATH = MODEL_DIR / "smart_traffic_system_model.pkl"

# Per-class colors (BGR) used when drawing boxes on video frames.
CLASS_COLORS = {
    "person": (235, 99, 37),         # blue
    "bicycle": (6, 119, 217),        # amber
    "car": (178, 145, 8),            # cyan
    "motorcycle": (38, 38, 220),     # red
    "bus": (105, 150, 5),            # emerald
    "truck": (237, 58, 124),         # violet
    "helmet": (74, 163, 22),         # green
    "no_helmet": (38, 38, 220),      # red
    "license_plate": (119, 39, 219), # pink
}
DEFAULT_COLOR = (139, 116, 100)


def color_for(name: str):
    return CLASS_COLORS.get(name.lower(), DEFAULT_COLOR)


class Detector:
    def __init__(self):
        self.config = {}
        self.model = None
        self.ready = False
        self.error = None
        self.weights_path = None
        self._lock = threading.Lock()
        self._load_config()

    def _load_config(self):
        if PKL_PATH.exists():
            with open(PKL_PATH, "rb") as f:
                self.config = pickle.load(f)
        else:
            self.config = {
                "model_architecture": "YOLOv8n",
                "classes": {},
                "weights_url": None,
            }

    @property
    def architecture(self) -> str:
        return self.config.get("model_architecture", "YOLOv8n")

    def load(self):
        """Load (and if needed download) the YOLO weights. Blocking call."""
        from ultralytics import YOLO

        arch = self.architecture.lower()                     # e.g. "yolov8m"
        local = MODEL_DIR / f"{arch}.pt"
        if not local.exists():
            # any .pt already present in model/ takes priority
            existing = sorted(MODEL_DIR.glob("*.pt"))
            if existing:
                local = existing[0]
            else:
                url = self.config.get("weights_url")
                if not url:
                    url = f"https://github.com/ultralytics/assets/releases/download/v8.2.0/{arch}.pt"
                MODEL_DIR.mkdir(parents=True, exist_ok=True)
                tmp = local.with_suffix(".download")
                print(f"[detector] downloading weights: {url}")
                urllib.request.urlretrieve(url, tmp)
                tmp.rename(local)
        self.weights_path = local
        print(f"[detector] loading {local.name} ...")
        self.model = YOLO(str(local))
        # warm-up so the first real frame is fast
        self.model.predict(np.zeros((320, 320, 3), dtype=np.uint8),
                           imgsz=320, verbose=False)
        self.ready = True
        print("[detector] model ready")

    @property
    def class_names(self):
        if self.model is not None:
            return dict(self.model.names)
        return {int(k): v for k, v in self.config.get("classes", {}).items()}

    def detect(self, frame_bgr: np.ndarray, imgsz: int = 640, conf: float = 0.35):
        """Run object detection. Returns a list of box dicts (no masks)."""
        if not self.ready:
            raise RuntimeError("Model is not loaded yet")
        with self._lock:
            t0 = time.perf_counter()
            results = self.model.predict(frame_bgr, imgsz=imgsz, conf=conf,
                                         verbose=False)
            elapsed = (time.perf_counter() - t0) * 1000.0
        boxes = []
        names = self.class_names
        for r in results:
            for b in r.boxes:
                x1, y1, x2, y2 = (float(v) for v in b.xyxy[0].tolist())
                cls_id = int(b.cls[0].item())
                boxes.append({
                    "class_id": cls_id,
                    "class_name": str(names.get(cls_id, cls_id)),
                    "confidence": round(float(b.conf[0].item()), 4),
                    "x1": round(x1, 1), "y1": round(y1, 1),
                    "x2": round(x2, 1), "y2": round(y2, 1),
                })
        return boxes, elapsed

    @staticmethod
    def draw(frame: np.ndarray, boxes):
        """Draw bounding boxes + labels on a frame (in place)."""
        for b in boxes:
            color = color_for(b["class_name"])
            x1, y1, x2, y2 = int(b["x1"]), int(b["y1"]), int(b["x2"]), int(b["y2"])
            cv2.rectangle(frame, (x1, y1), (x2, y2), color, 2)
            label = f'{b["class_name"]} {b["confidence"]:.2f}'
            (tw, th), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.55, 1)
            ty = max(y1 - 4, th + 4)
            cv2.rectangle(frame, (x1, ty - th - 6), (x1 + tw + 6, ty), color, -1)
            cv2.putText(frame, label, (x1 + 3, ty - 4),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.55, (10, 10, 10), 1, cv2.LINE_AA)
        return frame


detector = Detector()
