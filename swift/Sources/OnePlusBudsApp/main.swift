import AppKit
import Foundation
import OnePlusBudsCore

// ==============================================================================
// Custom Capsule Battery Pill View
// ==============================================================================
final class BatteryPillView: NSView {
    var level: Int = 0 { didSet { needsDisplay = true } }
    var isCharging: Bool = false { didSet { needsDisplay = true } }
    var isConnected: Bool = false { didSet { needsDisplay = true } }

    override var isFlipped: Bool { true }

    override func draw(_ dirtyRect: NSRect) {
        super.draw(dirtyRect)
        let bounds = self.bounds
        let bgPath = NSBezierPath(roundedRect: bounds, xRadius: bounds.height / 2.0, yRadius: bounds.height / 2.0)
        NSColor.separatorColor.withAlphaComponent(0.25).setFill()
        bgPath.fill()

        guard isConnected && level > 0 else { return }

        let fillWidth = max(bounds.height, bounds.width * CGFloat(min(100, max(0, level))) / 100.0)
        let fillRect = NSRect(x: 0, y: 0, width: fillWidth, height: bounds.height)
        let fillPath = NSBezierPath(roundedRect: fillRect, xRadius: bounds.height / 2.0, yRadius: bounds.height / 2.0)

        if isCharging {
            NSColor.systemGreen.setFill()
        } else if level > 20 {
            NSColor.systemGreen.setFill()
        } else if level > 10 {
            NSColor.systemOrange.setFill()
        } else {
            NSColor.systemRed.setFill()
        }
        fillPath.fill()
    }
}

// ==============================================================================
// Rounded Translucent Card View
// ==============================================================================
final class RoundedCardView: NSView {
    override var isFlipped: Bool { true }

    override init(frame: NSRect) {
        super.init(frame: frame)
        wantsLayer = true
        layer?.cornerRadius = 12.0
        layer?.masksToBounds = true
    }

    required init?(coder: NSCoder) { fatalError("init(coder:) has not been implemented") }

    override func draw(_ dirtyRect: NSRect) {
        let path = NSBezierPath(roundedRect: bounds, xRadius: 12.0, yRadius: 12.0)
        NSColor.labelColor.withAlphaComponent(0.045).setFill()
        path.fill()
        NSColor.separatorColor.withAlphaComponent(0.20).setStroke()
        path.lineWidth = 1.0
        path.stroke()
    }
}

// ==============================================================================
// Popover View Controller
// ==============================================================================
final class BudsPopoverViewController: NSViewController {
    let controller = BluetoothController.shared

    // UI Elements
    private let titleLabel = NSTextField(labelWithString: "OnePlus Buds")
    private let statusDot = NSTextField(labelWithString: "● Disconnected")
    private let connectButton = NSButton(title: "Connect", target: nil, action: nil)

    private let leftPercentLabel = NSTextField(labelWithString: "--%")
    private let rightPercentLabel = NSTextField(labelWithString: "--%")
    private let casePercentLabel = NSTextField(labelWithString: "--%")

    private let leftPill = BatteryPillView()
    private let rightPill = BatteryPillView()
    private let casePill = BatteryPillView()

    private let noiseSegment = NSSegmentedControl(labels: ["Noise Cancellation", "Off", "Transparency"], trackingMode: .selectOne, target: nil, action: nil)
    private let ancLevelSegment = NSSegmentedControl(labels: ["Auto", "Low", "Moderate", "High"], trackingMode: .selectOne, target: nil, action: nil)

    private let bassSwitch = NSSwitch()
    private let gameSwitch = NSSwitch()
    private let inEarSwitch = NSSwitch()
    private let dualSwitch = NSSwitch()
    private let spatialSwitch = NSSwitch()

    private let eqSegment = NSSegmentedControl(labels: ["Balanced", "Bass", "Clear", "Bold"], trackingMode: .selectOne, target: nil, action: nil)

    override func loadView() {
        let visualEffect = NSVisualEffectView(frame: NSRect(x: 0, y: 0, width: 340, height: 600))
        visualEffect.material = .popover
        visualEffect.blendingMode = .behindWindow
        visualEffect.state = .active
        self.view = visualEffect

        setupUI()
    }

    private func setupUI() {
        let container = view

        // 1. Header (y: 16)
        let iconView = NSImageView(frame: NSRect(x: 16, y: 16, width: 36, height: 36))
        iconView.image = NSImage(systemSymbolName: "airpodspro", accessibilityDescription: nil)
        iconView.contentTintColor = .labelColor
        container.addSubview(iconView)

        titleLabel.frame = NSRect(x: 60, y: 14, width: 170, height: 20)
        titleLabel.font = NSFont.systemFont(ofSize: 13, weight: .bold)
        container.addSubview(titleLabel)

        statusDot.frame = NSRect(x: 60, y: 34, width: 170, height: 16)
        statusDot.font = NSFont.systemFont(ofSize: 11, weight: .medium)
        statusDot.textColor = .secondaryLabelColor
        container.addSubview(statusDot)

        connectButton.frame = NSRect(x: 236, y: 20, width: 88, height: 28)
        connectButton.bezelStyle = .rounded
        connectButton.target = self
        connectButton.action = #selector(onConnectToggle)
        container.addSubview(connectButton)

        // 2. Battery Card (y: 64, height: 90)
        let batCard = RoundedCardView(frame: NSRect(x: 14, y: 64, width: 312, height: 90))
        container.addSubview(batCard)

        setupBatteryColumn(in: batCard, x: 12, label: "Left", percentLabel: leftPercentLabel, pill: leftPill)
        setupBatteryColumn(in: batCard, x: 112, label: "Right", percentLabel: rightPercentLabel, pill: rightPill)
        setupBatteryColumn(in: batCard, x: 212, label: "Case", percentLabel: casePercentLabel, pill: casePill)

        // 3. Noise Control (y: 164)
        let noiseTitle = NSTextField(labelWithString: "NOISE CONTROL")
        noiseTitle.frame = NSRect(x: 16, y: 164, width: 300, height: 14)
        noiseTitle.font = NSFont.systemFont(ofSize: 10, weight: .semibold)
        noiseTitle.textColor = .secondaryLabelColor
        container.addSubview(noiseTitle)

        noiseSegment.frame = NSRect(x: 14, y: 182, width: 312, height: 26)
        noiseSegment.target = self
        noiseSegment.action = #selector(onNoiseChanged)
        container.addSubview(noiseSegment)

        ancLevelSegment.frame = NSRect(x: 14, y: 214, width: 312, height: 24)
        ancLevelSegment.target = self
        ancLevelSegment.action = #selector(onAncLevelChanged)
        container.addSubview(ancLevelSegment)

        // 4. Audio Enhancements Card (y: 248, height: 200)
        let enhCard = RoundedCardView(frame: NSRect(x: 14, y: 248, width: 312, height: 200))
        container.addSubview(enhCard)

        setupToggleRow(in: enhCard, y: 8, title: "BassWave™ (Bass Boost)", color: .systemPurple, sfSymbol: "waveform", toggle: bassSwitch, action: #selector(onBassChanged))
        setupToggleRow(in: enhCard, y: 46, title: "Game Mode (Low Latency)", color: .systemOrange, sfSymbol: "gamecontroller.fill", toggle: gameSwitch, action: #selector(onGameChanged))
        setupToggleRow(in: enhCard, y: 84, title: "In-Ear Wear Detection", color: .systemGreen, sfSymbol: "ear.fill", toggle: inEarSwitch, action: #selector(onInEarChanged))
        setupToggleRow(in: enhCard, y: 122, title: "Dual Connection", color: .systemTeal, sfSymbol: "arrow.triangle.2.circlepath", toggle: dualSwitch, action: #selector(onDualChanged))
        setupToggleRow(in: enhCard, y: 160, title: "Spatial Audio (3D Sound)", color: .systemBlue, sfSymbol: "sparkles", toggle: spatialSwitch, action: #selector(onSpatialChanged))

        // 5. Sound Master EQ (y: 458)
        let eqTitle = NSTextField(labelWithString: "SOUND MASTER EQUALIZER")
        eqTitle.frame = NSRect(x: 16, y: 458, width: 300, height: 14)
        eqTitle.font = NSFont.systemFont(ofSize: 10, weight: .semibold)
        eqTitle.textColor = .secondaryLabelColor
        container.addSubview(eqTitle)

        eqSegment.frame = NSRect(x: 14, y: 476, width: 312, height: 26)
        eqSegment.target = self
        eqSegment.action = #selector(onEqChanged)
        container.addSubview(eqSegment)

        // 6. Footer (y: 520)
        let refreshBtn = NSButton(title: "Refresh", target: self, action: #selector(onRefreshClicked))
        refreshBtn.frame = NSRect(x: 14, y: 520, width: 150, height: 28)
        refreshBtn.bezelStyle = .rounded
        container.addSubview(refreshBtn)

        let quitBtn = NSButton(title: "Quit", target: self, action: #selector(onQuitClicked))
        quitBtn.frame = NSRect(x: 176, y: 520, width: 150, height: 28)
        quitBtn.bezelStyle = .rounded
        container.addSubview(quitBtn)
    }

    private func setupBatteryColumn(in container: NSView, x: CGFloat, label: String, percentLabel: NSTextField, pill: BatteryPillView) {
        let nameLbl = NSTextField(labelWithString: label)
        nameLbl.frame = NSRect(x: x, y: 12, width: 88, height: 16)
        nameLbl.font = NSFont.systemFont(ofSize: 11, weight: .medium)
        nameLbl.textColor = .secondaryLabelColor
        nameLbl.alignment = .center
        container.addSubview(nameLbl)

        percentLabel.frame = NSRect(x: x, y: 30, width: 88, height: 22)
        percentLabel.font = NSFont.systemFont(ofSize: 16, weight: .bold)
        percentLabel.alignment = .center
        container.addSubview(percentLabel)

        pill.frame = NSRect(x: x + 10, y: 60, width: 68, height: 8)
        container.addSubview(pill)
    }

    private func setupToggleRow(in container: NSView, y: CGFloat, title: String, color: NSColor, sfSymbol: String, toggle: NSSwitch, action: Selector) {
        let badge = NSView(frame: NSRect(x: 12, y: y, width: 28, height: 28))
        badge.wantsLayer = true
        badge.layer?.cornerRadius = 6.0
        badge.layer?.backgroundColor = color.cgColor
        container.addSubview(badge)

        let img = NSImageView(frame: NSRect(x: 4, y: 4, width: 20, height: 20))
        img.image = NSImage(systemSymbolName: sfSymbol, accessibilityDescription: nil)
        img.contentTintColor = .white
        badge.addSubview(img)

        let lbl = NSTextField(labelWithString: title)
        lbl.frame = NSRect(x: 48, y: y + 4, width: 200, height: 20)
        lbl.font = NSFont.systemFont(ofSize: 12, weight: .medium)
        container.addSubview(lbl)

        toggle.frame = NSRect(x: 260, y: y + 2, width: 40, height: 24)
        toggle.target = self
        toggle.action = action
        container.addSubview(toggle)
    }

    func updateUI() {
        titleLabel.stringValue = controller.activeProfile?.name ?? "OnePlus Buds"

        if controller.isConnected {
            statusDot.stringValue = "● Connected"
            statusDot.textColor = .systemGreen
            connectButton.title = "Disconnect"
        } else if controller.isConnecting {
            statusDot.stringValue = "● Connecting..."
            statusDot.textColor = .systemOrange
            connectButton.title = "Cancel"
        } else {
            statusDot.stringValue = "● Disconnected"
            statusDot.textColor = .secondaryLabelColor
            connectButton.title = "Connect"
        }

        // Battery
        let b = controller.battery
        leftPercentLabel.stringValue = b.left.isConnected ? "\(b.left.level)%\(b.left.isCharging ? " ⚡" : "")" : "--%"
        rightPercentLabel.stringValue = b.right.isConnected ? "\(b.right.level)%\(b.right.isCharging ? " ⚡" : "")" : "--%"
        casePercentLabel.stringValue = b.caseBattery.isConnected ? "\(b.caseBattery.level)%\(b.caseBattery.isCharging ? " ⚡" : "")" : "--%"

        leftPill.level = b.left.level
        leftPill.isCharging = b.left.isCharging
        leftPill.isConnected = b.left.isConnected

        rightPill.level = b.right.level
        rightPill.isCharging = b.right.isCharging
        rightPill.isConnected = b.right.isConnected

        casePill.level = b.caseBattery.level
        casePill.isCharging = b.caseBattery.isCharging
        casePill.isConnected = b.caseBattery.isConnected

        // Noise Control
        switch controller.primaryMode {
        case .noiseCancellation:
            noiseSegment.selectedSegment = 0
            ancLevelSegment.isEnabled = true
        case .off:
            noiseSegment.selectedSegment = 1
            ancLevelSegment.isEnabled = false
        case .transparency:
            noiseSegment.selectedSegment = 2
            ancLevelSegment.isEnabled = false
        }

        switch controller.ancLevel {
        case .auto: ancLevelSegment.selectedSegment = 0
        case .low: ancLevelSegment.selectedSegment = 1
        case .moderate: ancLevelSegment.selectedSegment = 2
        case .high: ancLevelSegment.selectedSegment = 3
        }

        // Feature switches
        bassSwitch.state = (controller.featureStates[.bassEngine] == true) ? .on : .off
        gameSwitch.state = (controller.featureStates[.gameMode] == true) ? .on : .off
        inEarSwitch.state = (controller.featureStates[.inEar] == true) ? .on : .off
        dualSwitch.state = (controller.featureStates[.dualConnect] == true) ? .on : .off
        spatialSwitch.state = (controller.featureStates[.spatialAudio] == true) ? .on : .off

        // EQ
        switch controller.currentEq {
        case .balanced: eqSegment.selectedSegment = 0
        case .bass: eqSegment.selectedSegment = 1
        case .clear: eqSegment.selectedSegment = 2
        case .bold: eqSegment.selectedSegment = 3
        }
    }

    // =========================================================================
    // Actions
    // =========================================================================
    @objc private func onConnectToggle() {
        if controller.isConnected {
            controller.disconnect()
        } else {
            controller.attemptFastConnect()
        }
    }

    @objc private func onNoiseChanged() {
        let seg = noiseSegment.selectedSegment
        if seg == 0 {
            controller.setNoiseMode(primary: .noiseCancellation, level: controller.ancLevel)
        } else if seg == 1 {
            controller.setNoiseMode(primary: .off)
        } else {
            controller.setNoiseMode(primary: .transparency)
        }
    }

    @objc private func onAncLevelChanged() {
        let levels: [AncLevel] = [.auto, .low, .moderate, .high]
        let idx = ancLevelSegment.selectedSegment
        if idx >= 0 && idx < levels.count {
            controller.setNoiseMode(primary: .noiseCancellation, level: levels[idx])
        }
    }

    @objc private func onBassChanged() {
        controller.setFeature(.bassEngine, enabled: bassSwitch.state == .on)
    }

    @objc private func onGameChanged() {
        controller.setFeature(.gameMode, enabled: gameSwitch.state == .on)
    }

    @objc private func onInEarChanged() {
        controller.setFeature(.inEar, enabled: inEarSwitch.state == .on)
    }

    @objc private func onDualChanged() {
        controller.setFeature(.dualConnect, enabled: dualSwitch.state == .on)
    }

    @objc private func onSpatialChanged() {
        controller.setFeature(.spatialAudio, enabled: spatialSwitch.state == .on)
    }

    @objc private func onEqChanged() {
        let presets: [EqualizerPreset] = [.balanced, .bass, .clear, .bold]
        let idx = eqSegment.selectedSegment
        if idx >= 0 && idx < presets.count {
            controller.setEqualizer(presets[idx])
        }
    }

    @objc private func onRefreshClicked() {
        controller.refresh()
    }

    @objc private func onQuitClicked() {
        NSApplication.shared.terminate(nil)
    }
}

// ==============================================================================
// Menu Bar Application Delegate
// ==============================================================================
@MainActor
final class AppDelegate: NSObject, NSApplicationDelegate, BluetoothControllerDelegate, SystemAudioMonitorDelegate {
    private var statusItem: NSStatusItem!
    private var popover: NSPopover!
    private let controller = BluetoothController.shared
    private let audioMonitor = SystemAudioMonitor()
    private var popoverVC: BudsPopoverViewController!

    func applicationDidFinishLaunching(_ notification: Notification) {
        controller.delegate = self
        audioMonitor.delegate = self
        audioMonitor.start()

        setupStatusItem()
        setupPopover()

        // Check initial active audio device
        if let (profile, _) = SystemAudioMonitor.findConnectedSupportedDevice() {
            controller.attemptFastConnect()
            updateStatusItem(connected: true, profileName: profile.name)
        } else {
            updateStatusItem(connected: false, profileName: nil)
        }
    }

    private func setupStatusItem() {
        statusItem = NSStatusBar.system.statusItem(withLength: NSStatusItem.variableLength)
        guard let button = statusItem.button else { return }

        let icon = NSImage(systemSymbolName: "airpodspro", accessibilityDescription: "OnePlus Buds")
        icon?.isTemplate = true
        button.image = icon
        button.imagePosition = .imageOnly
        button.title = ""
        button.target = self
        button.action = #selector(onStatusItemClicked)
    }

    private func setupPopover() {
        popover = NSPopover()
        popover.behavior = .transient
        popover.animates = true
        popoverVC = BudsPopoverViewController()
        popover.contentViewController = popoverVC
    }

    @objc private func onStatusItemClicked() {
        guard let button = statusItem.button else { return }
        if popover.isShown {
            popover.performClose(nil)
        } else {
            if !controller.isConnected {
                controller.attemptFastConnect()
            }
            popoverVC.updateUI()
            popover.show(relativeTo: button.bounds, of: button, preferredEdge: .minY)
        }
    }

    private func updateStatusItem(connected: Bool, profileName: String?) {
        guard let button = statusItem.button else { return }
        if connected {
            statusItem.length = NSStatusItem.variableLength
            let name = profileName ?? "OnePlus Buds"
            let left = controller.battery.left.isConnected ? "L: \(controller.battery.left.level)% " : ""
            let right = controller.battery.right.isConnected ? "R: \(controller.battery.right.level)% " : ""
            let caseBat = controller.battery.caseBattery.isConnected ? "Case: \(controller.battery.caseBattery.level)%" : ""
            button.toolTip = "\(name)\n\(left)\(right)\(caseBat)".trimmingCharacters(in: .whitespaces)
        } else {
            // Dynamic collapse to 0px
            statusItem.length = 0.0
            button.toolTip = "OnePlus Buds (Disconnected)"
        }
    }

    // =========================================================================
    // BluetoothControllerDelegate
    // =========================================================================
    func controllerStateChanged() {
        popoverVC.updateUI()
        updateStatusItem(connected: controller.isConnected, profileName: controller.activeProfile?.name)
    }

    func logMessage(_ message: String) {
        // App log
    }

    // =========================================================================
    // SystemAudioMonitorDelegate
    // =========================================================================
    func audioDeviceConnected(name: String, profile: DeviceProfile) {
        controller.attemptFastConnect()
        updateStatusItem(connected: true, profileName: profile.name)
    }

    func audioDeviceDisconnected(name: String, profile: DeviceProfile) {
        controller.disconnect()
        updateStatusItem(connected: false, profileName: nil)
        if popover.isShown {
            popover.performClose(nil)
        }
    }
}

// Entry Point
@MainActor
func runApp() {
    let app = NSApplication.shared
    let delegate = AppDelegate()
    app.delegate = delegate
    app.setActivationPolicy(.accessory)
    app.run()
}

runApp()
