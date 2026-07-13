// swift-tools-version: 5.9
import PackageDescription

let package = Package(
    name: "OnAir",
    platforms: [.macOS(.v13)],
    products: [.executable(name: "OnAir", targets: ["OnAir"])],
    targets: [.executableTarget(name: "OnAir")]
)
