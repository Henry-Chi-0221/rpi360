import AVFoundation
import CoreVideo

/// Sequential AVFoundation adapter preserving presentation timestamps. One sample per call.
public final class VideoFrames {
    private let reader: AVAssetReader
    private let output: AVAssetReaderTrackOutput
    public init(url: URL, videoTrackIndex: Int = 0) async throws {
        let asset = AVURLAsset(url: url)
        let tracks = try await asset.loadTracks(withMediaType: .video)
        guard tracks.indices.contains(videoTrackIndex) else { throw CoreError.rejected("Video track missing") }
        reader = try AVAssetReader(asset: asset)
        output = AVAssetReaderTrackOutput(track: tracks[videoTrackIndex], outputSettings: [kCVPixelBufferPixelFormatTypeKey as String:kCVPixelFormatType_32BGRA])
        output.alwaysCopiesSampleData = false
        guard reader.canAdd(output) else { throw CoreError.rejected("Unsupported decoder output") }
        reader.add(output)
        guard reader.startReading() else { throw reader.error ?? CoreError.rejected("Decoder did not start") }
    }
    public func next() throws -> (pixelBuffer: CVPixelBuffer, pts: CMTime)? {
        guard let sample = output.copyNextSampleBuffer() else {
            if let error = reader.error { throw error }; return nil
        }
        guard let buffer = CMSampleBufferGetImageBuffer(sample) else { throw CoreError.invalidResult }
        return (buffer,CMSampleBufferGetPresentationTimeStamp(sample))
    }
    deinit { reader.cancelReading() }
}
