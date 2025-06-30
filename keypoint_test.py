"""
picklecourt_2d.py – Python 3  •  OpenCV ≥4.x  •  NumPy
--------------------------------------------------------------------
USAGE
-----
$ python picklecourt_2d.py frame.jpg

 • Click the 12 court points in the prompted order.
 • The script pops up a window called “2-D Court” that shows the
   transposed top-down court on a black background (and writes it
   to  court_skeleton.png).

Point order (matches earlier discussion):
 1 TL-corner      5 far-right kitchen  9  far kitchen centre-T
 2 TR-corner      6 near-right kitchen 10 far baseline centre
 3 BR-corner      7 near-left kitchen  11 near baseline centre
 4 BL-corner      8 far kitchen centre-T 12 near kitchen centre-T
"""

import sys, cv2, numpy as np

# ---------- 1. Real-world dimensions (feet) ----------
WIDTH_FT, LENGTH_FT = 20.0, 44.0          # sideline-to-sideline, baseline-to-baseline :contentReference[oaicite:0]{index=0}
KITCHEN_FT          = 7.0                 # non-volley-zone depth :contentReference[oaicite:1]{index=1}
HALF_LEN_FT         = LENGTH_FT / 2       # distance baseline → net

# ---------- 2. Canvas scale ----------
PX_PER_FT = 20                            # 20 px ≈ 1 ft  → 400 × 880 image
CANVAS_W  = int(WIDTH_FT  * PX_PER_FT)
CANVAS_H  = int(LENGTH_FT * PX_PER_FT)

# ---------- 3. Destination (ideal) key-point template ----------
def dst_layout():
    y_far_kitchen  = (HALF_LEN_FT - KITCHEN_FT) * PX_PER_FT
    y_near_kitchen = (HALF_LEN_FT + KITCHEN_FT) * PX_PER_FT
    x_mid = CANVAS_W / 2
    return np.array([
        # corners
        (0,          0),              # 0 TL
        (CANVAS_W,   0),              # 1 TR
        (CANVAS_W,   CANVAS_H),       # 2 BR
        (0,          CANVAS_H),       # 3 BL
        # kitchen / NVZ intersections
        (0,          y_far_kitchen),  # 4 far-left kitchen
        (CANVAS_W,   y_far_kitchen),  # 5 far-right kitchen
        (CANVAS_W,   y_near_kitchen), # 6 near-right kitchen
        (0,          y_near_kitchen), # 7 near-left kitchen
        # centre-line intersections
        (x_mid,      y_far_kitchen),  # 8 far-centre kitchen
        (x_mid,      y_near_kitchen), # 9 near-centre kitchen
        (x_mid,      0),              # 10 far baseline centre
        (x_mid,      CANVAS_H)        # 11 near baseline centre
    ], dtype=np.float32)

DST_PTS = dst_layout()

# ---------- 4. Grab the 12 clicks ----------
src_pts = []
def on_click(ev, x, y, flags, param):
    if ev == cv2.EVENT_LBUTTONDOWN and len(src_pts) < 12:
        src_pts.append((x, y))
        cv2.circle(img_vis, (x, y), 4, (0, 255, 0), -1)
        cv2.imshow(win, img_vis)
        if len(src_pts) < 12:
            cv2.setWindowTitle(win, f"Click point {len(src_pts)+1}/12")
        else:
            cv2.destroyWindow(win)          # close after last click

ball_pts = []
def on_click_ball(ev, x, y, flags, param):
    if ev == cv2.EVENT_LBUTTONDOWN:
        ball_pts.append((x, y))
        cv2.circle(img_vis, (x, y), 4, (0, 255, 0), -1)
        cv2.imshow(win_ball, img_vis)
        cv2.destroyWindow(win_ball)          # close after last click

# ---------- 5. Court-drawing helper ----------
EDGES = [                               # pairs of index numbers
    (0,1),(1,2),(2,3),(3,0),            # outer rectangle
    (4,5),(6,7),                        # kitchen lines
    (4,0),(5,1),(6,2),(7,3),            # sidelines (baseline→kitchen)
    (8,10),(9,11)                       # centre-lines (baseline→kitchen)
]

def visualize_2d(points, w=CANVAS_W, h=CANVAS_H):
    """Return a black canvas with white court lines."""
    canvas = np.zeros((h, w, 3), dtype=np.uint8)
    for i, j in EDGES:
        p1, p2 = tuple(points[i]), tuple(points[j])
        cv2.line(canvas, p1, p2, (255,255,255), 2, cv2.LINE_AA)
    return canvas

# ---------- 6. Main ----------
if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit("Usage: python picklecourt_2d.py frame.jpg")

    img = cv2.imread(sys.argv[1])
    if img is None:
        sys.exit("Cannot read image!")

    img_vis = img.copy()
    win = "Click point 1/12"
    cv2.namedWindow(win, cv2.WINDOW_NORMAL)
    cv2.setMouseCallback(win, on_click)
    cv2.imshow(win, img_vis)
    cv2.waitKey(0)                       # waits until destroyWindow in callback

    if len(src_pts) != 12:
        sys.exit("Need exactly 12 points!")

    # ---- homography & transform (no warp) ----
    H, _      = cv2.findHomography(np.float32(src_pts), DST_PTS, cv2.RANSAC, 5.0)
    src_ref   = cv2.perspectiveTransform(DST_PTS[None,:,:], np.linalg.inv(H))[0]
    court_pts = cv2.perspectiveTransform(np.float32(src_ref)[None,:,:], H)[0].astype(int)

    print(court_pts)

    # ---- draw the court skeleton ----
    court_img = visualize_2d(court_pts)
    cv2.imwrite("court_skeleton.png", court_img)

    # ---- Example hardcoded ball position (image coordinates) ----
    # win_ball = "Click ball"
    # img_vis = img.copy()
    # cv2.namedWindow(win_ball, cv2.WINDOW_NORMAL)
    # cv2.setMouseCallback(win_ball, on_click_ball)
    # cv2.imshow(win_ball, img_vis)
    # cv2.waitKey(0)                       # waits until destroyWindow in callback

    # x_pred, y_pred = ball_pts[0][0], ball_pts[0][1]  # Replace with actual predicted values later

    # # ---- Transform ball to 2D plane ----
    # ball_2d = cv2.perspectiveTransform(
    #     np.array([[[x_pred, y_pred]]], dtype=np.float32), H
    # )[0][0].astype(int)

    # # ---- Draw ball ----
    # cv2.circle(court_img, tuple(ball_2d), 6, (0, 0, 255), -1)  # red dot

    cv2.imshow("2-D Court", court_img)
    cv2.waitKey(0)

    np.save("keypoints/homography.npy", H)                  # image ➜ court transform
    cv2.imwrite("keypoints/court_base.png", court_img)      # clean skeleton (no ball)
    print("[OK] Saved homography.npy and court_base.png")
