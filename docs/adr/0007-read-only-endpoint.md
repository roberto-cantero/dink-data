# Read PickleCam videos through a read-only endpoint, never Bunny keys

Every Bunny Stream library key can also delete customer videos, and the API has no read-only key. No Bunny key leaves PickleCam. The PickleCam backend developer exposes two read-only calls, a video list and short-lived download links, protected by a token, and they return no personal data.
