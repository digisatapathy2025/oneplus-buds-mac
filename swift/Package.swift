// swift-tools-version: 6.0
import PackageDescription

let package = Package(
    name: "OnePlusBuds",
    platforms: [
        .macOS(.v13)
    ],
    products: [
        .library(name: "OnePlusBudsCore", targets: ["OnePlusBudsCore"]),
        .executable(name: "buds", targets: ["OnePlusBudsCLI"]),
        .executable(name: "OnePlusBudsApp", targets: ["OnePlusBudsApp"]),
    ],
    targets: [
        .target(
            name: "OnePlusBudsCore",
            path: "Sources/OnePlusBudsCore",
            linkerSettings: [
                .linkedFramework("CoreBluetooth"),
                .linkedFramework("IOBluetooth"),
                .linkedFramework("Foundation"),
                .linkedFramework("AppKit")
            ]
        ),
        .executableTarget(
            name: "OnePlusBudsCLI",
            dependencies: ["OnePlusBudsCore"],
            path: "Sources/OnePlusBudsCLI"
        ),
        .executableTarget(
            name: "OnePlusBudsApp",
            dependencies: ["OnePlusBudsCore"],
            path: "Sources/OnePlusBudsApp"
        ),
    ]
)
