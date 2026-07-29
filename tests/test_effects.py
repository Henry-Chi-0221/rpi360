import unittest

from rpi360 import EFFECT_NAMES, effect_state


class EffectTests(unittest.TestCase):
    def test_tiny_planet_and_rabbit_hole_are_absolute(self):
        tiny = effect_state("tiny-planet", 0.5)
        rabbit = effect_state("rabbit-hole", 0.5)
        self.assertEqual((tiny.projection, tiny.fov, tiny.pitch), (
            "stereographic",
            300.0,
            -90.0,
        ))
        self.assertEqual(tiny.roll, 180.0)
        self.assertEqual(rabbit.pitch, 90.0)
        self.assertEqual(rabbit.roll, -180.0)

    def test_every_effect_has_stable_endpoints(self):
        for name in EFFECT_NAMES:
            start = effect_state(name, -1.0)
            end = effect_state(name, 2.0)
            self.assertEqual(start.yaw if "orbit" in name else start.roll, 0.0)
            self.assertEqual(end.yaw if "orbit" in name else abs(end.roll), 360.0)


if __name__ == "__main__":
    unittest.main()
