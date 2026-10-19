# Apache and MIT player models instead of Ultralytics YOLO

We use RF-DETR for people, RTMPose for keypoints and ByteTrack for tracking, plus an MIT appearance model for re-identification. Ultralytics YOLO is AGPL-3.0 and says the license also covers models trained with it, so a closed PickleCam version would need its paid Enterprise license. We switched before training anything, while the switch cost almost nothing. The repo itself stays AGPL-3.0, and PickleCam can relicense its own code because only the two owners contribute.
