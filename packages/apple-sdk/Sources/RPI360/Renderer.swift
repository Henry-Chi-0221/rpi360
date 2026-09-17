import Foundation
import CoreVideo
import RPI360Core

/// Shared wgpu/Metal renderer. Serialize calls on one queue. This portable RGBA
/// adapter deliberately copies pixels; it does not claim zero-copy CVMetalTexture import.
public final class Renderer {
    private var context: UnsafeMutableRawPointer?
    private func check(_ error: UnsafeMutablePointer<CChar>?) throws {
        if let error { defer { rpi360_free(error) }; throw CoreError.rejected(String(cString:error)) }
    }
    public init() throws { try check(rpi360_renderer_create(&context)) }
    deinit { rpi360_renderer_free(context) }
    public func upload(rgba: Data, width: UInt32, height: UInt32) throws {
        guard UInt64(width) * UInt64(height) * 4 == rgba.count else { throw CoreError.invalidResult }
        try rgba.withUnsafeBytes { data in
            try check(rpi360_renderer_upload(context, data.bindMemory(to: UInt8.self).baseAddress, data.count, width, height))
        }
    }
    public func render(calibration: Data, view: Data, width: UInt32, height: UInt32) throws -> Data {
        guard width > 0, height > 0, width <= 8192, height <= 8192,
              let cal = String(data:calibration,encoding:.utf8), let pose = String(data:view,encoding:.utf8) else { throw CoreError.invalidResult }
        var result = Data(count:Int(width)*Int(height)*4)
        try result.withUnsafeMutableBytes { data in
            try cal.withCString { c in try pose.withCString { v in
                try check(rpi360_renderer_draw(context,c,v,data.bindMemory(to:UInt8.self).baseAddress,data.count,width,height))
            }}
        }
        return result
    }
    /// Pack two decoded BGRA buffers without cropping or changing their timestamps.
    public func upload(first: CVPixelBuffer, second: CVPixelBuffer) throws {
        let width=CVPixelBufferGetWidth(first), height=CVPixelBufferGetHeight(first)
        guard width==CVPixelBufferGetWidth(second),height==CVPixelBufferGetHeight(second),
              CVPixelBufferGetPixelFormatType(first)==kCVPixelFormatType_32BGRA,
              CVPixelBufferGetPixelFormatType(second)==kCVPixelFormatType_32BGRA else {throw CoreError.invalidResult}
        var pixels=Data(count:width*2*height*4)
        try pixels.withUnsafeMutableBytes { out in
            let dst=out.bindMemory(to:UInt8.self)
            for (camera,buffer) in [first,second].enumerated() {
                guard CVPixelBufferLockBaseAddress(buffer,.readOnly)==kCVReturnSuccess else {throw CoreError.invalidResult}
                defer {CVPixelBufferUnlockBaseAddress(buffer,.readOnly)}
                guard let base=CVPixelBufferGetBaseAddress(buffer) else {throw CoreError.invalidResult}
                let source=base.assumingMemoryBound(to:UInt8.self), stride=CVPixelBufferGetBytesPerRow(buffer)
                for y in 0..<height {for x in 0..<width {
                    let s=y*stride+x*4,d=(y*width*2+camera*width+x)*4
                    dst[d]=source[s+2];dst[d+1]=source[s+1];dst[d+2]=source[s];dst[d+3]=255
                }}
            }
        }
        try upload(rgba:pixels,width:UInt32(width*2),height:UInt32(height))
    }
}
