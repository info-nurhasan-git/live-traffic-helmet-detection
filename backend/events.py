"""Crop and store helmet-violator / license-plate images from detected boxes."""

import time
from pathlib import Path

import cv2
import numpy as np

import database as db
from aux_detectors import aux_detectors

VIOLATIONS_DIR = db.DATA_DIR / "violations"


def _iou(a: dict, b: dict) -> float:
    ix1, iy1 = max(a["x1"], b["x1"]), max(a["y1"], b["y1"])
    ix2, iy2 = min(a["x2"], b["x2"]), min(a["y2"], b["y2"])
    iw, ih = max(0, ix2 - ix1), max(0, iy2 - iy1)
    inter = iw * ih
    area_a = max(0, a["x2"] - a["x1"]) * max(0, a["y2"] - a["y1"])
    area_b = max(0, b["x2"] - b["x1"]) * max(0, b["y2"] - b["y1"])
    union = area_a + area_b - inter
    return inter / union if union > 0 else 0.0


def _crop(frame: np.ndarray, box: dict, pad: float):
    h, w = frame.shape[:2]
    bw, bh = max(1, box["x2"] - box["x1"]), max(1, box["y2"] - box["y1"])
    x1 = max(0, int(box["x1"] - bw * pad))
    y1 = max(0, int(box["y1"] - bh * pad))
    x2 = min(w, int(box["x2"] + bw * pad))
    y2 = min(h, int(box["y2"] + bh * pad))
    if x2 <= x1 or y2 <= y1:
        return None
    return frame[y1:y2, x1:x2]


def _save_crop(frame: np.ndarray, box: dict, session_id: int, kind: str,
               pad: float = 0.15) -> str | None:
    crop = _crop(frame, box, pad)
    if crop is None or crop.size == 0:
        return None
    folder = VIOLATIONS_DIR / str(session_id)
    folder.mkdir(parents=True, exist_ok=True)
    name = f"{int(time.time() * 1000)}_{kind}_{np.random.randint(1000, 9999)}.jpg"
    path = folder / name
    if not cv2.imwrite(str(path), crop, [cv2.IMWRITE_JPEG_QUALITY, 90]):
        return None
    return f"/static/violations/{session_id}/{name}"


def _best_person(box: dict, main_boxes: list) -> dict | None:
    people = [b for b in main_boxes if b["class_name"].lower() == "person"]
    if not people:
        return None
    best = max(people, key=lambda p: _iou(box, p))
    return best if _iou(box, best) > 0.05 else None


class EventExtractor:
    """Per-session extractor with simple IoU dedup so the same rider/plate
    is only saved once instead of every frame."""

    def __init__(self, session_id: int):
        self.session_id = session_id
        self.recent: dict[str, list] = {"no_helmet": [], "plate": []}

    def process(self, frame: np.ndarray, main_boxes: list,
                frame_index: int, time_offset: float) -> list:
        if not aux_detectors.ready:
            return []
        helmet_boxes, plate_boxes = aux_detectors.detect(frame, imgsz=416, conf=0.25)

        targets = []
        for b in helmet_boxes:
            norm = b["class_name"].lower().replace(" ", "_").replace("-", "_")
            if "without" in norm or "no_helmet" in norm:
                targets.append(("no_helmet", b))
            elif "helmet" in norm:
                # mark helmet presence in the summary, no image needed
                pass
        targets += [("plate", b) for b in plate_boxes]

        saved = []
        for kind, box in targets:
            history = self.recent[kind]
            if any(_iou(box, old) > 0.55 for old in history[-12:]):
                continue
            draw_box = box
            pad = 0.15
            if kind == "no_helmet":
                person = _best_person(box, main_boxes)
                if person is not None:
                    draw_box = person       # full rider crop when available
                    pad = 0.08
            url = _save_crop(frame, draw_box, self.session_id, kind, pad)
            if url is None:
                continue
            db.add_event(self.session_id, kind, url, box["confidence"],
                         box["x1"], box["y1"], box["x2"], box["y2"],
                         frame_index, time_offset)
            history.append(box)
            saved.append({"type": kind, "image_path": url})
        return saved
