import AppKit
import SwiftUI

final class AppDelegate: NSObject, NSApplicationDelegate {
    private let settings = SettingsStore()
    private var statusController: StatusController!
    private var meetingMonitor: MeetingMonitor!
    private var settingsWindow: NSWindow?

    func applicationDidFinishLaunching(_ notification: Notification) {
        statusController = StatusController(
            openSettings: { [weak self] in self?.showSettings() },
            quit: { NSApplication.shared.terminate(nil) }
        )
        meetingMonitor = MeetingMonitor(settings: settings) { [weak self] state, message in
            DispatchQueue.main.async { self?.statusController.update(state: state, message: message) }
        }
        statusController.sendNow = { [weak self] in self?.meetingMonitor.sendCurrentState() }
        meetingMonitor.start()

        if !settings.isConfigured {
            showSettings()
        }
    }

    func applicationWillTerminate(_ notification: Notification) {
        meetingMonitor?.stop(sendFinished: true)
    }

    private func showSettings() {
        if settingsWindow == nil {
            let view = SettingsView(settings: settings)
            let window = NSWindow(contentViewController: NSHostingController(rootView: view))
            window.title = "On Air Settings"
            window.styleMask = [.titled, .closable]
            window.setContentSize(NSSize(width: 480, height: 275))
            window.center()
            window.isReleasedWhenClosed = false
            settingsWindow = window
        }
        NSApplication.shared.activate(ignoringOtherApps: true)
        settingsWindow?.makeKeyAndOrderFront(nil)
    }
}
