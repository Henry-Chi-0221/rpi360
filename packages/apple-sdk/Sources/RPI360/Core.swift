import Foundation
import RPI360Core

public enum CoreError: Error { case invalidResult; case rejected(String) }
/// Stable JSON boundary shared with WASM and Python. Native allocation is always released.
public enum Core {
    private static func result(_ pointer: UnsafeMutablePointer<CChar>?) throws -> Data {
        guard let pointer else { throw CoreError.invalidResult }
        defer { rpi360_free(pointer) }
        let data = Data(String(cString: pointer).utf8)
        if let object = try JSONSerialization.jsonObject(with: data) as? [String: Any], let error = object["error"] as? String { throw CoreError.rejected(error) }
        return data
    }
    public static func convertCalibration(_ json: Data) throws -> Data {
        guard let value = String(data: json, encoding: .utf8) else { throw CoreError.invalidResult }
        return try value.withCString { try result(rpi360_calibration($0)) }
    }
    public static func evaluateProject(_ json: Data, atMicroseconds time: Int64) throws -> Data {
        guard let value = String(data: json, encoding: .utf8) else { throw CoreError.invalidResult }
        return try value.withCString { try result(rpi360_evaluate($0, time)) }
    }
}
