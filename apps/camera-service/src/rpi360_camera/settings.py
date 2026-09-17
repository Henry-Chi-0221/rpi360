"""Revisioned sensor controls; persist only after both cameras accept the update."""

from typing import Annotated

from pydantic import BaseModel, Field

Gain = Annotated[float, Field(ge=0.1, le=16, allow_inf_nan=False)]


class CameraSettings(BaseModel):
    revision: int = Field(ge=1)
    auto_exposure: bool = True
    exposure_us: int = Field(default=10000, ge=100, le=30000)
    analogue_gain: Gain = 1
    auto_white_balance: bool = True
    colour_gains: tuple[Gain, Gain] = (1, 1)

    def controls(self):
        result = {"AeEnable": self.auto_exposure, "AwbEnable": self.auto_white_balance}
        if not self.auto_exposure:
            result.update(
                ExposureTime=self.exposure_us, AnalogueGain=self.analogue_gain
            )
        if not self.auto_white_balance:
            result["ColourGains"] = self.colour_gains
        return result
