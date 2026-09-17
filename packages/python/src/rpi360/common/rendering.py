"""Shared dual-fisheye stitching and view projection renderer.

The geometry is intentionally expressed as small vector transformations. This
keeps the mathematical path from output pixel to source pixel visible:

``output pixel -> unit ray -> camera ray -> fisheye pixel``.
"""

from __future__ import annotations

import hashlib
import math
import threading
from collections import OrderedDict
from dataclasses import dataclass
from typing import Any, Dict, Optional, Tuple

import cv2
import numpy as np

from .types import (
    CalibrationProfile,
    CameraCalibration,
    OrientationState,
    RenderResult,
    ViewConfig,
    rotation_matrix_from_euler,
    validate_calibration,
)

_STITCH_GEOMETRY_CACHE: "OrderedDict[Tuple[Any, ...], Dict[str, np.ndarray]]" = (
    OrderedDict()
)
_STITCH_GEOMETRY_CACHE_SIZE = 2
_VIEW_RAY_CACHE: "OrderedDict[Tuple[Any, ...], np.ndarray]" = OrderedDict()
_VIEW_RAY_CACHE_SIZE = 2
_VIEW_MAP_CACHE: "OrderedDict[Tuple[Any, ...], RemapMaps]" = OrderedDict()
_VIEW_MAP_CACHE_SIZE = 4
_GEOMETRY_CACHE_LOCK = threading.RLock()
RemapMaps = Tuple[np.ndarray, Optional[np.ndarray]]


def camera1_mount_rotation() -> np.ndarray:
    """Return the fixed back-to-back camera-1 mounting rotation."""
    return rotation_matrix_from_euler(
        yaw_deg=180.0,
        pitch_deg=0.0,
        roll_deg=180.0,
    )


@dataclass
class EquirectangularStages:
    """The three observable products of dual-fisheye Stage 1."""

    equi_1: np.ndarray
    equi_2: np.ndarray
    equi_blended: np.ndarray


def _require_bgr_image(image: np.ndarray, name: str) -> np.ndarray:
    array = np.asarray(image)
    if array.ndim != 3 or array.shape[2] != 3:
        raise ValueError(f"{name} must be an HxWx3 BGR image, got {array.shape}")
    if array.shape[0] <= 0 or array.shape[1] <= 0:
        raise ValueError(f"{name} must not be empty")
    if array.dtype != np.uint8:
        if np.issubdtype(array.dtype, np.floating):
            maximum = float(np.nanmax(array)) if array.size else 0.0
            scale = 255.0 if maximum <= 1.0 else 1.0
            array = np.clip(array * scale, 0.0, 255.0).astype(np.uint8)
        else:
            array = np.clip(array, 0, 255).astype(np.uint8)
    return np.ascontiguousarray(array)


def equirectangular_pixels_to_unit_rays(width: int, height: int) -> np.ndarray:
    """Reproduce Mapper.equi_to_unit_equi/unit_equi_to_3d_vector."""
    if width <= 0 or height <= 0:
        raise ValueError("width and height must be positive")
    pixel_x, pixel_y = np.meshgrid(
        np.arange(width, dtype=np.float64),
        np.arange(height, dtype=np.float64),
    )
    longitude = (pixel_x / (width / 2.0) - 1.0) * np.pi
    latitude = (pixel_y / height - 0.5) * np.pi

    cos_latitude = np.cos(latitude)
    ray_x = cos_latitude * np.sin(longitude)
    ray_y = np.sin(latitude)
    ray_z = cos_latitude * np.cos(longitude)
    return np.stack((ray_x, ray_y, ray_z), axis=-1)


def unit_rays_to_equirectangular_map(
    rays: np.ndarray, width: int, height: int
) -> Tuple[np.ndarray, np.ndarray]:
    """Convert unit rays to floating-point equirectangular source pixels."""
    vectors = np.asarray(rays, dtype=np.float64)
    if vectors.shape[-1] != 3:
        raise ValueError("rays must have shape (..., 3)")
    norm = np.linalg.norm(vectors, axis=-1, keepdims=True)
    vectors = vectors / np.maximum(norm, 1e-12)
    ray_x, ray_y, ray_z = np.moveaxis(vectors, -1, 0)

    longitude = np.arctan2(ray_x, ray_z)
    latitude = np.arctan2(ray_y, np.sqrt(ray_x * ray_x + ray_z * ray_z))

    map_x = (longitude / np.pi + 1.0) * (width / 2.0)
    map_y = (latitude / np.pi + 0.5) * height
    map_x = np.mod(map_x, width)
    map_y = np.clip(map_y, 0.0, height - 1.0)
    return map_x.astype(np.float32), map_y.astype(np.float32)


def project_unit_rays_to_fisheye(
    camera_rays: np.ndarray,
    calibration: CameraCalibration,
    frame_width: int,
    frame_height: int,
) -> Tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Project camera-coordinate rays with the OpenCV fisheye model.

    This is the vectorized form of the equidistant geometry used by the
    original prototype. The four distortion coefficients extend its radial
    angle mapping:

    ``theta_d = theta * (1 + k1*theta^2 + ... + k4*theta^8)``.
    """
    rays = np.asarray(camera_rays, dtype=np.float64)
    if rays.shape[-1] != 3:
        raise ValueError("camera_rays must have shape (..., 3)")
    norm = np.linalg.norm(rays, axis=-1, keepdims=True)
    rays = rays / np.maximum(norm, 1e-12)
    ray_x, ray_y, ray_z = np.moveaxis(rays, -1, 0)

    radial = np.sqrt(ray_x * ray_x + ray_y * ray_y)
    theta = np.arctan2(radial, ray_z)
    theta2 = theta * theta
    k1, k2, k3, k4 = calibration.D
    theta_distorted = theta * (
        1.0 + k1 * theta2 + k2 * theta2**2 + k3 * theta2**3 + k4 * theta2**4
    )

    # At the optical axis theta/r tends to one for a unit forward ray.
    angular_scale = np.divide(
        theta_distorted,
        radial,
        out=np.ones_like(theta_distorted),
        where=radial > 1e-12,
    )
    normalized_x = angular_scale * ray_x
    # Mapper rays and OpenCV image coordinates both use +y downward.
    normalized_y = angular_scale * ray_y

    K = calibration.scaled_K(frame_width, frame_height)
    map_x = K[0, 0] * normalized_x + K[0, 1] * normalized_y + K[0, 2]
    map_y = K[1, 1] * normalized_y + K[1, 2]

    backward_axis_is_singular = (radial <= 1e-12) & (ray_z < 0.0)
    # OpenCV's fisheye polynomial is only calibrated inside the physical
    # lens circle. Extrapolating it toward the rear hemisphere can fold rays
    # back into the rectangular sensor and create duplicated/mirrored content.
    maximum_theta = math.radians(calibration.fisheye_fov_deg * 0.5)
    within_physical_fov = theta <= maximum_theta + 1e-9
    valid = (
        np.isfinite(map_x)
        & np.isfinite(map_y)
        & ~backward_axis_is_singular
        & within_physical_fov
        & (map_x >= 0.0)
        & (map_x <= frame_width - 1.0)
        & (map_y >= 0.0)
        & (map_y <= frame_height - 1.0)
    )

    # Pixels near a sensor edge receive less weight. In the overlap this
    # creates a stable feather without hiding either camera's valid interior.
    edge_distance = np.minimum.reduce(
        (
            map_x + 0.5,
            frame_width - 0.5 - map_x,
            map_y + 0.5,
            frame_height - 0.5 - map_y,
        )
    )
    feather_pixels = max(2.0, min(frame_width, frame_height) * 0.08)
    reliability = np.clip(edge_distance / feather_pixels, 0.0, 1.0)
    reliability = np.where(valid, np.maximum(reliability, 1e-3), 0.0)
    return (
        map_x.astype(np.float32),
        map_y.astype(np.float32),
        valid,
        reliability.astype(np.float32),
    )


def _calibration_fingerprint(calibration: CalibrationProfile) -> str:
    digest = hashlib.sha1()
    for camera in (calibration.camera0, calibration.camera1):
        dimensions = np.asarray([camera.width, camera.height], dtype=np.int64)
        digest.update(dimensions.tobytes())
        digest.update(camera.K.tobytes())
        digest.update(camera.D.tobytes())
        digest.update(
            np.asarray([camera.fisheye_fov_deg], dtype=np.float64).tobytes()
        )
    digest.update(calibration.R_cam1_to_cam0.tobytes())
    return digest.hexdigest()


def _stitch_geometry(
    calibration: CalibrationProfile,
    frame0_shape: Tuple[int, ...],
    frame1_shape: Tuple[int, ...],
    width: int,
    height: int,
) -> Dict[str, np.ndarray]:
    key = (
        _calibration_fingerprint(calibration),
        tuple(frame0_shape[:2]),
        tuple(frame1_shape[:2]),
        int(width),
        int(height),
    )
    with _GEOMETRY_CACHE_LOCK:
        cached = _STITCH_GEOMETRY_CACHE.get(key)
        if cached is not None:
            _STITCH_GEOMETRY_CACHE.move_to_end(key)
            return cached

    rays_cam0 = equirectangular_pixels_to_unit_rays(width, height)

    # Strict original Mapper order:
    #   vector = vector @ R
    #   vector = rotate_vectors(vector, yaw=180, pitch=0, roll=180)
    # The second rotation describes the back-to-back camera mounting while R
    # is the measured equi_2-to-equi_1 alignment.
    camera1_mount = camera1_mount_rotation()
    rays_cam1 = rays_cam0 @ calibration.R_cam1_to_cam0 @ camera1_mount

    map0_x, map0_y, valid0, weight0 = project_unit_rays_to_fisheye(
        rays_cam0,
        calibration.camera0,
        frame0_shape[1],
        frame0_shape[0],
    )
    map1_x, map1_y, valid1, weight1 = project_unit_rays_to_fisheye(
        rays_cam1,
        calibration.camera1,
        frame1_shape[1],
        frame1_shape[0],
    )
    geometry = {
        "map0_x": map0_x,
        "map0_y": map0_y,
        "map1_x": map1_x,
        "map1_y": map1_y,
        "valid0": valid0,
        "valid1": valid1,
        "weight0": weight0,
        "weight1": weight1,
    }
    with _GEOMETRY_CACHE_LOCK:
        existing = _STITCH_GEOMETRY_CACHE.get(key)
        if existing is not None:
            _STITCH_GEOMETRY_CACHE.move_to_end(key)
            return existing
        _STITCH_GEOMETRY_CACHE[key] = geometry
        _STITCH_GEOMETRY_CACHE.move_to_end(key)
        while len(_STITCH_GEOMETRY_CACHE) > _STITCH_GEOMETRY_CACHE_SIZE:
            _STITCH_GEOMETRY_CACHE.popitem(last=False)
    return geometry


def _interpolation_for_quality(quality: str) -> int:
    quality = str(quality).lower()
    if quality == "fast":
        return cv2.INTER_NEAREST
    if quality == "balanced":
        return cv2.INTER_LINEAR
    if quality == "high":
        return cv2.INTER_LANCZOS4
    raise ValueError("quality must be 'fast', 'balanced', or 'high'")


def blend_equirectangular_mapper(
    equi_1: np.ndarray,
    equi_2: np.ndarray,
    feather_width_deg: float = 10.0,
) -> np.ndarray:
    """Exact fixed 90°/270° smoothstep blend from original Mapper."""
    image1 = _require_bgr_image(equi_1, "equi_1")
    image2 = _require_bgr_image(equi_2, "equi_2")
    if image1.shape != image2.shape:
        raise ValueError(f"equi_1 shape {image1.shape} != equi_2 shape {image2.shape}")
    if not math.isfinite(float(feather_width_deg)) or feather_width_deg <= 0.0:
        raise ValueError("feather_width_deg must be finite and positive")

    _, width = image1.shape[:2]
    start = int(90.0 / 360.0 * width)
    end = int(270.0 / 360.0 * width)
    feather = max(1, int(feather_width_deg / 360.0 * width))
    half_feather = feather // 2
    left0 = max(start - half_feather, 0)
    left1 = min(start + half_feather, width)
    right0 = max(end - half_feather, 0)
    right1 = min(end + half_feather, width)

    alpha = np.zeros(width, dtype=np.float32)
    alpha[start:end] = 1.0
    if left1 > left0:
        transition = np.linspace(0.0, 1.0, left1 - left0, dtype=np.float32)
        alpha[left0:left1] = transition * transition * (3.0 - 2.0 * transition)
    if right1 > right0:
        transition = np.linspace(1.0, 0.0, right1 - right0, dtype=np.float32)
        alpha[right0:right1] = transition * transition * (3.0 - 2.0 * transition)

    blended = image2.copy()
    if right0 > left1:
        blended[:, left1:right0] = image1[:, left1:right0]
    for x0, x1 in ((left0, left1), (right0, right1)):
        if x1 <= x0:
            continue
        strip_alpha = alpha[x0:x1][None, :, None]
        strip = image1[:, x0:x1].astype(np.float32) * strip_alpha + image2[
            :, x0:x1
        ].astype(np.float32) * (1.0 - strip_alpha)
        blended[:, x0:x1] = np.clip(strip, 0.0, 255.0).astype(np.uint8)
    return blended


def stitch_equirectangular_stages(
    frame0: np.ndarray,
    frame1: np.ndarray,
    calibration: CalibrationProfile,
    width: int,
    height: int,
    quality: str = "balanced",
) -> EquirectangularStages:
    """Project both BGR fisheyes and blend with Mapper's fixed two seams."""
    image0 = _require_bgr_image(frame0, "frame0")
    image1 = _require_bgr_image(frame1, "frame1")
    validate_calibration(calibration)
    if int(width) <= 0 or int(height) <= 0:
        raise ValueError("equirectangular width and height must be positive")
    interpolation = _interpolation_for_quality(quality)
    geometry = _stitch_geometry(
        calibration, image0.shape, image1.shape, int(width), int(height)
    )

    sampled0 = cv2.remap(
        image0,
        geometry["map0_x"],
        geometry["map0_y"],
        interpolation=interpolation,
        borderMode=cv2.BORDER_CONSTANT,
        borderValue=0,
    )
    sampled1 = cv2.remap(
        image1,
        geometry["map1_x"],
        geometry["map1_y"],
        interpolation=interpolation,
        borderMode=cv2.BORDER_CONSTANT,
        borderValue=0,
    )
    sampled0[~geometry["valid0"]] = 0
    sampled1[~geometry["valid1"]] = 0

    return EquirectangularStages(
        equi_1=sampled0,
        equi_2=sampled1,
        equi_blended=blend_equirectangular_mapper(sampled0, sampled1),
    )


def stitch_equirectangular(
    frame0: np.ndarray,
    frame1: np.ndarray,
    calibration: CalibrationProfile,
    width: int,
    height: int,
    quality: str = "balanced",
) -> np.ndarray:
    """Compatibility helper returning only the blended Stage 1 panorama."""
    return stitch_equirectangular_stages(
        frame0, frame1, calibration, width, height, quality
    ).equi_blended


def perspective_pixels_to_unit_rays(
    width: int, height: int, horizontal_fov_deg: float
) -> np.ndarray:
    """Back-project perspective pixels into view-local unit rays."""
    if width <= 0 or height <= 0:
        raise ValueError("width and height must be positive")
    if not 0.0 < float(horizontal_fov_deg) < 180.0:
        raise ValueError("horizontal_fov_deg must be between 0 and 180")

    half_width = math.tan(math.radians(horizontal_fov_deg) * 0.5)
    half_height = half_width * (height / float(width))
    pixel_x, pixel_y = np.meshgrid(
        np.arange(width, dtype=np.float64) + 0.5,
        np.arange(height, dtype=np.float64) + 0.5,
    )
    ray_x = (pixel_x / width * 2.0 - 1.0) * half_width
    ray_y = (pixel_y / height * 2.0 - 1.0) * half_height
    ray_z = np.ones_like(ray_x)
    rays = np.stack((ray_x, ray_y, ray_z), axis=-1)
    return rays / np.linalg.norm(rays, axis=-1, keepdims=True)


def stereographic_pixels_to_unit_rays(
    width: int, height: int, horizontal_fov_deg: float
) -> np.ndarray:
    """Exact vectorized form of Mapper.stereographic_to_vector."""
    if width <= 0 or height <= 0:
        raise ValueError("width and height must be positive")
    if not 0.0 < float(horizontal_fov_deg) < 360.0:
        raise ValueError("horizontal_fov_deg must be between 0 and 360")

    pixel_x, pixel_y = np.meshgrid(
        np.arange(width, dtype=np.float64),
        np.arange(height, dtype=np.float64),
    )
    half_width = math.tan(math.radians(horizontal_fov_deg * 0.25))
    half_height = half_width * (height / float(width))
    plane_x = (pixel_x - width / 2.0) * (2.0 * half_width / width)
    plane_y = (pixel_y - height / 2.0) * (2.0 * half_height / height)
    radius_squared = plane_x * plane_x + plane_y * plane_y
    denominator = 1.0 + radius_squared

    ray_x = 2.0 * plane_x / denominator
    ray_y = 2.0 * plane_y / denominator
    ray_z = (1.0 - radius_squared) / denominator
    rays = np.stack((ray_x, ray_y, ray_z), axis=-1)
    return rays / np.maximum(np.linalg.norm(rays, axis=-1, keepdims=True), 1e-12)


def _sample_equirectangular(
    equirectangular: np.ndarray,
    world_rays: Optional[np.ndarray],
    quality: str,
    valid: Optional[np.ndarray] = None,
    maps: Optional[RemapMaps] = None,
) -> np.ndarray:
    image = _require_bgr_image(equirectangular, "equirectangular")
    height, width = image.shape[:2]
    # Longitude is periodic, but latitude is not. A one-pixel horizontal
    # wrap lets nearest/linear interpolation cross 360° -> 0° without
    # sampling BORDER_CONSTANT, while BORDER_REPLICATE remains correct at
    # the north and south image edges.
    sampling_image = cv2.copyMakeBorder(
        image,
        0,
        0,
        1,
        1,
        borderType=cv2.BORDER_WRAP,
    )
    if maps is None:
        if world_rays is None:
            raise ValueError("world_rays are required when maps are not supplied")
        map_x, map_y = unit_rays_to_equirectangular_map(world_rays, width, height)
        map_x = map_x + 1.0
    else:
        map_x, map_y = maps

    sampled = cv2.remap(
        sampling_image,
        map_x,
        map_y,
        interpolation=_interpolation_for_quality(quality),
        borderMode=cv2.BORDER_REPLICATE,
    )
    if valid is not None:
        sampled = sampled.copy()
        sampled[~valid] = 0
    return sampled


def _base_view_rays(
    projection: str,
    width: int,
    height: int,
    horizontal_fov_deg: float,
) -> np.ndarray:
    key = (
        str(projection),
        int(width),
        int(height),
        float(horizontal_fov_deg),
    )
    with _GEOMETRY_CACHE_LOCK:
        cached = _VIEW_RAY_CACHE.get(key)
        if cached is not None:
            _VIEW_RAY_CACHE.move_to_end(key)
            return cached
    if projection == "perspective":
        rays = perspective_pixels_to_unit_rays(width, height, horizontal_fov_deg)
    elif projection == "stereographic":
        rays = stereographic_pixels_to_unit_rays(width, height, horizontal_fov_deg)
    else:
        raise ValueError("view ray cache only supports projected views")
    rays.setflags(write=False)
    with _GEOMETRY_CACHE_LOCK:
        existing = _VIEW_RAY_CACHE.get(key)
        if existing is not None:
            _VIEW_RAY_CACHE.move_to_end(key)
            return existing
        _VIEW_RAY_CACHE[key] = rays
        _VIEW_RAY_CACHE.move_to_end(key)
        while len(_VIEW_RAY_CACHE) > _VIEW_RAY_CACHE_SIZE:
            _VIEW_RAY_CACHE.popitem(last=False)
    return rays


def _equirectangular_view_maps(
    panorama_width: int,
    panorama_height: int,
    orientation: OrientationState,
    projection: str,
    output_width: int,
    output_height: int,
    horizontal_fov_deg: float,
    quality: str,
) -> RemapMaps:
    rotation = np.ascontiguousarray(orientation.rotation_matrix, dtype=np.float64)
    interpolation = _interpolation_for_quality(quality)
    nearest = interpolation == cv2.INTER_NEAREST
    key = (
        int(panorama_width),
        int(panorama_height),
        str(projection),
        int(output_width),
        int(output_height),
        float(horizontal_fov_deg),
        rotation.tobytes(),
        nearest,
    )
    with _GEOMETRY_CACHE_LOCK:
        cached = _VIEW_MAP_CACHE.get(key)
        if cached is not None:
            _VIEW_MAP_CACHE.move_to_end(key)
            return cached

    view_rays = _base_view_rays(
        projection,
        output_width,
        output_height,
        horizontal_fov_deg,
    )
    world_rays = view_rays @ rotation
    float_maps = unit_rays_to_equirectangular_map(
        world_rays,
        panorama_width,
        panorama_height,
    )
    maps = cv2.convertMaps(
        float_maps[0] + 1.0,
        float_maps[1],
        cv2.CV_16SC2,
        nninterpolation=nearest,
    )
    for map_axis in maps:
        if map_axis is not None:
            map_axis.setflags(write=False)
    with _GEOMETRY_CACHE_LOCK:
        existing = _VIEW_MAP_CACHE.get(key)
        if existing is not None:
            _VIEW_MAP_CACHE.move_to_end(key)
            return existing
        _VIEW_MAP_CACHE[key] = maps
        _VIEW_MAP_CACHE.move_to_end(key)
        while len(_VIEW_MAP_CACHE) > _VIEW_MAP_CACHE_SIZE:
            _VIEW_MAP_CACHE.popitem(last=False)
    return maps


def render_perspective(
    equirectangular: np.ndarray,
    orientation: OrientationState,
    width: int,
    height: int,
    horizontal_fov_deg: float,
    quality: str = "balanced",
) -> np.ndarray:
    panorama_height, panorama_width = equirectangular.shape[:2]
    maps = _equirectangular_view_maps(
        panorama_width,
        panorama_height,
        orientation,
        "perspective",
        int(width),
        int(height),
        horizontal_fov_deg,
        quality,
    )
    return _sample_equirectangular(
        equirectangular,
        None,
        quality,
        maps=maps,
    )


def render_stereographic(
    equirectangular: np.ndarray,
    orientation: OrientationState,
    width: int,
    height: int,
    horizontal_fov_deg: float,
    quality: str = "balanced",
) -> np.ndarray:
    panorama_height, panorama_width = equirectangular.shape[:2]
    maps = _equirectangular_view_maps(
        panorama_width,
        panorama_height,
        orientation,
        "stereographic",
        int(width),
        int(height),
        horizontal_fov_deg,
        "fast",
    )
    # The proven Mapper pipeline uses INTER_NEAREST for the final view remap.
    return _sample_equirectangular(
        equirectangular,
        None,
        "fast",
        maps=maps,
    )


def _format_pixels(image: np.ndarray, pixel_format: str) -> np.ndarray:
    if pixel_format == "bgr24":
        return image
    if pixel_format == "bgra":
        alpha = np.full(image.shape[:2] + (1,), 255, dtype=np.uint8)
        return np.concatenate((image, alpha), axis=2)
    raise ValueError(f"unsupported pixel format {pixel_format!r}")


def render_equirectangular(
    equirectangular: np.ndarray,
    orientation: OrientationState,
    view: ViewConfig,
) -> np.ndarray:
    """Render one view from an already stitched BGR panorama."""
    if view.projection == "equirectangular":
        if equirectangular.shape[:2] == (view.height, view.width):
            output = equirectangular.copy()
        else:
            output = cv2.resize(
                equirectangular,
                (view.width, view.height),
                interpolation=_interpolation_for_quality(view.quality),
            )
    elif view.projection == "perspective":
        output = render_perspective(
            equirectangular,
            orientation,
            view.width,
            view.height,
            view.horizontal_fov_deg,
            quality=view.quality,
        )
    elif view.projection == "stereographic":
        output = render_stereographic(
            equirectangular,
            orientation,
            view.width,
            view.height,
            view.horizontal_fov_deg,
            quality=view.quality,
        )
    else:  # ViewConfig normally prevents this branch.
        raise ValueError(f"unsupported projection {view.projection!r}")
    return _format_pixels(output, view.pixel_format)


def render_frames(
    frame0: np.ndarray,
    frame1: np.ndarray,
    calibration: CalibrationProfile,
    orientation: OrientationState,
    view: ViewConfig,
    *,
    return_equirectangular: bool = False,
    equirectangular_width: Optional[int] = None,
    equirectangular_height: Optional[int] = None,
) -> RenderResult:
    """Run both render stages for one synchronized frame pair."""
    if equirectangular_width is None:
        equirectangular_width = (
            view.width
            if view.projection == "equirectangular"
            else max(1024, view.width * 2)
        )
    if equirectangular_height is None:
        equirectangular_height = (
            view.height
            if view.projection == "equirectangular"
            else max(1, equirectangular_width // 2)
        )
    panorama = stitch_equirectangular(
        frame0,
        frame1,
        calibration,
        equirectangular_width,
        equirectangular_height,
        quality=view.quality,
    )
    image = render_equirectangular(panorama, orientation, view)
    return RenderResult(
        image=image,
        equirectangular=panorama if return_equirectangular else None,
    )


class RenderSession:
    """Cache Stage 1 while orientation and projection change."""

    def __init__(
        self,
        calibration: CalibrationProfile,
        *,
        default_equirectangular_width: int = 2048,
        default_equirectangular_height: int = 1024,
    ) -> None:
        validate_calibration(calibration)
        self.calibration = calibration
        self.default_equirectangular_width = int(default_equirectangular_width)
        self.default_equirectangular_height = int(default_equirectangular_height)
        if (
            self.default_equirectangular_width <= 0
            or self.default_equirectangular_height <= 0
        ):
            raise ValueError("default equirectangular size must be positive")
        self._frame0: Optional[np.ndarray] = None
        self._frame1: Optional[np.ndarray] = None
        self._equirectangular: Optional[np.ndarray] = None
        self._equirectangular_stages: Optional[EquirectangularStages] = None
        self._cache_key: Optional[Tuple[int, int, str]] = None
        self.stitch_count = 0

    @property
    def has_frames(self) -> bool:
        return self._frame0 is not None and self._frame1 is not None

    @property
    def has_equirectangular(self) -> bool:
        return self._equirectangular is not None

    def set_frames(self, frame0: np.ndarray, frame1: np.ndarray) -> None:
        self._frame0 = _require_bgr_image(frame0, "frame0")
        self._frame1 = _require_bgr_image(frame1, "frame1")
        self.invalidate()

    def invalidate(self) -> None:
        self._equirectangular = None
        self._equirectangular_stages = None
        self._cache_key = None

    def build_equirectangular(
        self,
        width: Optional[int] = None,
        height: Optional[int] = None,
        quality: str = "balanced",
    ) -> np.ndarray:
        if not self.has_frames:
            raise RuntimeError("set_frames() must be called before rendering")
        width = int(width or self.default_equirectangular_width)
        height = int(height or self.default_equirectangular_height)
        key = (width, height, str(quality).lower())
        if self._equirectangular is None or self._cache_key != key:
            self._equirectangular_stages = stitch_equirectangular_stages(
                self._frame0,
                self._frame1,
                self.calibration,
                width,
                height,
                quality=quality,
            )
            self._equirectangular = self._equirectangular_stages.equi_blended
            self._cache_key = key
            self.stitch_count += 1
        return self._equirectangular

    def get_equirectangular_stages(
        self,
        width: Optional[int] = None,
        height: Optional[int] = None,
        quality: str = "balanced",
    ) -> EquirectangularStages:
        """Return camera 0, camera 1, and blended Stage 1 images."""
        self.build_equirectangular(width, height, quality)
        if self._equirectangular_stages is None:
            raise RuntimeError("equirectangular stages were not built")
        return self._equirectangular_stages

    def get_equirectangular(
        self,
        width: Optional[int] = None,
        height: Optional[int] = None,
        quality: str = "balanced",
    ) -> np.ndarray:
        return self.build_equirectangular(width, height, quality)

    def render(
        self,
        orientation: OrientationState,
        view: ViewConfig,
        *,
        return_equirectangular: bool = False,
        equirectangular_width: Optional[int] = None,
        equirectangular_height: Optional[int] = None,
    ) -> RenderResult:
        if equirectangular_width is None:
            equirectangular_width = (
                view.width
                if view.projection == "equirectangular"
                else self.default_equirectangular_width
            )
        if equirectangular_height is None:
            equirectangular_height = (
                view.height
                if view.projection == "equirectangular"
                else self.default_equirectangular_height
            )
        panorama = self.build_equirectangular(
            equirectangular_width, equirectangular_height, view.quality
        )
        image = render_equirectangular(panorama, orientation, view)
        return RenderResult(
            image=image,
            equirectangular=panorama if return_equirectangular else None,
        )
