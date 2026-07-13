import AppKit

enum MeetingState {
    case idle
    case active(mic: Bool, camera: Bool)
    case error
}

final class StatusController: NSObject {
    private let statusItem = NSStatusBar.system.statusItem(withLength: NSStatusItem.squareLength)
    private let statusLine = NSMenuItem(title: "Checking devices…", action: nil, keyEquivalent: "")
    var sendNow: (() -> Void)?

    init(openSettings: @escaping () -> Void, quit: @escaping () -> Void) {
        self.openSettings = openSettings
        self.quit = quit
        super.init()
        let menu = NSMenu()
        statusLine.isEnabled = false
        menu.addItem(statusLine)
        menu.addItem(.separator())
        let sendItem = NSMenuItem(title: "Send status now", action: #selector(sendStatus), keyEquivalent: "")
        sendItem.target = self
        menu.addItem(sendItem)
        let settingsItem = NSMenuItem(title: "Settings…", action: #selector(openSettingsAction), keyEquivalent: ",")
        settingsItem.target = self
        menu.addItem(settingsItem)
        menu.addItem(.separator())
        let quitItem = NSMenuItem(title: "Quit On Air", action: #selector(quitAction), keyEquivalent: "q")
        quitItem.target = self
        menu.addItem(quitItem)
        statusItem.menu = menu
        update(state: .idle, message: "No meeting detected")
    }

    private let openSettings: () -> Void
    private let quit: () -> Void

    @objc private func openSettingsAction() { openSettings() }
    @objc private func quitAction() { quit() }
    @objc private func sendStatus() { sendNow?() }

    func update(state: MeetingState, message: String) {
        statusLine.title = message
        let symbol: String
        switch state {
        case .idle: symbol = "circle"
        case .active(let mic, let camera):
            symbol = camera ? "video.fill" : (mic ? "mic.fill" : "circle.fill")
        case .error: symbol = "exclamationmark.triangle"
        }
        let image = NSImage(systemSymbolName: symbol, accessibilityDescription: message)
        image?.isTemplate = true
        statusItem.button?.image = image
        statusItem.button?.toolTip = message
    }
}
