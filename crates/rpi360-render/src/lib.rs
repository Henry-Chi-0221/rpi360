//! One shader and geometry contract for native Metal, browser WebGPU and WebGL2.
use rpi360_core::{CalibrationProfile, Projection, ViewState};
use wasm_bindgen::prelude::*;
use wgpu::util::DeviceExt;
#[derive(Clone, Copy, bytemuck::Pod, bytemuck::Zeroable)]
#[repr(C)]
struct Uniforms {
    v: [[f32; 4]; 16],
}
fn uniforms(
    cal: &CalibrationProfile,
    view: &ViewState,
    width: u32,
    height: u32,
    aa: bool,
) -> Result<Uniforms, String> {
    cal.validate()?;
    view.validate()?;
    let mut v = [[0.; 4]; 16];
    v[0] = view.rotation()?.to_array();
    v[1] = [
        width as f32,
        height as f32,
        view.horizontal_fov_deg.to_radians(),
        match view.projection {
            Projection::Perspective => 0.,
            Projection::Stereographic => 1.,
            Projection::Equirectangular => 2.,
        },
    ];
    for (i, c) in cal.cameras.iter().enumerate() {
        let [fx, fy, cx, cy] = c.intrinsics;
        v[2 + i] = [
            fx / c.size[0] as f32,
            fy / c.size[1] as f32,
            cx / c.size[0] as f32,
            cy / c.size[1] as f32,
        ];
        v[4 + i] = c.distortion;
        for row in 0..3 {
            v[6 + 3 * i + row] = [
                c.camera_to_rig[0][row],
                c.camera_to_rig[1][row],
                c.camera_to_rig[2][row],
                0.,
            ];
        }
        v[12 + i] = [c.fov_deg.to_radians() / 2., c.gain[0], c.gain[1], c.gain[2]];
        v[14 + i][0] = c.skew / c.size[0] as f32;
    }
    v[14][1] = if aa { 1. } else { 0. };
    Ok(Uniforms { v })
}
pub struct Gpu {
    device: wgpu::Device,
    queue: wgpu::Queue,
    pipeline: wgpu::RenderPipeline,
    layout: wgpu::BindGroupLayout,
    uniform: wgpu::Buffer,
    sampler: wgpu::Sampler,
    source: Option<wgpu::Texture>,
    binding: Option<wgpu::BindGroup>,
    source_size: [u32; 2],
}
impl Gpu {
    async fn new(
        instance: &wgpu::Instance,
        surface: Option<&wgpu::Surface<'_>>,
    ) -> Result<(Self, wgpu::TextureFormat, wgpu::Adapter), String> {
        let adapter = instance
            .request_adapter(&wgpu::RequestAdapterOptions {
                power_preference: wgpu::PowerPreference::HighPerformance,
                compatible_surface: surface,
                force_fallback_adapter: false,
            })
            .await
            .map_err(|e| e.to_string())?;
        let format = surface
            .map(|s| {
                s.get_capabilities(&adapter)
                    .formats
                    .into_iter()
                    .find(|f| !f.is_srgb())
                    .unwrap_or(wgpu::TextureFormat::Bgra8Unorm)
            })
            .unwrap_or(wgpu::TextureFormat::Rgba8Unorm);
        let (device, queue) = adapter
            .request_device(&wgpu::DeviceDescriptor {
                label: Some("RPI360"),
                required_features: wgpu::Features::empty(),
                required_limits: wgpu::Limits::downlevel_webgl2_defaults()
                    .using_resolution(adapter.limits()),
                memory_hints: wgpu::MemoryHints::MemoryUsage,
                trace: wgpu::Trace::Off,
            })
            .await
            .map_err(|e| e.to_string())?;
        let uniform = device.create_buffer_init(&wgpu::util::BufferInitDescriptor {
            label: Some("view"),
            contents: bytemuck::bytes_of(&Uniforms { v: [[0.; 4]; 16] }),
            usage: wgpu::BufferUsages::UNIFORM | wgpu::BufferUsages::COPY_DST,
        });
        let layout = device.create_bind_group_layout(&wgpu::BindGroupLayoutDescriptor {
            label: None,
            entries: &[
                wgpu::BindGroupLayoutEntry {
                    binding: 0,
                    visibility: wgpu::ShaderStages::FRAGMENT,
                    ty: wgpu::BindingType::Buffer {
                        ty: wgpu::BufferBindingType::Uniform,
                        has_dynamic_offset: false,
                        min_binding_size: None,
                    },
                    count: None,
                },
                wgpu::BindGroupLayoutEntry {
                    binding: 1,
                    visibility: wgpu::ShaderStages::FRAGMENT,
                    ty: wgpu::BindingType::Texture {
                        sample_type: wgpu::TextureSampleType::Float { filterable: true },
                        view_dimension: wgpu::TextureViewDimension::D2,
                        multisampled: false,
                    },
                    count: None,
                },
                wgpu::BindGroupLayoutEntry {
                    binding: 2,
                    visibility: wgpu::ShaderStages::FRAGMENT,
                    ty: wgpu::BindingType::Sampler(wgpu::SamplerBindingType::Filtering),
                    count: None,
                },
            ],
        });
        let shader = device.create_shader_module(wgpu::ShaderModuleDescriptor {
            label: Some("fisheye"),
            source: wgpu::ShaderSource::Wgsl(include_str!("../shaders/fisheye.wgsl").into()),
        });
        let pipeline_layout = device.create_pipeline_layout(&wgpu::PipelineLayoutDescriptor {
            label: None,
            bind_group_layouts: &[&layout],
            push_constant_ranges: &[],
        });
        let pipeline = device.create_render_pipeline(&wgpu::RenderPipelineDescriptor {
            label: Some("direct viewport"),
            layout: Some(&pipeline_layout),
            vertex: wgpu::VertexState {
                module: &shader,
                entry_point: Some("vs"),
                compilation_options: Default::default(),
                buffers: &[],
            },
            fragment: Some(wgpu::FragmentState {
                module: &shader,
                entry_point: Some("fs"),
                compilation_options: Default::default(),
                targets: &[Some(wgpu::ColorTargetState {
                    format,
                    blend: None,
                    write_mask: wgpu::ColorWrites::ALL,
                })],
            }),
            primitive: Default::default(),
            depth_stencil: None,
            multisample: Default::default(),
            multiview: None,
            cache: None,
        });
        let sampler = device.create_sampler(&wgpu::SamplerDescriptor {
            mag_filter: wgpu::FilterMode::Linear,
            min_filter: wgpu::FilterMode::Linear,
            ..Default::default()
        });
        Ok((
            Self {
                device,
                queue,
                pipeline,
                layout,
                uniform,
                sampler,
                source: None,
                binding: None,
                source_size: [0, 0],
            },
            format,
            adapter,
        ))
    }
    pub fn upload(&mut self, rgba: &[u8], width: u32, height: u32) -> Result<(), String> {
        if width == 0
            || height == 0
            || width % 2 != 0
            || width > self.device.limits().max_texture_dimension_2d
            || height > self.device.limits().max_texture_dimension_2d
            || rgba.len() != width as usize * height as usize * 4
        {
            return Err("invalid packed RGBA image dimensions".into());
        }
        if self.source_size != [width, height] {
            let texture = self.device.create_texture(&wgpu::TextureDescriptor {
                label: Some("paired fisheyes"),
                size: wgpu::Extent3d {
                    width,
                    height,
                    depth_or_array_layers: 1,
                },
                mip_level_count: 1,
                sample_count: 1,
                dimension: wgpu::TextureDimension::D2,
                format: wgpu::TextureFormat::Rgba8Unorm,
                usage: wgpu::TextureUsages::TEXTURE_BINDING | wgpu::TextureUsages::COPY_DST,
                view_formats: &[],
            });
            let view = texture.create_view(&Default::default());
            self.binding = Some(self.device.create_bind_group(&wgpu::BindGroupDescriptor {
                label: None,
                layout: &self.layout,
                entries: &[
                    wgpu::BindGroupEntry {
                        binding: 0,
                        resource: self.uniform.as_entire_binding(),
                    },
                    wgpu::BindGroupEntry {
                        binding: 1,
                        resource: wgpu::BindingResource::TextureView(&view),
                    },
                    wgpu::BindGroupEntry {
                        binding: 2,
                        resource: wgpu::BindingResource::Sampler(&self.sampler),
                    },
                ],
            }));
            self.source = Some(texture);
            self.source_size = [width, height];
        }
        self.queue.write_texture(
            self.source.as_ref().unwrap().as_image_copy(),
            rgba,
            wgpu::TexelCopyBufferLayout {
                offset: 0,
                bytes_per_row: Some(width * 4),
                rows_per_image: Some(height),
            },
            wgpu::Extent3d {
                width,
                height,
                depth_or_array_layers: 1,
            },
        );
        Ok(())
    }
    fn encode(
        &self,
        encoder: &mut wgpu::CommandEncoder,
        target: &wgpu::TextureView,
        cal: &CalibrationProfile,
        view: &ViewState,
        width: u32,
        height: u32,
        aa: bool,
    ) -> Result<(), String> {
        let binding = self.binding.as_ref().ok_or("no source pair uploaded")?;
        self.queue.write_buffer(
            &self.uniform,
            0,
            bytemuck::bytes_of(&uniforms(cal, view, width, height, aa)?),
        );
        let mut pass = encoder.begin_render_pass(&wgpu::RenderPassDescriptor {
            label: None,
            color_attachments: &[Some(wgpu::RenderPassColorAttachment {
                view: target,
                resolve_target: None,
                ops: wgpu::Operations {
                    load: wgpu::LoadOp::Clear(wgpu::Color::BLACK),
                    store: wgpu::StoreOp::Store,
                },
                depth_slice: None,
            })],
            depth_stencil_attachment: None,
            timestamp_writes: None,
            occlusion_query_set: None,
        });
        pass.set_pipeline(&self.pipeline);
        pass.set_bind_group(0, binding, &[]);
        pass.draw(0..3, 0..1);
        Ok(())
    }
    #[cfg(not(target_arch = "wasm32"))]
    pub async fn headless() -> Result<Self, String> {
        let instance = wgpu::Instance::new(&wgpu::InstanceDescriptor::default());
        Ok(Self::new(&instance, None).await?.0)
    }
    #[cfg(not(target_arch = "wasm32"))]
    pub fn render(
        &self,
        cal: &CalibrationProfile,
        view: &ViewState,
        width: u32,
        height: u32,
        aa: bool,
    ) -> Result<Vec<u8>, String> {
        if width == 0 || height == 0 || width > 8192 || height > 8192 {
            return Err("output dimensions outside 1..8192".into());
        }
        let texture = self.device.create_texture(&wgpu::TextureDescriptor {
            label: None,
            size: wgpu::Extent3d {
                width,
                height,
                depth_or_array_layers: 1,
            },
            mip_level_count: 1,
            sample_count: 1,
            dimension: wgpu::TextureDimension::D2,
            format: wgpu::TextureFormat::Rgba8Unorm,
            usage: wgpu::TextureUsages::RENDER_ATTACHMENT | wgpu::TextureUsages::COPY_SRC,
            view_formats: &[],
        });
        let stride = (width * 4).div_ceil(256) * 256;
        let buffer = self.device.create_buffer(&wgpu::BufferDescriptor {
            label: None,
            size: stride as u64 * height as u64,
            usage: wgpu::BufferUsages::COPY_DST | wgpu::BufferUsages::MAP_READ,
            mapped_at_creation: false,
        });
        let mut encoder = self.device.create_command_encoder(&Default::default());
        self.encode(
            &mut encoder,
            &texture.create_view(&Default::default()),
            cal,
            view,
            width,
            height,
            aa,
        )?;
        encoder.copy_texture_to_buffer(
            texture.as_image_copy(),
            wgpu::TexelCopyBufferInfo {
                buffer: &buffer,
                layout: wgpu::TexelCopyBufferLayout {
                    offset: 0,
                    bytes_per_row: Some(stride),
                    rows_per_image: Some(height),
                },
            },
            wgpu::Extent3d {
                width,
                height,
                depth_or_array_layers: 1,
            },
        );
        self.queue.submit([encoder.finish()]);
        let (tx, rx) = std::sync::mpsc::channel();
        buffer.slice(..).map_async(wgpu::MapMode::Read, move |r| {
            let _ = tx.send(r);
        });
        self.device
            .poll(wgpu::PollType::Wait)
            .map_err(|e| e.to_string())?;
        rx.recv()
            .map_err(|e| e.to_string())?
            .map_err(|e| e.to_string())?;
        let mapped = buffer.slice(..).get_mapped_range();
        let mut output = Vec::with_capacity(width as usize * height as usize * 4);
        for row in mapped.chunks(stride as usize) {
            output.extend_from_slice(&row[..width as usize * 4]);
        }
        drop(mapped);
        buffer.unmap();
        Ok(output)
    }
}
#[cfg(target_arch = "wasm32")]
#[wasm_bindgen]
pub struct BrowserRenderer {
    gpu: Gpu,
    surface: wgpu::Surface<'static>,
    config: wgpu::SurfaceConfiguration,
    calibration: CalibrationProfile,
}
#[cfg(target_arch = "wasm32")]
#[wasm_bindgen]
impl BrowserRenderer {
    pub async fn create(
        canvas: web_sys::HtmlCanvasElement,
        calibration: &str,
    ) -> Result<BrowserRenderer, JsValue> {
        console_error_panic_hook::set_once();
        let err = |e: String| JsValue::from_str(&e);
        let calibration = CalibrationProfile::parse(calibration).map_err(err)?;
        let width = canvas.width().max(1);
        let height = canvas.height().max(1);
        let instance = wgpu::Instance::new(&wgpu::InstanceDescriptor {
            backends: wgpu::Backends::BROWSER_WEBGPU | wgpu::Backends::GL,
            ..Default::default()
        });
        let surface = instance
            .create_surface(wgpu::SurfaceTarget::Canvas(canvas))
            .map_err(|e| err(e.to_string()))?;
        let (gpu, format, adapter) = Gpu::new(&instance, Some(&surface)).await.map_err(err)?;
        let mut config = surface
            .get_default_config(&adapter, width, height)
            .ok_or_else(|| err("no surface configuration".into()))?;
        config.format = format;
        surface.configure(&gpu.device, &config);
        Ok(Self {
            gpu,
            surface,
            config,
            calibration,
        })
    }
    pub fn upload(&mut self, rgba: &[u8], width: u32, height: u32) -> Result<(), JsValue> {
        self.gpu
            .upload(rgba, width, height)
            .map_err(|e| JsValue::from_str(&e))
    }
    pub fn set_calibration(&mut self, json: &str) -> Result<(), JsValue> {
        self.calibration = CalibrationProfile::parse(json).map_err(|e| JsValue::from_str(&e))?;
        Ok(())
    }
    pub fn draw(
        &mut self,
        view: &str,
        width: u32,
        height: u32,
        antialias: bool,
    ) -> Result<(), JsValue> {
        let err = |e: String| JsValue::from_str(&e);
        if width == 0 || height == 0 || width > 8192 || height > 8192 {
            return Err(err("invalid output dimensions".into()));
        }
        if self.config.width != width || self.config.height != height {
            self.config.width = width;
            self.config.height = height;
            self.surface.configure(&self.gpu.device, &self.config);
        }
        let view: ViewState = serde_json::from_str(view).map_err(|e| err(e.to_string()))?;
        let frame = match self.surface.get_current_texture() {
            Ok(f) => f,
            Err(wgpu::SurfaceError::Lost | wgpu::SurfaceError::Outdated) => {
                self.surface.configure(&self.gpu.device, &self.config);
                self.surface
                    .get_current_texture()
                    .map_err(|e| err(e.to_string()))?
            }
            Err(e) => return Err(err(e.to_string())),
        };
        let mut encoder = self.gpu.device.create_command_encoder(&Default::default());
        self.gpu
            .encode(
                &mut encoder,
                &frame.texture.create_view(&Default::default()),
                &self.calibration,
                &view,
                width,
                height,
                antialias,
            )
            .map_err(err)?;
        self.gpu.queue.submit([encoder.finish()]);
        frame.present();
        Ok(())
    }
}
// Re-export the exact same WASM core functions in the renderer bundle.
#[wasm_bindgen]
pub fn convert_calibration(json: &str) -> Result<String, JsValue> {
    rpi360_core::convert_calibration(json).map_err(|e| JsValue::from_str(&e))
}
#[wasm_bindgen]
pub fn evaluate_project(json: &str, time_us: f64) -> Result<String, JsValue> {
    rpi360_core::evaluate_project(json, time_us).map_err(|e| JsValue::from_str(&e))
}
#[wasm_bindgen]
pub fn orientation_from_euler(yaw: f32, pitch: f32, roll: f32) -> Vec<f32> {
    rpi360_core::orientation_from_euler(yaw, pitch, roll)
}

#[wasm_bindgen]
pub fn orientation_to_euler(q: &[f32]) -> Result<Vec<f32>, JsValue> {
    let q: [f32; 4] = q
        .try_into()
        .map_err(|_| JsValue::from_str("quaternion needs four components"))?;
    Ok(rpi360_core::to_euler(q).to_vec())
}
#[wasm_bindgen]
pub fn map_rays(input: &str) -> Result<String, JsValue> {
    rpi360_core::map_rays_json(input).map_err(|e| JsValue::from_str(&e))
}
