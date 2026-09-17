import Foundation
import CoreVideo
import RPI360
// Add RPI360 to an iOS/macOS target, then call from an async Task.
func inspectSource(url: URL, calibration: Data, project: Data) async throws {
    _ = try Core.convertCalibration(calibration)
    let frames = try await VideoFrames(url: url)
    if let frame = try frames.next() {
        let mediaTime = Int64(frame.pts.seconds * 1_000_000)
        print(String(data: try Core.evaluateProject(project, atMicroseconds: mediaTime), encoding: .utf8)!)
        // Select the matching second-camera frame by its PTS plus the manifest's
        // media_start_offset_us. Do not pair the two readers by frame number.
    }
}

// Call after a media adapter has selected a pair on the shared session clock.
// UI orientation/FOV changes reuse these buffers without another camera request.
func renderPair(first: CVPixelBuffer, second: CVPixelBuffer,
                calibration: Data, project: Data, outputTimeUs: Int64,
                renderer: Renderer) throws -> Data {
    let evaluated = try Core.evaluateProject(project, atMicroseconds: outputTimeUs)
    guard let value = try JSONSerialization.jsonObject(with: evaluated) as? [String: Any],
          let view = value["view"] else { throw CoreError.invalidResult }
    try renderer.upload(first: first, second: second)
    return try renderer.render(calibration: Core.convertCalibration(calibration),
                               view: JSONSerialization.data(withJSONObject: view),
                               width: 1280, height: 720)
}
