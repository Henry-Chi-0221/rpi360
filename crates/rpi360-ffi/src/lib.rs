//! C ABI JSON boundary. Caller owns inputs; free every returned pointer with rpi360_free.
use std::ffi::{c_char, CStr, CString};
fn result(value: Result<String, String>) -> *mut c_char {
    CString::new(match value {
        Ok(v) => v,
        Err(e) => serde_json::json!({"error":e}).to_string(),
    })
    .unwrap()
    .into_raw()
}
/// # Safety
/// `input` must be a valid nul-terminated UTF-8 string for the duration of the call.
#[no_mangle]
pub unsafe extern "C" fn rpi360_calibration(input: *const c_char) -> *mut c_char {
    if input.is_null() {
        return result(Err("null input".into()));
    }
    let s = match CStr::from_ptr(input).to_str() {
        Ok(s) => s,
        Err(e) => return result(Err(e.to_string())),
    };
    result(
        rpi360_core::CalibrationProfile::parse(s)
            .and_then(|p| serde_json::to_string(&p).map_err(|e| e.to_string())),
    )
}
/// # Safety
/// `input` must be a valid nul-terminated UTF-8 JSON project.
#[no_mangle]
pub unsafe extern "C" fn rpi360_evaluate(input: *const c_char, time_us: i64) -> *mut c_char {
    if input.is_null() {
        return result(Err("null input".into()));
    }
    let s = match CStr::from_ptr(input).to_str() {
        Ok(s) => s,
        Err(e) => return result(Err(e.to_string())),
    };
    result((|| {
        let p: rpi360_core::EditProject = serde_json::from_str(s).map_err(|e| e.to_string())?;
        serde_json::to_string(&p.evaluate(time_us)?).map_err(|e| e.to_string())
    })())
}
/// # Safety
/// Pass a non-null pointer returned by this library exactly once, or null.
#[no_mangle]
pub unsafe extern "C" fn rpi360_free(value: *mut c_char) {
    if !value.is_null() {
        drop(CString::from_raw(value));
    }
}
/// # Safety
/// `input` must point to a valid nul-terminated UTF-8 JSON request.
#[no_mangle]
pub unsafe extern "C" fn rpi360_map_rays(input: *const c_char) -> *mut c_char {
    if input.is_null() {
        return result(Err("null input".into()));
    }
    result(
        CStr::from_ptr(input)
            .to_str()
            .map_err(|e| e.to_string())
            .and_then(rpi360_core::map_rays_json),
    )
}

#[cfg(feature = "gpu")]
mod gpu;
