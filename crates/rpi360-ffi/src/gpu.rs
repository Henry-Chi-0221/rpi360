//! Retained GPU context for native adapters. RGBA transfer is a reference path;
//! callers own their buffers and serialize calls to each context.
use rpi360_render::Gpu;
use std::ffi::{c_char, c_void, CStr};
fn response(value: Result<(), String>) -> *mut c_char {
    match value {
        Ok(()) => std::ptr::null_mut(),
        Err(e) => super::result(Err(e)),
    }
}
/// # Safety
/// `out` must be writable. A successful context must be freed once with renderer_free.
#[no_mangle]
pub unsafe extern "C" fn rpi360_renderer_create(out: *mut *mut c_void) -> *mut c_char {
    if out.is_null() {
        return response(Err("null output context".into()));
    }
    *out = std::ptr::null_mut();
    response(pollster::block_on(Gpu::headless()).map(|gpu| {
        *out = Box::into_raw(Box::new(gpu)).cast();
    }))
}
/// # Safety
/// Context must be live; source must reference length readable bytes. Calls are serialized.
#[no_mangle]
pub unsafe extern "C" fn rpi360_renderer_upload(
    context: *mut c_void,
    source: *const u8,
    length: usize,
    width: u32,
    height: u32,
) -> *mut c_char {
    if context.is_null() || source.is_null() || length > isize::MAX as usize {
        return response(Err("invalid context or source buffer".into()));
    }
    response((&mut *context.cast::<Gpu>()).upload(
        std::slice::from_raw_parts(source, length),
        width,
        height,
    ))
}
/// # Safety
/// JSON arguments are valid nul-terminated strings; destination references length writable
/// bytes and must not overlap context. Context is live and calls are serialized.
#[no_mangle]
pub unsafe extern "C" fn rpi360_renderer_draw(
    context: *mut c_void,
    calibration: *const c_char,
    view: *const c_char,
    destination: *mut u8,
    length: usize,
    width: u32,
    height: u32,
) -> *mut c_char {
    response((|| {
        if context.is_null() || calibration.is_null() || view.is_null() || destination.is_null() {
            return Err("null render argument".into());
        }
        if width == 0 || height == 0 || width > 8192 || height > 8192 {
            return Err("output dimensions outside 1..8192".into());
        }
        let expected = u64::from(width) * u64::from(height) * 4;
        if expected > length as u64 || expected > isize::MAX as u64 {
            return Err("output buffer too small".into());
        }
        let cal = rpi360_core::CalibrationProfile::parse(
            CStr::from_ptr(calibration)
                .to_str()
                .map_err(|e| e.to_string())?,
        )?;
        let state: rpi360_core::ViewState =
            serde_json::from_str(CStr::from_ptr(view).to_str().map_err(|e| e.to_string())?)
                .map_err(|e| e.to_string())?;
        let result = (&*context.cast::<Gpu>()).render(&cal, &state, width, height, true)?;
        std::ptr::copy_nonoverlapping(result.as_ptr(), destination, result.len());
        Ok(())
    })())
}
/// # Safety
/// Context is either null or a live context returned by create, freed exactly once.
#[no_mangle]
pub unsafe extern "C" fn rpi360_renderer_free(context: *mut c_void) {
    if !context.is_null() {
        drop(Box::from_raw(context.cast::<Gpu>()));
    }
}
