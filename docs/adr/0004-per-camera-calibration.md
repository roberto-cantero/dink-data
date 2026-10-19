# Calibrate each camera once with a lens model

PickleCam cameras are fixed, have wide-angle lenses, and often don't show all four corners. A 4-corner homography would be wrong, so each camera gets one calibration from clicked points, lines and the net top. The fit uses a pinhole camera with radial distortion, and lens parameters are shared across cameras of the same model. Every video from that camera reuses the calibration, and a camera-moved check flags it when the court lines stop matching. The mapping applies only to points on the floor.
