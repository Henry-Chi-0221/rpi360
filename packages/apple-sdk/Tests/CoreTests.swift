import XCTest
@testable import RPI360
final class CoreTests: XCTestCase {
    func testErrorBoundary() {
        XCTAssertThrowsError(try Core.convertCalibration(Data("{}".utf8)))
    }
    func testSpinAndSourceTime() throws {
        let project = #"{"schema_version":2,"id":"test","source_id":"fixture","duration_us":1000000,"alignment_us":null,"keyframes":[{"time_us":0,"linear":true,"view":{"orientation":[0,0,0,1],"horizontal_fov_deg":90,"projection":"perspective","spin_deg":0}},{"time_us":1000000,"linear":true,"view":{"orientation":[0,0,0,1],"horizontal_fov_deg":90,"projection":"perspective","spin_deg":360}}],"time_remap":[{"output_us":0,"source_us":2000000},{"output_us":1000000,"source_us":4000000}]}"#
        let output = try Core.evaluateProject(Data(project.utf8), atMicroseconds: 500000)
        let result = try XCTUnwrap(try JSONSerialization.jsonObject(with: output) as? [String:Any])
        XCTAssertEqual(result["source_time_us"] as? Int,3000000)
        XCTAssertEqual((result["view"] as? [String:Any])?["spin_deg"] as? Int,180)
    }
}
