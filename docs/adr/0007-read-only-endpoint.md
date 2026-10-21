# Read PickleCam videos through a read-only endpoint, never Bunny keys

Every Bunny Stream library key can also delete customer videos, and the API has no read-only key. No Bunny key leaves PickleCam. The PickleCam backend developer exposes a read-only call, protected by a token, that returns no personal data. ADR 0017 cut the original two calls, a video list and short-lived download links, to one list that includes the links, and ADR 0018 moved the endpoint to after the prototype.
