import cv2

import dinkdata.ball


def test_imports():
    assert dinkdata.ball.__doc__


def test_synthetic_clip_reads_back(synthetic_clip):
    cap = cv2.VideoCapture(str(synthetic_clip))
    try:
        assert cap.get(cv2.CAP_PROP_FPS) == 30
        assert int(cap.get(cv2.CAP_PROP_FRAME_COUNT)) == 60
        assert (cap.get(cv2.CAP_PROP_FRAME_WIDTH), cap.get(cv2.CAP_PROP_FRAME_HEIGHT)) == (320, 180)
    finally:
        cap.release()
