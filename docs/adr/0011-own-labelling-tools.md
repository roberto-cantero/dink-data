# Our own studio, with a minimal tool and CVAT first

Generic labelling tools are slow for pickleball events and need converter scripts, which broke the prototype's labels. We build our own studio, which writes our contracts directly and becomes the review tool. Labelling is the critical path, so it doesn't wait for the studio. Rally-level labels start with a minimal local web page, ball clicks start in CVAT with a converter tested for frame alignment, and only full-event gold waits for the studio's events mode.
