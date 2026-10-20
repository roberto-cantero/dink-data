# Highlight reels are clip lists, rendered to MP4 for the prototype

A reel is a list of clips in `highlights.json`. The prototype renders an MP4 for every player from that list, because DinkData is a standalone app until PickleCam approves it (ADR 0018). In M4, at 4,500 recordings a day, storing four MP4 reels per game would add about 10 TB a month, so a web player plays the clips from PickleCam's own video and draws the player marker. A short serverless job then renders an MP4 only when a player asks to download or share it, and keeps it for 30 days.
