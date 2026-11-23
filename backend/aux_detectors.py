"""Optional auxiliary YOLO models for helmet-violation and license-plate detection.

The main model from the .pkl config is a COCO model (no helmet / plate classes).
These two small fine-tuned models provide:
  * helmet_violation.pt -> helmet | no_helmet
  * plate_detector.pt   -> license plate

Both are loaded lazily and degrade gracefully if the files are missing.
"""

import threading
from pathlib import Path

import cv2
import numpy as np

MODEL_DIR = Path(__file__).resolve().parent.parent / "model"


class AuxDetectors:
    def __init__(self):
        self.helmet_model = None
        self.plate_model = None
        self.ready = False
        self.error = None
        self._lock = threading.Lock()

    def load(self):
        from ultralytics import YOLO
        helmet_path = MODEL_DIR / "helmet_violation.pt"
        plate_path = MODEL_DIR / "plate_detector.pt"
        if not (helmet_path.exists() and plate_path.exists()):
            self.error = "helmet_violation.pt / plate_detector.pt not found in model folder"
            print(f"[aux] {self.error}")
            return
        print("[aux] loading helmet + plate models ...")
        self.helmet_model = YOLO(str(helmet_path))
        self.plate_model = YOLO(str(plate_path))
        dummy = np.zeros((320, 320, 3), dtype=np.uint8)
        self.helmet_model.predict(dummy, imgsz=320, verbose=False)
        self.plate_model.predict(dummy, imgsz=320, verbose=False)
        self.ready = True
        print("[aux] helmet + plate models ready")

    @staticmethod
    def _to_boxes(result, names):
        out = []
        for r in result:
            for b in r.boxes:
                x1, y1, x2, y2 = (float(v) for v in b.xyxy[0].tolist())
                cls_id = int(b.cls[0].item())
                out.append({
                    "class_name": str(names.get(cls_id, cls_id)),
                    "confidence": round(float(b.conf[0].item()), 4),
                    "x1": x1, "y1": y1, "x2": x2, "y2": y2,
                })
        return out

    def detect(self, frame: np.ndarray, imgsz: int = 416, conf: float = 0.4):
        """Returns (helmet_boxes, plate_boxes)."""
        if not self.ready:
            return [], []
        with self._lock:
            hr = self.helmet_model.predict(frame, imgsz=imgsz, conf=conf, verbose=False)
            pr = self.plate_model.predict(frame, imgsz=imgsz, conf=conf, verbose=False)
        return (self._to_boxes(hr, self.helmet_model.names),
                self._to_boxes(pr, self.plate_model.names))


aux_detectors = AuxDetectors()
