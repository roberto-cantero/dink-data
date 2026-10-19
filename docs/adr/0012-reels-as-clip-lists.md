# Highlight reels are clip lists, rendered to MP4 only on request

At 4,500 recordings a day, storing four MP4 reels per game would add about 10 TB a month. A reel is a list of clips in `highlights.json`, played from PickleCam's own video by a web player that draws the player marker. A short serverless job renders an MP4 only when a player asks to download or share it, and keeps it for 30 days.
