# Start from scratch instead of porting the prototype

The prototype in `legacy/` was a fork of TrackNetV3, a badminton ball tracker, retrained on pickleball. Its trained checkpoints and labels are lost, and its code assumed a CUDA GPU, loaded whole videos into memory, assumed 1280×720 at 30 fps and measured speeds in pixels. We tagged it `legacy-prototype` and deleted it, and we write the new pipeline from the papers and `docs/DESIGN.md`.

## Lessons kept from the prototype

- Load nothing at import time. The prototype crashed on a fresh clone because it read calibration files on import.
- Use `pathlib`. Backslash paths broke it on macOS and Linux.
- Hold out whole facilities for testing. Its test rallies came from its training matches, so its accuracy was optimistic.
- Project only floor points (feet, bounces) through the court mapping, never a ball in the air.
- Work in court feet and seconds, never pixels per frame or hand-tuned pixel bands.
- Name calibration points, never number them. Its click order was mislabelled.
- Check label frame alignment with a test. Its CVAT frame offsets depended on task order.
