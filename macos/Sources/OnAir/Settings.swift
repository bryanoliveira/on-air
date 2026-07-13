import Foundation
import SwiftUI

final class SettingsStore: ObservableObject {
    private enum Key {
        static let serverURL = "serverURL"
        static let apiToken = "apiToken"
        static let username = "username"
    }

    @Published var serverURL: String { didSet { defaults.set(serverURL, forKey: Key.serverURL) } }
    @Published var apiToken: String { didSet { defaults.set(apiToken, forKey: Key.apiToken) } }
    @Published var username: String { didSet { defaults.set(username, forKey: Key.username) } }
    private let defaults: UserDefaults

    init(defaults: UserDefaults = .standard) {
        self.defaults = defaults
        serverURL = defaults.string(forKey: Key.serverURL) ?? ""
        apiToken = defaults.string(forKey: Key.apiToken) ?? ""
        username = defaults.string(forKey: Key.username) ?? NSUserName()
    }

    var isConfigured: Bool {
        URL(string: serverURL)?.scheme != nil && !username.trimmingCharacters(in: .whitespaces).isEmpty
    }
}

struct SettingsView: View {
    @ObservedObject var settings: SettingsStore

    var body: some View {
        Form {
            Text("On Air reports microphone and camera activity to your server. Settings are stored only on this Mac.")
                .foregroundStyle(.secondary)
            TextField("Server URL", text: $settings.serverURL, prompt: Text("https://on-air.example.net"))
            TextField("Username", text: $settings.username)
            SecureField("API token (optional)", text: $settings.apiToken)
            Text("The server URL should not include /api/v1/events. Changes take effect on the next poll (within 5 seconds).")
                .font(.caption)
                .foregroundStyle(.secondary)
        }
        .padding(20)
        .frame(width: 480, height: 275)
    }
}
