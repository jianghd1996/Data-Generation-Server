import math
import unittest
from data_generation_server.trajectory import camera_angles, orientation_size, spherical_position


class TrajectoryTests(unittest.TestCase):
    def test_exact_waypoints_and_mirror(self):
        angles = camera_angles('figure8', 121, -90, 12, 90, 30, 5)
        expected = [(-90, 12), (-90, 17), (-60, 17), (-60, 7), (-90, 7),
                    (-90, 12), (-90, 17), (-120, 17), (-120, 7), (-90, 7), (-90, 12)]
        for index, point in enumerate(expected):
            self.assertEqual(angles[index * 12], point)
        for index in range(61):
            self.assertAlmostEqual(angles[index][0] + angles[index + 60][0], -180)
            self.assertAlmostEqual(angles[index][1], angles[index + 60][1])
        self.assertEqual(angles[0], angles[-1])

    def test_sphere_and_bounds(self):
        target = (2, 3, 4)
        for az, el in camera_angles('figure8', 121, -90, 12, 90, 30, 5):
            self.assertTrue(-120 <= az <= -60)
            self.assertTrue(7 <= el <= 17)
            self.assertAlmostEqual(math.dist(spherical_position(az, el, 4.5, target), target), 4.5)
        with self.assertRaises(ValueError): camera_angles('figure8', 121, 0, 88, 90, 30, 5)

    def test_orientation(self):
        self.assertEqual(orientation_size('portrait', 1280, 720, 42), (720, 1280, 'portrait'))
        self.assertEqual(orientation_size('landscape', 720, 1280, 42), (1280, 720, 'landscape'))
        choices = {orientation_size('random', 1280, 720, seed)[2] for seed in range(20)}
        self.assertEqual(choices, {'landscape', 'portrait'})
        self.assertEqual(orientation_size('random', 1280, 720, 42), orientation_size('random', 1280, 720, 42))


if __name__ == '__main__': unittest.main()
