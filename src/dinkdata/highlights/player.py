"""A simple web page that plays one reel's clips from `highlights.json` (DESIGN 6.12 point 1).

M0 needs no exact frames and no title card or marker drawn in the browser: those are M4 work,
once a serverless renderer and tracking exist. The page just seeks a `<video>` through the
reel's clips in order, skipping the gaps between them.
"""

import html
import json
from pathlib import Path

from dinkdata.contracts.highlights import Reel

_TEMPLATE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>{title}</title>
<style>
  body {{ font-family: sans-serif; background: #111; color: #eee; text-align: center; }}
  video {{ max-width: 100%; }}
  #status {{ margin-top: 0.5em; }}
</style>
</head>
<body>
<h1>{title}</h1>
<video id="player" src="{video_src}" controls></video>
<p id="status"></p>
<script>
  const clips = {clips_json};
  const video = document.getElementById("player");
  const status = document.getElementById("status");
  let current = 0;

  function playClip(n) {{
    if (n >= clips.length) {{
      status.textContent = "Reel finished.";
      video.pause();
      return;
    }}
    current = n;
    status.textContent = `Clip ${{n + 1}} of ${{clips.length}}: ${{clips[n].reasons.join(", ")}}`;
    video.currentTime = clips[n].start_t;
    video.play();
  }}

  video.addEventListener("timeupdate", () => {{
    if (current < clips.length && video.currentTime >= clips[current].end_t) {{
      playClip(current + 1);
    }}
  }});

  video.addEventListener("loadedmetadata", () => playClip(0));
</script>
</body>
</html>
"""


def write_player_page(reel: Reel, video_src: str, out: Path, *, title: str | None = None) -> Path:
    """Write a static HTML page at `out` that plays `reel`'s clips, in order, from `video_src`."""
    clips = [{"start_t": c.start_t, "end_t": c.end_t, "reasons": c.reasons} for c in reel.clips]
    page = _TEMPLATE.format(
        title=html.escape(title or f"{reel.game_id} / {reel.player_id} reel"),
        video_src=html.escape(video_src, quote=True),
        clips_json=json.dumps(clips),
    )
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(page)
    return out
