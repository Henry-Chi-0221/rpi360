"""Deterministic, platform-neutral view effect presets."""

from __future__ import annotations

from dataclasses import dataclass

from .common.player import Player

EFFECT_NAMES = (
    "tiny-planet",
    "inverted-tiny-planet",
    "perspective-orbit",
    "barrel-roll",
)


@dataclass(frozen=True)
class EffectState:
    projection: str
    fov: float
    yaw: float
    pitch: float
    roll: float


def effect_state(name: str, progress: float) -> EffectState:
    """Return an absolute pose for normalized progress in ``[0, 1]``."""
    from .compat.effects import canonical_effect

    effect = canonical_effect(str(name).lower())
    if effect not in EFFECT_NAMES:
        raise ValueError("effect must be one of {}".format(", ".join(EFFECT_NAMES)))
    position = min(1.0, max(0.0, float(progress)))
    sweep = 360.0 * position
    if effect == "tiny-planet":
        return EffectState("stereographic", 300.0, 0.0, -90.0, sweep)
    if effect == "inverted-tiny-planet":
        return EffectState("stereographic", 300.0, 0.0, 90.0, -sweep)
    if effect == "perspective-orbit":
        return EffectState("perspective", 100.0, sweep, -10.0, 0.0)
    return EffectState("perspective", 120.0, 0.0, 0.0, sweep)


def apply_effect(player: Player, name: str, progress: float) -> EffectState:
    """Apply one deterministic effect pose to a Player."""
    state = effect_state(name, progress)
    player.configure(state.projection, fov=state.fov)
    player.set_orientation(state.yaw, state.pitch, state.roll)
    return state


__all__ = ["EFFECT_NAMES", "EffectState", "apply_effect", "effect_state"]
