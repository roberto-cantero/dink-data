"""The pretrained player models behind small interfaces (DESIGN 6.6 steps 1 and 2).

RF-DETR finds people, RTMPose finds their 17 COCO keypoints and DINOv2 gives an appearance
embedding. Each loads on its first call, never at import. Weights download on first use into
`cache_dir()`, outside the repo.
"""

import os
import urllib.request
import zipfile
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

from dinkdata.players import pose

PERSON = 1
"""The person class in RF-DETR's COCO ids."""

DETECTORS = {
    "nano": ("RFDETRNano", "rf-detr-nano.pth"),
    "small": ("RFDETRSmall", "rf-detr-small.pth"),
    "medium": ("RFDETRMedium", "rf-detr-medium.pth"),
    "large": ("RFDETRLarge", "rf-detr-large-2026.pth"),
}
"""The Apache-2.0 sizes only. XL and 2XL are under PML (DESIGN 13)."""

RTMPOSE_URL = (
    "https://download.openmmlab.com/mmpose/v1/projects/rtmposev1/onnx_sdk/"
    "rtmpose-m_simcc-body7_pt-body7_420e-256x192-e48f03d0_20230504.zip"
)
DINO = "facebook/dinov2-small"
DINO_H, DINO_W = 224, 112
"""DINOv2 input for a standing person, in multiples of its 14-pixel patches."""


def pick_device() -> str:
    import torch

    if torch.cuda.is_available():
        return "cuda"
    if torch.backends.mps.is_available():
        return "mps"
    return "cpu"


def cache_dir() -> Path:
    """Where downloaded weights live: `$DINKDATA_MODELS`, or ~/.cache/dinkdata/models."""
    env = os.environ.get("DINKDATA_MODELS")
    return Path(env) if env else Path.home() / ".cache" / "dinkdata" / "models"


def clip_region(region: Sequence[float], width: int, height: int) -> tuple[int, int, int, int]:
    """A region x1, y1, x2, y2 rounded to whole pixels inside a width x height frame."""
    x1, y1, x2, y2 = region
    return (
        int(np.clip(np.floor(x1), 0, width)),
        int(np.clip(np.floor(y1), 0, height)),
        int(np.clip(np.ceil(x2), 0, width)),
        int(np.clip(np.ceil(y2), 0, height)),
    )


def shift_boxes(boxes: np.ndarray, region: Sequence[int]) -> np.ndarray:
    """Boxes found in a crop, moved back to the frame's pixels."""
    x1, y1 = region[0], region[1]
    return boxes + np.array([x1, y1, x1, y1], dtype=boxes.dtype)


@dataclass(frozen=True)
class Detections:
    boxes: np.ndarray
    """n x 4, x1, y1, x2, y2 in frame pixels."""
    conf: np.ndarray


class PersonDetector:
    """RF-DETR, people only. Call it with an RGB frame and, optionally, the region to search."""

    def __init__(self, size: str = "medium", threshold: float = 0.3, device: str | None = None):
        self.size = size
        self.threshold = threshold
        self.device = device
        self._model: Any = None

    def _load(self) -> Any:
        import rfdetr

        class_name, weights = DETECTORS[self.size]
        folder = cache_dir()
        folder.mkdir(parents=True, exist_ok=True)
        model = getattr(rfdetr, class_name)(
            device=self.device or pick_device(), pretrain_weights=str(folder / weights)
        )
        return model

    def __call__(self, image: np.ndarray, region: Sequence[float] | None = None) -> Detections:
        if self._model is None:
            self._model = self._load()
        h, w = image.shape[:2]
        box = clip_region(region, w, h) if region is not None else (0, 0, w, h)
        crop = image[box[1] : box[3], box[0] : box[2]]
        found = self._model.predict(np.ascontiguousarray(crop), threshold=self.threshold)
        people = found.class_id == PERSON
        boxes = shift_boxes(found.xyxy[people].astype(np.float32), box)
        return Detections(boxes=boxes.reshape(-1, 4), conf=found.confidence[people])


def _download_rtmpose(folder: Path) -> Path:
    target = folder / "rtmpose-m-body7.onnx"
    if target.exists():
        return target
    folder.mkdir(parents=True, exist_ok=True)
    archive = folder / "rtmpose-m-body7.zip.part"
    urllib.request.urlretrieve(RTMPOSE_URL, archive)  # noqa: S310 (fixed https URL)
    with zipfile.ZipFile(archive) as z:
        member = next(n for n in z.namelist() if n.endswith(".onnx"))
        partial = target.with_suffix(".part")
        partial.write_bytes(z.read(member))
    partial.rename(target)
    archive.unlink()
    return target


class RTMPose:
    """RTMPose-m through onnxruntime. Call it with an RGB frame and n x 4 boxes. Returns
    n x 17 x 3 keypoints as x, y in frame pixels and a score in [0, 1]."""

    def __init__(self) -> None:
        self._session: Any = None

    def _load(self) -> Any:
        import onnxruntime

        available = onnxruntime.get_available_providers()
        providers = [p for p in ("CUDAExecutionProvider", "CPUExecutionProvider") if p in available]
        return onnxruntime.InferenceSession(
            str(_download_rtmpose(cache_dir())), providers=providers
        )

    def __call__(self, image: np.ndarray, boxes: np.ndarray) -> np.ndarray:
        import cv2

        if len(boxes) == 0:
            return np.zeros((0, 17, 3), dtype=np.float32)
        if self._session is None:
            self._session = self._load()
        inputs, regions = [], []
        for box in boxes:
            centre, scale = pose.box_to_centre_scale(box)
            crop = cv2.warpAffine(
                image, pose.warp_matrix(centre, scale), (pose.INPUT_W, pose.INPUT_H)
            )
            inputs.append(((crop.astype(np.float32) - pose.MEAN) / pose.STD).transpose(2, 0, 1))
            regions.append((centre, scale))
        name = self._session.get_inputs()[0].name
        simcc_x, simcc_y = self._session.run(None, {name: np.stack(inputs)})
        locs, scores = pose.decode_simcc(simcc_x, simcc_y)
        out = np.zeros((len(boxes), locs.shape[1], 3), dtype=np.float32)
        for i, (centre, scale) in enumerate(regions):
            out[i, :, :2] = pose.from_input(locs[i], centre, scale)
            out[i, :, 2] = scores[i]
        return out


class DinoEmbedder:
    """DINOv2-small class-token embeddings of person crops, unit length. Call it with an RGB
    frame and n x 4 boxes. Returns n x 384."""

    def __init__(self, device: str | None = None) -> None:
        self.device = device
        self._model: Any = None

    def _load(self) -> Any:
        from transformers import Dinov2Model

        model = Dinov2Model.from_pretrained(DINO, cache_dir=str(cache_dir() / "huggingface"))
        return model.to(self.device or pick_device()).eval()  # type: ignore[arg-type]

    def __call__(self, image: np.ndarray, boxes: np.ndarray) -> np.ndarray:
        import cv2
        import torch

        if len(boxes) == 0:
            return np.zeros((0, 384), dtype=np.float32)
        if self._model is None:
            self._model = self._load()
        h, w = image.shape[:2]
        crops = []
        for box in boxes:
            x1, y1, x2, y2 = clip_region(box, w, h)
            crop = image[y1 : max(y2, y1 + 1), x1 : max(x2, x1 + 1)]
            crop = cv2.resize(crop, (DINO_W, DINO_H), interpolation=cv2.INTER_LINEAR)
            crops.append(((crop.astype(np.float32) - pose.MEAN) / pose.STD).transpose(2, 0, 1))
        device = next(self._model.parameters()).device
        with torch.inference_mode():
            out = self._model(pixel_values=torch.from_numpy(np.stack(crops)).to(device))
        embedding = out.pooler_output.float().cpu().numpy()
        return embedding / np.linalg.norm(embedding, axis=1, keepdims=True)
