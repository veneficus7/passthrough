"""Blender transform -> After Effects transform.

Pure Python, no ``bpy`` and no ``mathutils`` (SPEC.md section 6). Matrices come
in as four rows of four floats, indexed ``m[row][col]``, which is how
``mathutils.Matrix`` presents itself in Python. Everything here is arithmetic on
plain tuples so it can be unit tested without Blender.

Ported from Blender's ``io_export_after_effects`` add-on, as section 7.2
instructs. Two things that port surfaced, both worth knowing:

* Section 7.2 describes a "180 degree reconciliation" for cameras. The
  reference implementation does not do that: it subtracts **90 degrees from X**,
  because an After Effects layer stands upright while a Blender object lies in
  the XY plane. 90 is what is implemented here.
* The reference's lens conversion treats ``sensor_fit='AUTO'`` as horizontal.
  That is wrong for a portrait render: AUTO fits the sensor to the *larger*
  image dimension, so at 1080x1920 the sensor spans the height. Since this
  project targets 1080x1920 (Appendix B), AUTO is handled properly here.
"""

import math

#: After Effects works in pixels; Blender works in metres. The reference
#: add-on hardcodes 100 pixels per Blender unit, and matching it keeps
#: imported scenes the size AE users expect.
DEFAULT_PIXELS_PER_UNIT = 100.0

#: Below this the rotation matrix is treated as gimbal locked.
_GIMBAL_EPSILON = 1e-6


def to_translation(matrix):
    """Translation column of a 4x4 matrix."""
    return (matrix[0][3], matrix[1][3], matrix[2][3])


def to_scale(matrix):
    """Length of each basis column, i.e. the object's scale."""
    return tuple(
        math.sqrt(matrix[0][col] ** 2 + matrix[1][col] ** 2 + matrix[2][col] ** 2)
        for col in range(3)
    )


def to_rotation_matrix(matrix):
    """The 3x3 rotation part, with scale divided out."""
    scale = to_scale(matrix)
    return tuple(
        tuple(matrix[row][col] / scale[col] if scale[col] else 0.0 for col in range(3))
        for row in range(3)
    )


def to_euler_zyx(matrix):
    """Euler angles in radians, Blender's ``ZYX`` order.

    ``ZYX`` means the rotations are applied Z first, then Y, then X, so the
    composed matrix is ``Rx @ Ry @ Rz``. Writing that product out gives::

        R[0][0] = cy*cz     R[0][1] = -cy*sz    R[0][2] = sy
        R[1][2] = -sx*cy    R[2][2] = cx*cy

    which is enough to recover all three angles. Verified element-wise against
    ``mathutils.Matrix.to_euler('ZYX')`` in the integration tests, because
    getting an Euler convention subtly wrong is the classic way to lose a day
    here.
    """
    rot = to_rotation_matrix(matrix)

    sy = max(-1.0, min(1.0, rot[0][2]))
    y = math.asin(sy)
    cy = math.cos(y)

    if abs(cy) < _GIMBAL_EPSILON:
        # Gimbal lock: X and Z become the same axis. Pin Z and fold the whole
        # rotation into X, which is what mathutils does.
        x = math.atan2(sy * rot[1][0], rot[1][1])
        z = 0.0
    else:
        x = math.atan2(-rot[1][2], rot[2][2])
        z = math.atan2(-rot[0][1], rot[0][0])
    return (x, y, z)


def convert_position(location, width, height, pixels_per_unit=DEFAULT_PIXELS_PER_UNIT, aspect=1.0):
    """Blender world location -> After Effects position, in pixels.

    Blender is Z-up and right handed; After Effects is Y-down with Z going into
    the screen, and its origin is the top-left corner of the comp::

        ae_x = ( bx * s) / aspect + width  / 2
        ae_y = (-bz * s)          + height / 2
        ae_z = ( by * s)
    """
    bx, by, bz = location
    return (
        (bx * pixels_per_unit) / aspect + width / 2.0,
        (-bz * pixels_per_unit) + height / 2.0,
        by * pixels_per_unit,
    )


def convert_orientation(euler_zyx, x_rot_correction=False):
    """Blender ZYX Euler (radians) -> After Effects orientation (degrees).

    ``x_rot_correction`` applies to things that point -- cameras and lights.
    """
    x, y, z = euler_zyx
    rx = math.degrees(x)
    ry = -math.degrees(y)
    rz = -math.degrees(z)
    if x_rot_correction:
        rx -= 90.0
    return (rx, ry, rz)


def convert_scale(scale, percent=100.0):
    """Blender scale -> After Effects scale percentages, with axes remapped."""
    sx, sy, sz = scale
    return (sx * percent, sz * percent, sy * percent)


def convert_transform(
    matrix,
    width,
    height,
    pixels_per_unit=DEFAULT_PIXELS_PER_UNIT,
    aspect=1.0,
    x_rot_correction=False,
):
    """Full transform conversion. Returns ``(position, orientation, scale)``."""
    position = convert_position(to_translation(matrix), width, height, pixels_per_unit, aspect)
    orientation = convert_orientation(to_euler_zyx(matrix), x_rot_correction)
    scale = convert_scale(to_scale(matrix))
    return position, orientation, scale


def unwrap_degrees(previous, current):
    """Shift ``current`` by whole turns so it is nearest ``previous``.

    ``atan2`` wraps at +/-180, so an orientation track can jump from 179 to
    -179 between frames. After Effects interpolates that literally and spins the
    camera 358 degrees. Unwrapping keeps the track continuous, which is what
    "the animation matches Blender's" actually requires.
    """
    return current + 360.0 * round((previous - current) / 360.0)


def unwrap_track(orientations):
    """Apply :func:`unwrap_degrees` down a sequence of ``(rx, ry, rz)``."""
    unwrapped = []
    previous = None
    for orientation in orientations:
        if previous is None:
            current = tuple(orientation)
        else:
            current = tuple(
                unwrap_degrees(prev_axis, axis)
                for prev_axis, axis in zip(previous, orientation, strict=True)
            )
        unwrapped.append(current)
        previous = current
    return unwrapped


def effective_sensor(sensor_fit, sensor_width, sensor_height, resolution_x, resolution_y):
    """Which sensor dimension Blender actually uses, and which image axis it spans.

    Returns ``(sensor_mm, axis)`` where axis is ``"HORIZONTAL"`` or
    ``"VERTICAL"``.

    ``AUTO`` is the case worth care: Blender applies ``sensor_width`` to the
    *larger* image dimension, so a portrait render fits the sensor vertically.
    """
    if sensor_fit == "VERTICAL":
        return sensor_height, "VERTICAL"
    if sensor_fit == "HORIZONTAL":
        return sensor_width, "HORIZONTAL"
    if resolution_x >= resolution_y:
        return sensor_width, "HORIZONTAL"
    return sensor_width, "VERTICAL"


def zoom_from_lens(lens_mm, sensor_fit, sensor_width, sensor_height, width, height, aspect=1.0):
    """Focal length -> After Effects camera zoom, in pixels.

    After Effects expresses field of view as a zoom distance in pixels::

        zoom / dimension = lens / sensor

    where ``dimension`` is whichever comp axis the sensor spans.
    """
    sensor_mm, axis = effective_sensor(sensor_fit, sensor_width, sensor_height, width, height)
    dimension = width if axis == "HORIZONTAL" else height
    return lens_mm * dimension / sensor_mm * aspect
