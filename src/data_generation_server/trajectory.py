"""Deterministic spherical camera trajectories, angles in degrees."""
import math
import random


def orientation_size(orientation, width, height, seed):
    if orientation == 'random':
        orientation = random.Random(seed).choice(['landscape', 'portrait'])
    if orientation == 'keep':
        return width, height, 'landscape' if width >= height else 'portrait'
    long, short = max(width, height), min(width, height)
    return (long, short, orientation) if orientation == 'landscape' else (short, long, orientation)


def camera_angles(trajectory, frames, start, elevation, sweep, theta, phi):
    if frames < 1:
        raise ValueError('At least one frame required')
    if frames == 1:
        # Use the full-trajectory validator, then return its initial viewpoint.
        return camera_angles(trajectory, 2, start, elevation, sweep, theta, phi)[:1]
    if trajectory == 'orbit':
        return [(start + sweep * i / (frames - 1), elevation) for i in range(frames)]
    if theta <= 0 or phi <= 0 or abs(elevation) + phi >= 89:
        raise ValueError('theta/phi must be positive and elevation +/- phi must remain inside (-89, 89)')
    # Right: up, right, down, left, up; then the left mirror.
    waypoints = [(0, 0), (0, phi), (theta, phi), (theta, -phi), (0, -phi),
                 (0, 0), (0, phi), (-theta, phi), (-theta, -phi), (0, -phi), (0, 0)]
    result = []
    for index in range(frames):
        time = 10 * index / (frames - 1)
        leg = min(9, int(time))
        u = time - leg
        # Stop smoothly at each corner: C2 continuous position across all legs.
        eased = u ** 3 * (10 - 15 * u + 6 * u ** 2)
        a, b = waypoints[leg], waypoints[leg + 1]
        result.append((start + a[0] + (b[0] - a[0]) * eased,
                       elevation + a[1] + (b[1] - a[1]) * eased))
    return result


def spherical_position(azimuth, elevation, radius, target):
    azimuth, elevation = math.radians(azimuth), math.radians(elevation)
    return (target[0] + radius * math.cos(elevation) * math.cos(azimuth),
            target[1] + radius * math.cos(elevation) * math.sin(azimuth),
            target[2] + radius * math.sin(elevation))
