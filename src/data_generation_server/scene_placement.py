"""Search nearby support surfaces with unobstructed spherical camera views."""
import math


def find_placement(start, target_height, radius, angles, subject_size, raycast, step=4, rings=8):
    """raycast(origin, direction, distance) returns (hit point, normal), or None.

    Caller excludes the subject and non-rendering geometry. This checks floor support
    and center/edge visibility, not full camera-volume collision or semantic placement.
    """
    offsets = sorted(((x, y) for x in range(-rings, rings + 1) for y in range(-rings, rings + 1)),
                     key=lambda p: (p[0] ** 2 + p[1] ** 2, p))
    unique_angles = sorted(set(tuple(angle) for angle in angles))
    for x, y in offsets:
        px, py = start[0] + x * step, start[1] + y * step
        floor = raycast((px, py, start[2] + 2 * subject_size), (0, 0, -1), 4 * subject_size + 20)
        if floor is None or floor[1][2] < 0.7: continue
        position = (px, py, floor[0][2] + 0.005)
        target = (px, py, position[2] + target_height)
        clear = True
        for azimuth, elevation in unique_angles:
            azimuth, elevation = math.radians(azimuth), math.radians(elevation)
            camera = (px + radius * math.cos(elevation) * math.cos(azimuth),
                      py + radius * math.cos(elevation) * math.sin(azimuth),
                      target[2] + radius * math.sin(elevation))
            # Center plus approximate subject edges catches walls clipping part of the subject.
            for dx, dy, dz in ((0, 0, 0), (-subject_size / 3, 0, 0),
                               (subject_size / 3, 0, 0), (0, 0, subject_size / 3)):
                point = (target[0] + dx, target[1] + dy, target[2] + dz)
                delta = tuple(point[i] - camera[i] for i in range(3))
                length = math.sqrt(sum(value * value for value in delta))
                if raycast(camera, tuple(value / length for value in delta), length - 0.02):
                    clear = False
                    break
            if not clear: break
        if clear: return position
    raise ValueError('No supported, unobstructed placement found within 32 scene units; choose --subject-position manually')
