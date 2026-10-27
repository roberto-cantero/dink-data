"""Colour features of a player's shirt and shorts, placed with the keypoints."""

import numpy as np

from dinkdata.players.appearance import body_regions, colour_feature, cosine

RED, BLUE, WHITE, GREY = (200, 30, 30), (30, 40, 200), (235, 235, 235), (90, 90, 90)


def player_image(shirt, shorts, background=GREY, noise=0, seed=0):
    """A 200x100 RGB picture of a player: shirt in rows 40 to 100, shorts in rows 100 to 140."""
    image = np.empty((200, 100, 3), dtype=np.uint8)
    image[:] = background
    image[40:100, 30:70] = shirt
    image[100:140, 32:68] = shorts
    if noise:
        jitter = np.random.default_rng(seed).integers(-noise, noise + 1, image.shape)
        image = np.clip(image.astype(int) + jitter, 0, 255).astype(np.uint8)
    return image


def keypoints():
    kp = np.zeros((17, 3), dtype=np.float32)
    kp[5], kp[6] = (32, 40, 0.9), (68, 40, 0.9)  # shoulders
    kp[11], kp[12] = (36, 100, 0.9), (64, 100, 0.9)  # hips
    kp[13], kp[14] = (36, 140, 0.9), (64, 140, 0.9)  # knees
    return kp


BOX = (20.0, 10.0, 80.0, 195.0)


def test_regions_follow_the_keypoints():
    torso, legs = body_regions(BOX, keypoints())
    assert torso[1] >= 40 and torso[3] <= 100
    assert legs[1] >= 100 and legs[3] <= 140
    assert torso[0] >= 32 and torso[2] <= 68


def test_regions_fall_back_to_shares_of_the_box_without_keypoints():
    torso, legs = body_regions(BOX, np.zeros((17, 3), dtype=np.float32))
    assert BOX[1] < torso[1] < torso[3] <= legs[1] < legs[3] < BOX[3]


def test_the_same_clothes_look_alike_through_noise():
    a = colour_feature(player_image(RED, BLUE, noise=12, seed=1), BOX, keypoints())
    b = colour_feature(player_image(RED, BLUE, noise=12, seed=2), BOX, keypoints())
    assert cosine(a, b) > 0.9


def test_swapped_shirt_and_shorts_look_different():
    a = colour_feature(player_image(RED, BLUE), BOX, keypoints())
    b = colour_feature(player_image(BLUE, RED), BOX, keypoints())
    assert cosine(a, b) < 0.5


def test_white_and_grey_shirts_differ_by_brightness():
    a = colour_feature(player_image(WHITE, BLUE), BOX, keypoints())
    b = colour_feature(player_image(GREY, BLUE), BOX, keypoints())
    assert cosine(a, b) < 0.9


def test_the_feature_is_unit_length():
    feature = colour_feature(player_image(RED, BLUE), BOX, keypoints())
    assert abs(np.linalg.norm(feature) - 1) < 1e-6
