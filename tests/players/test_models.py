"""Device choice and the model wrappers. The wrappers load pretrained weights, so their tests
download them and are marked `data`."""

import numpy as np
import pytest

from dinkdata.players import models


def test_cuda_wins_over_mps(monkeypatch):
    torch = pytest.importorskip("torch")
    monkeypatch.setattr(torch.cuda, "is_available", lambda: True)
    monkeypatch.setattr(torch.backends.mps, "is_available", lambda: True)
    assert models.pick_device() == "cuda"


def test_mps_without_cuda(monkeypatch):
    torch = pytest.importorskip("torch")
    monkeypatch.setattr(torch.cuda, "is_available", lambda: False)
    monkeypatch.setattr(torch.backends.mps, "is_available", lambda: True)
    assert models.pick_device() == "mps"


def test_cpu_without_either(monkeypatch):
    torch = pytest.importorskip("torch")
    monkeypatch.setattr(torch.cuda, "is_available", lambda: False)
    monkeypatch.setattr(torch.backends.mps, "is_available", lambda: False)
    assert models.pick_device() == "cpu"


def test_the_cache_folder_can_be_moved(monkeypatch, tmp_path):
    monkeypatch.setenv("DINKDATA_MODELS", str(tmp_path / "m"))
    assert models.cache_dir() == tmp_path / "m"


def test_regions_are_cropped_inside_the_frame():
    assert models.clip_region((-10, 5, 300, 900), width=200, height=100) == (0, 5, 200, 100)


def test_boxes_from_a_crop_move_back_to_the_frame():
    boxes = np.array([[1.0, 2.0, 3.0, 4.0]])
    assert models.shift_boxes(boxes, (10, 20, 50, 60)).tolist() == [[11, 22, 13, 24]]


@pytest.mark.data
def test_the_detector_finds_nobody_on_an_empty_court(synthetic_clip):
    """A court with no people gives no person boxes."""
    from dinkdata.video.reader import VideoReader

    with VideoReader(synthetic_clip) as video:
        image = video[0].image
    detections = models.PersonDetector(size="nano")(image)
    assert detections.boxes.shape == (0, 4)


@pytest.mark.data
def test_pose_runs_on_a_box():
    image = np.full((256, 192, 3), 120, dtype=np.uint8)
    keypoints = models.RTMPose()(image, np.array([[20.0, 20.0, 170.0, 240.0]]))
    assert keypoints.shape == (1, 17, 3)
    assert ((keypoints[..., 2] >= 0) & (keypoints[..., 2] <= 1)).all()


@pytest.mark.data
def test_dino_embeddings_are_unit_length():
    image = np.full((256, 192, 3), 120, dtype=np.uint8)
    embedding = models.DinoEmbedder()(image, np.array([[20.0, 20.0, 170.0, 240.0]]))
    assert embedding.shape == (1, 384)
    assert np.linalg.norm(embedding[0]) == pytest.approx(1, abs=1e-4)
