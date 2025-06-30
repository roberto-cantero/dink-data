"""
rally_segment_features.py

Compute basic rally-level statistics for pickleball rallies.

Features implemented:
1. AvgSpeed        – mean speed over visible frames (px / frame)
2. TotalDist_px    – cumulative distance travelled by the ball (px)
3. NetCrossings    – number of times the ball switches courts
                     (far ↔ near) using a two-threshold net band.

Author: ChatGPT
"""

from __future__ import annotations
from typing import List, Tuple

import numpy as np
import pandas as pd


def get_initial_segments(df, MAX_MERGE_GAP, MIN_SEGMENT_LENGTH):
    rally_segments = []
    segment_start = None

    for idx, is_active in enumerate(df['IsActive']):
        if is_active and segment_start is None:
            segment_start = idx
        elif not is_active and segment_start is not None:
            # End of current segment
            rally_segments.append((segment_start, idx - 1))
            segment_start = None
    # Handle if the last segment goes to the end
    if segment_start is not None:
        rally_segments.append((segment_start, len(df) - 1))

    # === 5. Merge segments separated by very short gaps ===
    merged_segments = []
    for start, end in rally_segments:
        if merged_segments and (start - merged_segments[-1][1] <= MAX_MERGE_GAP):
            # Merge with previous
            merged_segments[-1] = (merged_segments[-1][0], end)
        else:
            merged_segments.append((start, end))

    # === 6. Filter out very short segments ===
    filtered_segments = [
        (start, end) for start, end in merged_segments
        if (end - start + 1) >= MIN_SEGMENT_LENGTH
    ]

    return filtered_segments

def compute_rally_features(
    frame_df: pd.DataFrame,
    segments: List[Tuple[int, int]],
    fps: int,
    net_y_upper: float,
    net_y_lower: float,
) -> pd.DataFrame:
    """Return rally-level metrics.

    Parameters
    ----------
    frame_df : DataFrame
        Must contain columns 'X', 'Y', 'Speed', 'Visibility'. One row per frame.
    segments : list of (start_frame, end_frame)
        Inclusive indices for each rally.
    fps : int
        Video frame rate.
    net_y_upper, net_y_lower : float
        Pixel y-coordinates bracketing the net band.
        • Y < net_y_upper  ⇒  far court  (-1)
        • Y > net_y_lower  ⇒  near court (+1)
        • net_y_upper ≤ Y ≤ net_y_lower ⇒ net band (0)
    """
    records = []

    for idx, (s, e) in enumerate(segments):
        seg = frame_df.iloc[s : e + 1]

        vis_seg = seg[seg["Visibility"] == 1]
        n_frames = e - s + 1
        duration_sec = n_frames / fps

        # 1. average speed (visible frames only)
        avg_speed = vis_seg["Speed"].mean()

        # 2. total distance travelled
        total_dist = vis_seg["Speed"].sum()

        # 3. net crossings with two-threshold logic
        y_vals = vis_seg["Y"].to_numpy()
        if len(y_vals):
            zones = np.where(
                y_vals < net_y_upper, -1,
                np.where(y_vals > net_y_lower, 1, 0)
            )

            # strip zeros (net band) and consecutive duplicates
            side_seq = [zones[0]] if zones[0] != 0 else []
            for z in zones[1:]:
                if z == 0:
                    continue
                if not side_seq or z != side_seq[-1]:
                    side_seq.append(z)

            # count transitions between -1 and +1
            crossings = sum(
                side_seq[i] != side_seq[i-1] for i in range(1, len(side_seq))
            )
        else:
            crossings = 0

        records.append(
            {
                "RallyIdx": idx,
                "StartFrame": s,
                "EndFrame": e,
                "Duration_sec": duration_sec,
                "AvgSpeed": avg_speed,
                "TotalDist_px": total_dist,
                "NetCrossings": crossings,
            }
        )

    df_out = pd.DataFrame.from_records(records)

    # add absolute time columns for convenience
    df_out["StartTime_sec"] = df_out["StartFrame"] / fps
    df_out["EndTime_sec"]   = df_out["EndFrame"]   / fps

    return df_out

def merge_lob_segments(
    segments: List[Tuple[int, int]],
    frame_df: pd.DataFrame,
    fps: int,
    top_band_y: int = 40,         # Y-position (pixels) for "top of frame" threshold
    max_gap_between_segments: int = 90  # Max gap (frames) to still consider as one rally
) -> List[Tuple[int, int]]:
    """
    Merge consecutive rally segments that were incorrectly split by a lob,
    based on ball exiting and re-entering at the top of the frame.

    Args:
        segments: List of (start_frame, end_frame) tuples for initial rally segments.
        frame_df: DataFrame with columns ['Y', 'Visibility'] (one row per frame).
        fps: Frames per second (not directly used here, but useful for logging/tuning).
        top_band_y: Threshold (in pixels) for considering "top of the frame."
        max_gap_between_segments: Maximum allowed gap (in frames) between merged segments.

    Returns:
        List of (start_frame, end_frame) tuples with lob-related splits fixed.
    """
    merged_segments = []
    i = 0
    while i < len(segments):
        group_start, group_end = segments[i]  # Current group being merged

        while i + 1 < len(segments):
            # Current segment (end) and next segment (start)
            current_end = group_end
            next_start, next_end = segments[i + 1]
            gap_between = next_start - current_end - 1

            # If gap is too large, don't merge
            if gap_between > max_gap_between_segments:
                break

            # --- Check last visible frame of current segment ---
            last_visible_frames = frame_df.iloc[current_end - 4: current_end + 1]
            last_visible_frames = last_visible_frames[last_visible_frames.Visibility == 1]
            if last_visible_frames.empty:
                break
            last_y = last_visible_frames.Y.iloc[-1]
            last_dy = last_visible_frames.Y.diff().iloc[-1]  # Upward motion = negative

            # --- Check first visible frame of next segment ---
            first_visible_frames = frame_df.iloc[next_start: next_start + 5]
            first_visible_frames = first_visible_frames[first_visible_frames.Visibility == 1]
            if len(first_visible_frames) < 2:
                break

            first_y = first_visible_frames.Y.iloc[0]
            first_dy = first_visible_frames.Y.diff().iloc[1]  # Downward motion = positive

            # Merge if ball exited at the top and re-entered at the top
            ball_exited_up = last_y < top_band_y and last_dy < 0
            ball_entered_down = first_y < top_band_y and first_dy > 0

            if ball_exited_up and ball_entered_down:
                # Merge the next segment into the current group
                group_end = next_end
                i += 1
            else:
                break

        merged_segments.append((group_start, group_end))
        i += 1
    return merged_segments
