# Hand-downloaded games use the catalog's HMAC ids

The first gold games are downloaded by hand before `dink catalog sync` exists. Their `video_id` comes from the same function the catalog will use: `v_` and the first 16 hex characters of HMAC-SHA256 over the session id, keyed with `DINKDATA_ID_KEY` from `.env`. `uv run --env-file .env dink id video` asks for the session id at a hidden prompt, so it never reaches shell history, and prints only the id. Labels made now keep their ids once the catalog exists. 16 hex characters are 64 bits, enough to avoid collisions at 4,500 videos a day.
