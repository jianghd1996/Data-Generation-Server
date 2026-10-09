import unittest
from data_generation_server.scene_placement import find_placement


class PlacementTests(unittest.TestCase):
    def test_moves_off_blocked_origin_and_uses_floor_height(self):
        def raycast(origin, direction, distance):
            if direction == (0, 0, -1): return ((origin[0], origin[1], 1.5), (0, 0, 1))
            endpoint = tuple(origin[i] + direction[i] * distance for i in range(3))
            if abs(endpoint[0]) < 1 and abs(endpoint[1]) < 1:
                return (origin, (0, 1, 0))
            return None
        position = find_placement((0, 0, 0), 1, 4.5, [(-90, 12), (-60, 17)], 2, raycast)
        self.assertNotEqual(position[:2], (0, 0))
        self.assertAlmostEqual(position[2], 1.505)

    def test_no_clear_support_fails_instead_of_using_bad_origin(self):
        with self.assertRaisesRegex(ValueError, 'No supported'):
            find_placement((0, 0, 0), 1, 4.5, [(-90, 12)], 2, lambda *args: None, rings=0)
