# SPDX-License-Identifier: MIT
"""Place a global window corner on a visible monitor, in monitor coordinates."""
def monitor_position(rectangles, x, y, width, height):
    if not rectangles:
        raise ValueError("No connected monitors")
    def distance(rect):
        rx, ry, rw, rh = rect
        return (max(rx-x, 0, x-(rx+rw-1))**2, max(ry-y, 0, y-(ry+rh-1))**2)
    index = min(range(len(rectangles)), key=lambda i: distance(rectangles[i]))
    rx, ry, rw, rh = rectangles[index]
    return index, round(max(0, min(x-rx, rw-width))), round(max(0, min(y-ry, rh-height)))
