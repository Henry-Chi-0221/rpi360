//! Streaming native export renderer. Pixel I/O is RGBA8; only one pair is resident.
#[cfg(not(target_arch = "wasm32"))]
fn main() -> Result<(), Box<dyn std::error::Error>> {
    use std::io::{Read, Write};
    let a: Vec<String> = std::env::args().collect();
    if a.len() != 9 || a[1] != "--pipe" {
        return Err("usage: rpi360-render --pipe calibration.json project.json source_width source_height output_width output_height antialias".into());
    }
    let cal = rpi360_core::CalibrationProfile::parse(&std::fs::read_to_string(&a[2])?)?;
    let project: rpi360_core::EditProject = serde_json::from_str(&std::fs::read_to_string(&a[3])?)?;
    project.validate()?;
    let w: u32 = a[4].parse()?;
    let h: u32 = a[5].parse()?;
    let ow: u32 = a[6].parse()?;
    let oh: u32 = a[7].parse()?;
    let aa: bool = a[8].parse()?;
    if w == 0 || h == 0 || w > 16384 || h > 8192 {
        return Err("invalid packed source dimensions".into());
    }
    let mut gpu = pollster::block_on(rpi360_render::Gpu::headless())?;
    let mut pixels = vec![0; w as usize * h as usize * 4];
    let mut stdin = std::io::stdin().lock();
    let mut stdout = std::io::stdout().lock();
    loop {
        let mut time = [0; 8];
        match stdin.read_exact(&mut time) {
            Ok(()) => {}
            Err(e) if e.kind() == std::io::ErrorKind::UnexpectedEof => break,
            Err(e) => return Err(e.into()),
        };
        stdin.read_exact(&mut pixels)?;
        let view = project.evaluate(i64::from_le_bytes(time))?.view;
        gpu.upload(&pixels, w, h)?;
        let result = gpu.render(&cal, &view, ow, oh, aa)?;
        stdout.write_all(&result)?;
        stdout.flush()?;
    }
    Ok(())
}
#[cfg(target_arch = "wasm32")]
fn main() {}
