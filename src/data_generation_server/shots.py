"""Shot composition approximations from normalized subject bounds."""
import math


def shot_setup(kind, shot, height, width, image_width, image_height, focal_mm, radius, elevation, phi, chest=0.65, knee=0.28):
    if shot == 'manual':
        return height / 2, radius
    if kind == 'person' and shot == 'far':
        return height / 2, radius  # Preserve the approved full-body distance.
    low = {'near': chest, 'medium': knee, 'far': 0.0}[shot] if kind == 'person' else 0.0
    target = height * (low + 1) / 2
    coverage = {'near': 0.85, 'medium': 0.64, 'far': 0.40}[shot] if kind == 'object' else 0.85
    fx = focal_mm / 36 * min(image_width, image_height) * (1280 / 720)
    vhalf = math.atan(image_height / (2 * fx))
    hhalf = math.atan(image_width / (2 * fx))
    # Fit desired vertical region, with elevation's foreshortening included.
    vertical = height * (1 - low) * math.cos(math.radians(elevation)) / (2 * coverage * math.tan(vhalf))
    horizontal = width / (2 * 0.9 * math.tan(hhalf))
    if kind == 'object':
        return target, max(vertical * coverage, horizontal, 0.1) / coverage
    return target, max(vertical, 0.1)
