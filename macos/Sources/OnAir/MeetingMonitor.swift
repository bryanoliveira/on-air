import Foundation

private struct EventPayload: Encodable {
    let username: String
    let eventType: String
    let micActive: Bool
    let cameraActive: Bool
    let timestamp: String

    enum CodingKeys: String, CodingKey {
        case username, timestamp
        case eventType = "event_type"
        case micActive = "mic_active"
        case cameraActive = "camera_active"
    }
}

final class MeetingMonitor {
    private let settings: SettingsStore
    private let detector = DeviceActivityDetector()
    private let report: (MeetingState, String) -> Void
    private let queue = DispatchQueue(label: "dev.on-air.monitor", qos: .utility)
    private var timer: DispatchSourceTimer?
    private var meetingActive = false
    private var lastActivity: Date?
    private var lastHeartbeat: Date?
    private var latest = DeviceActivity(microphone: false, camera: false)
    private let heartbeatInterval: TimeInterval = 180
    private let inactiveGrace: TimeInterval = 30

    init(settings: SettingsStore, report: @escaping (MeetingState, String) -> Void) {
        self.settings = settings
        self.report = report
    }

    func start() {
        let timer = DispatchSource.makeTimerSource(queue: queue)
        timer.schedule(deadline: .now(), repeating: 5)
        timer.setEventHandler { [weak self] in self?.poll() }
        self.timer = timer
        timer.resume()
    }

    func stop(sendFinished: Bool) {
        timer?.cancel()
        timer = nil
        if sendFinished && meetingActive {
            send(eventType: "finished-meeting", activity: latest)
        }
    }

    func sendCurrentState() {
        queue.async { [weak self] in
            guard let self else { return }
            self.send(eventType: self.meetingActive ? "in-meeting" : "finished-meeting", activity: self.latest)
        }
    }

    private func poll() {
        let now = Date()
        latest = detector.current()
        if latest.isMeeting {
            lastActivity = now
            if !meetingActive || lastHeartbeat.map({ now.timeIntervalSince($0) >= heartbeatInterval }) ?? true {
                meetingActive = true
                lastHeartbeat = now
                send(eventType: "in-meeting", activity: latest)
            }
            let devices = [latest.microphone ? "microphone" : nil, latest.camera ? "camera" : nil]
                .compactMap { $0 }.joined(separator: " + ")
            report(.active(mic: latest.microphone, camera: latest.camera), "Meeting detected: \(devices)")
        } else if meetingActive, let lastActivity, now.timeIntervalSince(lastActivity) >= inactiveGrace {
            meetingActive = false
            lastHeartbeat = nil
            send(eventType: "finished-meeting", activity: latest)
            report(.idle, "No meeting detected")
        } else if !meetingActive {
            report(.idle, "No meeting detected")
        }
    }

    private func send(eventType: String, activity: DeviceActivity) {
        let urlString = settings.serverURL.trimmingCharacters(in: .whitespacesAndNewlines)
            .trimmingCharacters(in: CharacterSet(charactersIn: "/")) + "/api/v1/events"
        guard settings.isConfigured, let url = URL(string: urlString) else {
            report(.error, "Configure a valid server URL")
            return
        }
        let formatter = ISO8601DateFormatter()
        let payload = EventPayload(username: settings.username, eventType: eventType,
                                   micActive: activity.microphone, cameraActive: activity.camera,
                                   timestamp: formatter.string(from: Date()))
        var request = URLRequest(url: url)
        request.httpMethod = "POST"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        if !settings.apiToken.isEmpty {
            request.setValue("Bearer \(settings.apiToken)", forHTTPHeaderField: "Authorization")
        }
        do {
            request.httpBody = try JSONEncoder().encode(payload)
        } catch {
            report(.error, "Could not encode status")
            return
        }
        URLSession.shared.dataTask(with: request) { [weak self] _, response, error in
            if let error {
                self?.report(.error, "Server error: \(error.localizedDescription)")
                return
            }
            guard let status = (response as? HTTPURLResponse)?.statusCode, 200..<300 ~= status else {
                self?.report(.error, "Server rejected status update")
                return
            }
        }.resume()
    }
}
