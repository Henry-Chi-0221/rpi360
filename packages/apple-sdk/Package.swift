// swift-tools-version: 5.9
import PackageDescription
let package = Package(
    name: "RPI360", platforms: [.iOS(.v16), .macOS(.v13)],
    products: [.library(name: "RPI360", targets: ["RPI360"])],
    targets: [
        .binaryTarget(name: "RPI360Core", path: "RPI360Core.xcframework"),
        .target(name: "RPI360", dependencies: ["RPI360Core"], linkerSettings: [
            .linkedFramework("Metal"), .linkedFramework("QuartzCore"),
            .linkedFramework("Foundation"), .linkedFramework("CoreGraphics"),
            .linkedLibrary("c++")]),
        .executableTarget(name: "RPI360Smoke", dependencies: ["RPI360"], path: "Smoke"),
        .testTarget(name: "RPI360Tests", dependencies: ["RPI360"], path: "Tests")
    ])
