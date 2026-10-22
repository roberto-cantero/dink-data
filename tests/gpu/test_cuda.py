"""GPU smoke test for the Docker image, run on a pod with `uv run pytest -m gpu` (#44)."""

import pytest

pytestmark = pytest.mark.gpu

torch = pytest.importorskip("torch")


@pytest.fixture(autouse=True)
def _needs_cuda() -> None:
    if not torch.cuda.is_available():
        pytest.skip("no CUDA GPU")


def test_torch_is_the_cuda_build() -> None:
    assert torch.version.cuda is not None
    assert torch.version.cuda.startswith("12.6")


def test_matmul_on_the_gpu_matches_the_cpu() -> None:
    generator = torch.Generator().manual_seed(0)
    a = torch.randn(512, 512, generator=generator)
    b = torch.randn(512, 512, generator=generator)
    on_gpu = (a.cuda() @ b.cuda()).cpu()
    assert torch.allclose(on_gpu, a @ b, atol=1e-3, rtol=1e-3)


def test_torchvision_runs_cuda_kernels() -> None:
    from torchvision.ops import nms

    boxes = torch.tensor([[0, 0, 10, 10], [1, 1, 11, 11], [50, 50, 60, 60]], dtype=torch.float32)
    scores = torch.tensor([0.9, 0.8, 0.7])
    kept = nms(boxes.cuda(), scores.cuda(), iou_threshold=0.5).cpu().tolist()
    assert kept == [0, 2]


def test_video_libraries_import() -> None:
    import av
    import cv2

    assert av.__version__
    assert cv2.__version__
