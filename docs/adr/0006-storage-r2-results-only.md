# Cloudflare R2 for storage, and production keeps results only

We store sample videos, labels, calibrations, models and results in one R2 bucket, because downloads are free and it is independent of PickleCam's production systems. R2 has no object versioning, so labels and calibrations are written once to versioned paths. In production, workers read each video from Bunny and keep only the results. Copying 67 TB of video a month into R2 would add about $1,000 to the bill every month.
