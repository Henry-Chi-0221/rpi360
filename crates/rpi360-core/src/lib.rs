//! Platform-independent geometry, calibration conversion and editing timeline.
//! Rig: +X right, +Y up, -Z forward. Lens: +X right, +Y down, +Z optical axis.
use glam::{Mat3, Quat, Vec3};
use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};
use std::f32::consts::PI;

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct Lens {
    pub size: [u32; 2],
    /// fx, fy, cx, cy at calibration resolution.
    pub intrinsics: [f32; 4],
    #[serde(default)]
    pub skew: f32,
    pub distortion: [f32; 4],
    pub fov_deg: f32,
    /// Row-major rotation: column ray_rig = camera_to_rig * column ray_camera.
    pub camera_to_rig: [[f32; 3]; 3],
    #[serde(default = "unit_gain")]
    pub gain: [f32; 3],
}
fn unit_gain() -> [f32; 3] {
    [1.; 3]
}
fn matrix(rows: [[f32; 3]; 3]) -> Mat3 {
    Mat3::from_cols_array_2d(&rows).transpose()
}
fn rows(m: Mat3) -> [[f32; 3]; 3] {
    m.transpose().to_cols_array_2d()
}
#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct CalibrationProfile {
    pub schema_version: u32,
    pub id: String,
    pub coordinate_system: String,
    pub cameras: [Lens; 2],
}
impl CalibrationProfile {
    pub fn validate(&self) -> Result<(), String> {
        if self.schema_version != 2 || self.coordinate_system != "right-up-back" {
            return Err("unsupported calibration coordinate system/version".into());
        }
        for c in &self.cameras {
            let m = matrix(c.camera_to_rig);
            if c.size.contains(&0)
                || !c
                    .intrinsics
                    .iter()
                    .chain(c.distortion.iter())
                    .chain(c.gain.iter())
                    .all(|v| v.is_finite())
                || !c.skew.is_finite()
                || c.intrinsics[0] <= 0.
                || c.intrinsics[1] <= 0.
                || !(0. ..=360.).contains(&c.fov_deg)
                || c.fov_deg == 0.
                || !m.is_finite()
                || (m.determinant() - 1.).abs() > 0.001
                || (m.transpose() * m - Mat3::IDENTITY)
                    .to_cols_array()
                    .iter()
                    .any(|v| v.abs() > 0.001)
            {
                return Err("invalid lens calibration or rotation".into());
            }
        }
        Ok(())
    }
    pub fn parse(json: &str) -> Result<Self, String> {
        let v: serde_json::Value = serde_json::from_str(json).map_err(|e| e.to_string())?;
        if v.get("schema_version").and_then(|v| v.as_u64()) == Some(2) {
            let p: Self = serde_json::from_value(v).map_err(|e| e.to_string())?;
            p.validate()?;
            return Ok(p);
        }
        let legacy = v.get("calibration").unwrap_or(&v);
        let r: [[f32; 3]; 3] =
            serde_json::from_value(legacy["R_cam1_to_cam0"].clone()).map_err(|e| e.to_string())?;
        let s = Mat3::from_diagonal(Vec3::new(1., -1., -1.));
        // Exactly preserves old row-vector R * mount, including its hidden mount.
        let mount = Mat3::from_diagonal(Vec3::new(1., -1., -1.));
        let mut cams = Vec::new();
        for i in 0..2 {
            let c = &legacy[format!("camera_{i}")];
            let k: [[f32; 3]; 3] =
                serde_json::from_value(c["K"].clone()).map_err(|e| e.to_string())?;
            let d = serde_json::from_value(c["D"].clone()).map_err(|e| e.to_string())?;
            let get = |name: &str| {
                c[name]
                    .as_u64()
                    .filter(|v| *v > 0 && *v <= u32::MAX as u64)
                    .map(|v| v as u32)
                    .ok_or(format!("missing {name}"))
            };
            cams.push(Lens {
                size: [get("width")?, get("height")?],
                intrinsics: [k[0][0], k[1][1], k[0][2], k[1][2]],
                skew: k[0][1],
                distortion: d,
                fov_deg: c["fisheye_fov_deg"].as_f64().unwrap_or(210.) as f32,
                camera_to_rig: rows(if i == 0 { s } else { s * matrix(r) * mount }),
                gain: unit_gain(),
            });
        }
        let p = Self {
            schema_version: 2,
            id: format!(
                "legacy-{:x}",
                Sha256::digest(serde_json::to_vec(&legacy).map_err(|e| e.to_string())?)
            ),
            coordinate_system: "right-up-back".into(),
            cameras: cams.try_into().unwrap(),
        };
        p.validate()?;
        Ok(p)
    }
}
#[derive(Clone, Copy, Debug, Serialize, Deserialize, PartialEq)]
#[serde(rename_all = "snake_case")]
pub enum Projection {
    Perspective,
    Stereographic,
    Equirectangular,
}
#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct ViewState {
    /// Quaternion [x,y,z,w], normalized at the boundary.
    pub orientation: [f32; 4],
    pub horizontal_fov_deg: f32,
    pub projection: Projection,
    #[serde(default)]
    pub spin_deg: f32,
}
impl Default for ViewState {
    fn default() -> Self {
        Self {
            orientation: [0., 0., 0., 1.],
            horizontal_fov_deg: 90.,
            projection: Projection::Perspective,
            spin_deg: 0.,
        }
    }
}
impl ViewState {
    pub fn rotation(&self) -> Result<Quat, String> {
        let q = Quat::from_array(self.orientation);
        if !q.is_finite() || q.length_squared() < 1e-12 || !self.spin_deg.is_finite() {
            return Err("invalid orientation".into());
        }
        Ok(q.normalize() * Quat::from_axis_angle(Vec3::NEG_Z, self.spin_deg.to_radians()))
    }
    pub fn validate(&self) -> Result<(), String> {
        self.rotation()?;
        let max = if self.projection == Projection::Perspective {
            179.
        } else {
            359.
        };
        if !self.horizontal_fov_deg.is_finite()
            || self.horizontal_fov_deg <= 0.
            || self.horizontal_fov_deg > max
        {
            return Err("invalid horizontal FOV".into());
        }
        Ok(())
    }
}
/// UI yaw is positive towards image-right; pitch positive looks upwards.
pub fn from_euler(yaw: f32, pitch: f32, roll: f32) -> [f32; 4] {
    (Quat::from_rotation_y(-yaw.to_radians())
        * Quat::from_rotation_x(pitch.to_radians())
        * Quat::from_rotation_z(-roll.to_radians()))
    .normalize()
    .to_array()
}
pub fn to_euler(q: [f32; 4]) -> [f32; 3] {
    let (y, x, z) = Quat::from_array(q)
        .normalize()
        .to_euler(glam::EulerRot::YXZ);
    [-y.to_degrees(), x.to_degrees(), -z.to_degrees()]
}
pub fn view_ray(view: &ViewState, uv: [f32; 2], aspect: f32) -> Result<Vec3, String> {
    view.validate()?;
    if !aspect.is_finite() || aspect <= 0. {
        return Err("invalid aspect".into());
    }
    let x = 2. * uv[0] - 1.;
    let y = 1. - 2. * uv[1];
    let f = view.horizontal_fov_deg.to_radians();
    let ray = match view.projection {
        Projection::Perspective => {
            Vec3::new(x * (f / 2.).tan(), y * (f / 2.).tan() / aspect, -1.).normalize()
        }
        Projection::Stereographic => {
            let x = x * 2. * (f / 4.).tan();
            let y = y * 2. * (f / 4.).tan() / aspect;
            let r = x * x + y * y;
            Vec3::new(4. * x, 4. * y, r - 4.) / (r + 4.)
        }
        Projection::Equirectangular => {
            let lon = x * PI;
            let lat = y * PI / 2.;
            Vec3::new(lon.sin() * lat.cos(), lat.sin(), -lon.cos() * lat.cos())
        }
    };
    Ok(view.rotation()? * ray)
}
/// Normalized UV and deterministic feather confidence; None outside calibrated lens.
pub fn project_ray(lens: &Lens, ray: Vec3) -> Option<([f32; 2], f32)> {
    let r = matrix(lens.camera_to_rig).transpose() * ray.normalize();
    let radial = r.truncate().length();
    let theta = radial.atan2(r.z);
    if theta > lens.fov_deg.to_radians() / 2. || (radial < 1e-7 && r.z < 0.) {
        return None;
    }
    let t = theta * theta;
    let d = lens.distortion;
    let td = theta * (1. + t * (d[0] + t * (d[1] + t * (d[2] + t * d[3]))));
    let scale = if radial > 1e-7 { td / radial } else { 1. };
    let [fx, fy, cx, cy] = lens.intrinsics;
    let u = (fx * r.x * scale + lens.skew * r.y * scale + cx) / lens.size[0] as f32;
    let v = (fy * r.y * scale + cy) / lens.size[1] as f32;
    if !(0. ..=1.).contains(&u) || !(0. ..=1.).contains(&v) {
        return None;
    }
    let angular = ((lens.fov_deg.to_radians() / 2. - theta) / 0.25).clamp(0., 1.);
    let edge = (u.min(1. - u).min(v.min(1. - v)) / 0.04).clamp(0., 1.);
    Some(([u, v], (edge * angular).max(0.001)))
}
#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct Keyframe {
    pub time_us: i64,
    pub view: ViewState,
    #[serde(default)]
    pub linear: bool,
}
#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct TimePoint {
    pub output_us: i64,
    pub source_us: i64,
}
#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct EditProject {
    pub schema_version: u32,
    pub id: String,
    pub source_id: String,
    pub duration_us: i64,
    pub keyframes: Vec<Keyframe>,
    pub time_remap: Vec<TimePoint>,
    /// Explicit user correction; unknown legacy alignment remains null until reviewed.
    pub alignment_us: Option<i64>,
}
#[derive(Serialize, Deserialize)]
pub struct EvaluatedView {
    pub view: ViewState,
    pub source_time_us: i64,
}
impl EditProject {
    pub fn validate(&self) -> Result<(), String> {
        if self.schema_version != 2
            || self.duration_us <= 0
            || self.keyframes.is_empty()
            || self.time_remap.is_empty()
        {
            return Err("invalid edit project".into());
        }
        if self.keyframes[0].time_us != 0 || self.time_remap[0].output_us != 0 {
            return Err("tracks must begin at output time zero".into());
        }
        for k in &self.keyframes {
            k.view.validate()?;
            if k.time_us < 0 || k.time_us > self.duration_us {
                return Err("keyframe outside timeline".into());
            }
        }
        if self
            .keyframes
            .windows(2)
            .any(|p| p[0].time_us >= p[1].time_us)
            || self
                .time_remap
                .windows(2)
                .any(|p| p[0].output_us >= p[1].output_us || p[0].source_us > p[1].source_us)
            || self
                .time_remap
                .iter()
                .any(|p| p.source_us < 0 || p.output_us < 0 || p.output_us > self.duration_us)
        {
            return Err("non-monotonic timeline".into());
        }
        Ok(())
    }
    pub fn evaluate(&self, time_us: i64) -> Result<EvaluatedView, String> {
        self.validate()?;
        let t = time_us.clamp(0, self.duration_us);
        let index = self
            .keyframes
            .partition_point(|k| k.time_us <= t)
            .saturating_sub(1);
        let a = &self.keyframes[index];
        let b = self.keyframes.get(index + 1).unwrap_or(a);
        let mut f = if b.time_us == a.time_us {
            0.
        } else {
            (t - a.time_us) as f32 / (b.time_us - a.time_us) as f32
        };
        if !a.linear {
            f = f * f * (3. - 2. * f);
        }
        // Interpolate base quaternion separately from unwrapped spin (a full roll survives).
        let qa = Quat::from_array(a.view.orientation).normalize();
        let qb = Quat::from_array(b.view.orientation).normalize();
        let view = ViewState {
            orientation: qa.slerp(qb, f).normalize().to_array(),
            horizontal_fov_deg: a.view.horizontal_fov_deg
                + (b.view.horizontal_fov_deg - a.view.horizontal_fov_deg) * f,
            projection: a.view.projection,
            spin_deg: a.view.spin_deg + (b.view.spin_deg - a.view.spin_deg) * f,
        };
        let i = self
            .time_remap
            .partition_point(|k| k.output_us <= t)
            .saturating_sub(1);
        let a = &self.time_remap[i];
        let b = self.time_remap.get(i + 1).unwrap_or(a);
        let source_time_us = if a.output_us == b.output_us {
            a.source_us
        } else {
            a.source_us
                + ((t - a.output_us) as f64 * (b.source_us - a.source_us) as f64
                    / (b.output_us - a.output_us) as f64)
                    .round() as i64
        };
        Ok(EvaluatedView {
            view,
            source_time_us,
        })
    }
}
pub fn convert_calibration(json: &str) -> Result<String, String> {
    CalibrationProfile::parse(json)
        .and_then(|v| serde_json::to_string(&v).map_err(|e| e.to_string()))
}
pub fn evaluate_project(json: &str, time_us: f64) -> Result<String, String> {
    let result = (|| {
        let p: EditProject = serde_json::from_str(json).map_err(|e| e.to_string())?;
        serde_json::to_string(&p.evaluate(time_us.round() as i64)?).map_err(|e| e.to_string())
    })();
    result
}
pub fn orientation_from_euler(yaw: f32, pitch: f32, roll: f32) -> Vec<f32> {
    from_euler(yaw, pitch, roll).to_vec()
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn axes_and_aspect() {
        let v = ViewState::default();
        assert!((view_ray(&v, [0.5, 0.5], 2.).unwrap() - Vec3::NEG_Z).length() < 1e-6);
        let right = view_ray(&v, [1., 0.5], 2.).unwrap();
        assert!((right.x + right.z).abs() < 1e-6);
        let top = view_ray(&v, [0.5, 0.], 2.).unwrap();
        assert!((top.y / -top.z - 0.5).abs() < 1e-6);
    }
    #[test]
    fn full_roll_survives() {
        let mut b = ViewState::default();
        b.spin_deg = 360.;
        let p = EditProject {
            schema_version: 2,
            id: "x".into(),
            source_id: "x".into(),
            duration_us: 100,
            keyframes: vec![
                Keyframe {
                    time_us: 0,
                    view: ViewState::default(),
                    linear: true,
                },
                Keyframe {
                    time_us: 100,
                    view: b,
                    linear: true,
                },
            ],
            time_remap: vec![
                TimePoint {
                    output_us: 0,
                    source_us: 123,
                },
                TimePoint {
                    output_us: 100,
                    source_us: 323,
                },
            ],
            alignment_us: None,
        };
        let e = p.evaluate(50).unwrap();
        assert_eq!(e.view.spin_deg, 180.);
        assert_eq!(e.source_time_us, 223);
        assert!((e.view.rotation().unwrap() * Vec3::X + Vec3::X).length() < 1e-5);
    }
    #[test]
    fn legacy_mount_is_explicit() {
        let p = CalibrationProfile::parse(include_str!(
            "../../../calibration/rpi5-dual-imx219-example.json"
        ))
        .unwrap();
        assert!(project_ray(&p.cameras[0], Vec3::NEG_Z).is_some());
        assert!(project_ray(&p.cameras[1], Vec3::Z).is_some());
        assert!(project_ray(&p.cameras[1], Vec3::NEG_Z).is_none());
    }
}

/// Geometry diagnostic boundary used by cross-platform golden tests and SDKs.
pub fn map_rays_json(input: &str) -> Result<String, String> {
    let value: serde_json::Value = serde_json::from_str(input).map_err(|e| e.to_string())?;
    let calibration = CalibrationProfile::parse(&value["calibration"].to_string())?;
    let rays: Vec<[f32; 3]> =
        serde_json::from_value(value["rays"].clone()).map_err(|e| e.to_string())?;
    if rays.len() > 100_000 {
        return Err("too many rays".into());
    }
    let mut result = Vec::new();
    for r in rays {
        let ray = Vec3::from_array(r);
        if !ray.is_finite() || ray.length_squared() < 1e-12 {
            return Err("invalid ray".into());
        }
        result.push(
            calibration
                .cameras
                .iter()
                .map(|c| project_ray(c, ray))
                .collect::<Vec<_>>(),
        );
    }
    serde_json::to_string(&result).map_err(|e| e.to_string())
}
