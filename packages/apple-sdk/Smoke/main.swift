import Foundation
import RPI360
let project = #"{"schema_version":2,"id":"smoke","source_id":"fixture","duration_us":1000,"alignment_us":null,"keyframes":[{"time_us":0,"linear":true,"view":{"orientation":[0,0,0,1],"horizontal_fov_deg":90,"projection":"perspective","spin_deg":360}}],"time_remap":[{"output_us":0,"source_us":12345}]}"#
for _ in 0..<1000 {
    let data = try Core.evaluateProject(Data(project.utf8), atMicroseconds: 500)
    let object = try JSONSerialization.jsonObject(with: data) as! [String:Any]
    precondition(object["source_time_us"] as? Int == 12345)
    precondition((object["view"] as? [String:Any])?["spin_deg"] as? Int == 360)
}
print("Swift C ABI: 1000 allocation/evaluate/free cycles passed")
if CommandLine.arguments.count == 6 {
    let renderer = try Renderer()
    let calibration = try Data(contentsOf:URL(fileURLWithPath:CommandLine.arguments[1]))
    let source = try Data(contentsOf:URL(fileURLWithPath:CommandLine.arguments[2]))
    let width = UInt32(CommandLine.arguments[3])!, height = UInt32(CommandLine.arguments[4])!
    let view = Data(#"{"orientation":[0,0,0,1],"horizontal_fov_deg":90,"projection":"perspective","spin_deg":0}"#.utf8)
    try renderer.upload(rgba:source,width:width,height:height)
    let output = try renderer.render(calibration:calibration,view:view,width:320,height:180)
    try output.write(to:URL(fileURLWithPath:CommandLine.arguments[5]))
    print("Swift shared GPU: rendered 320×180 RGBA fixture")
}
