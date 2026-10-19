# Pydantic contracts and timestamp-based time

Stages hand work to each other through files whose formats are pydantic models. JSON Schemas are generated from the models, and stages validate files at run time, not only in tests. Every event carries both a frame index and a time in seconds from the video's frame timestamps. PickleCam videos drop frames, so `frame / 30` drifts and is banned.
