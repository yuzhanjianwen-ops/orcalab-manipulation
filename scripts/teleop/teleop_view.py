# -*- coding: utf-8 -*-
"""Optional control-frame presets for teleop.py.

The stock teleop maps the sticks onto the ROBOT BASE frame (``Rb``), which is
correct when you stand behind the robot looking the same way it does.  When you
watch the scene from the opposite side (from in front of the robot, or from a
camera that faces back at it), both axes of the horizontal plane appear
mirrored and the "next arm" choice no longer matches what you see.

This module keeps that knowledge out of the main loop so the stock scheme stays
byte-for-byte unchanged unless a preset is requested.

A preset is just two independent flips:

  flip_lr  - negate the local Y (robot's left/right) component
  flip_fb  - negate the local X (robot's forward/back) component

Flipping both is a 180 deg rotation of the horizontal plane, which is exactly
what "I am looking at the robot from the other side" means.  Vertical (RT/LT)
and wrist rotation are never touched.

`select_arm` is the arm that X switches to, in SCREEN terms, so the operator
does not have to translate "the arm on my left" into the robot's own naming.

Usage:
    from teleop_view import PRESETS, resolve, select_arm
    flips = resolve("behind")            # -> ViewFlip(flip_lr=True, flip_fb=True)
    nxt   = select_arm("r", any_flip)    # -> arm to activate next
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ViewFlip:
    """How to reinterpret the sticks for the operator's viewpoint."""

    name: str = "front"
    flip_lr: bool = False
    flip_fb: bool = False

    @property
    def mirrored(self) -> bool:
        """True when screen left/right no longer matches the robot's own."""
        return self.flip_lr

    def describe(self) -> str:
        if not self.flip_lr and not self.flip_fb:
            return "robot-base (stock)"
        parts = []
        if self.flip_fb:
            parts.append("fwd/back")
        if self.flip_lr:
            parts.append("left/right")
        return "view-mirrored: " + "+".join(parts)

    def apply(self, lx: float, ly: float) -> tuple[float, float]:
        """Rewrite a raw stick pair into the robot-base frame."""
        if self.flip_lr:
            lx = -lx
        if self.flip_fb:
            ly = -ly
        return lx, ly

    def toggle_lr(self) -> "ViewFlip":
        return ViewFlip(self.name + "+lr", not self.flip_lr, self.flip_fb)

    def toggle_fb(self) -> "ViewFlip":
        return ViewFlip(self.name + "+fb", self.flip_lr, not self.flip_fb)


# Presets reachable from the command line.  Names are what the operator types.
PRESETS = {
    # stock behaviour: sticks follow the robot's own axes
    "front": ViewFlip("front", flip_lr=False, flip_fb=False),
    # standing behind / looking back at the robot: full 180 deg turn of the
    # horizontal plane, so "push left" moves the TCP to the screen's left
    "behind": ViewFlip("behind", flip_lr=True, flip_fb=True),
    # only the left/right axis feels wrong
    "flip-lr": ViewFlip("flip-lr", flip_lr=True, flip_fb=False),
    # only forward/back feels wrong
    "flip-fb": ViewFlip("flip-fb", flip_lr=False, flip_fb=True),
}

DEFAULT = "front"


def resolve(name: str) -> ViewFlip:
    """Look up a preset by name; unknown names fall back to the stock scheme."""
    key = (name or DEFAULT).strip().lower().replace("_", "-")
    return PRESETS.get(key, PRESETS[DEFAULT])


def parse_flags(behind: bool, flip_lr: bool, flip_fb: bool) -> ViewFlip:
    """Build a preset from the boolean command-line switches.

    ``--behind`` is a shortcut for flipping both axes; the explicit
    ``--flip-lr`` / ``--flip-fb`` switches override it when given, so the
    operator can dial in just the axis that feels wrong.
    """
    lr = flip_lr or behind
    fb = flip_fb or behind
    if not lr and not fb:
        return PRESETS[DEFAULT]
    name = "custom"
    for preset in PRESETS.values():
        if preset.flip_lr == lr and preset.flip_fb == fb:
            return preset
    return ViewFlip(name, lr, fb)


def select_arm(current: str, flip: ViewFlip) -> str:
    """Arm to activate on the next X press.

    With the stock frame the arms are named the way the robot sees them.  Once
    the horizontal plane is mirrored, the arm the operator perceives as "next"
    is the other one, so the choice has to be mirrored too.
    """
    other = "l" if current == "r" else "r"
    return other


def screen_side(robot_side: str, flip: ViewFlip) -> str:
    """Which side of the SCREEN a robot arm appears on, given the viewpoint."""
    if not flip.flip_lr:
        return robot_side
    return "l" if robot_side == "r" else "r"
