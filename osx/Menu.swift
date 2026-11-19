import AppKit
import Darwin

enum WindowError: String, Error {
    case busy = "An unlock is already in progress."
    case unavailable = "The Bitwarden window service is unavailable."
    case authentication = "Unlock failed. Check your master password and CLI login."
    case clock = "Could not read the authentication clock."
    case timeout = "The operation timed out."
}

// Both unlock interfaces hold the same inode from before prompting through startup.
final class AuthLock: Sendable {
    private let fd: Int32

    init(home: URL) throws {
        let parent = home.appendingPathComponent(".local/state")
        try FileManager.default.createDirectory(at: parent, withIntermediateDirectories: true)
        let directory = parent.appendingPathComponent("bw-window").path
        guard mkdir(directory, 0o700) == 0 || errno == EEXIST else { throw WindowError.unavailable }
        let dir = open(directory, O_RDONLY | O_DIRECTORY | O_NOFOLLOW | O_CLOEXEC)
        guard dir >= 0 else { throw WindowError.unavailable }
        defer { close(dir) }
        var info = stat()
        guard fstat(dir, &info) == 0, info.st_uid == getuid(), info.st_mode & 0o777 == 0o700
        else { throw WindowError.unavailable }

        let file = openat(dir, "auth.lock", O_RDWR | O_CREAT | O_NOFOLLOW | O_CLOEXEC | O_NONBLOCK, 0o600)
        guard file >= 0 else { throw WindowError.unavailable }
        guard fstat(file, &info) == 0, info.st_uid == getuid(), info.st_mode & S_IFMT == S_IFREG,
              info.st_mode & 0o077 == 0 else {
            close(file)
            throw WindowError.unavailable
        }
        guard flock(file, LOCK_EX | LOCK_NB) == 0 else {
            let busy = errno == EWOULDBLOCK
            close(file)
            throw busy ? WindowError.busy : WindowError.unavailable
        }
        fd = file
    }

    deinit { close(fd) }
}

struct WindowClient {
    let home: URL
    private struct Paths: Decodable {
        let bw: String
        let cli_env: [String: String]?
    }
    private func paths() throws -> Paths {
        let url = home.appendingPathComponent(".local/lib/bw-window/paths.json")
        let paths = try JSONDecoder().decode(Paths.self, from: Data(contentsOf: url))
        guard paths.bw.hasPrefix("/") else { throw WindowError.unavailable }
        return paths
    }
    var broker: URL { home.appendingPathComponent(".local/bin/bw-window") }

    private func run(_ tool: URL, _ arguments: [String], input: Data? = nil, timeout: TimeInterval = 90) throws -> (Int32, Data) {
        let process = Process()
        let output = Pipe()
        let pipe = input == nil ? nil : Pipe()
        process.executableURL = tool
        process.arguments = arguments
        var environment = try paths().cli_env ?? [:]
        environment["HOME"] = home.path
        environment["PATH"] = tool.deletingLastPathComponent().path + ":/usr/bin:/bin"
        environment["LC_ALL"] = "C"
        process.environment = environment
        process.standardInput = pipe?.fileHandleForReading ?? FileHandle.nullDevice
        process.standardOutput = output
        process.standardError = FileHandle.nullDevice
        try process.run()
        let watchdog = DispatchWorkItem {
            if process.isRunning { kill(process.processIdentifier, SIGKILL) }
        }
        DispatchQueue.global().asyncAfter(deadline: .now() + timeout, execute: watchdog)
        defer { watchdog.cancel() }
        // The read end was supplied as a FileHandle rather than a Pipe.
        try pipe?.fileHandleForReading.close()
        if let input, let writer = pipe?.fileHandleForWriting {
            do {
                try writer.write(contentsOf: input)
                try writer.close()
            } catch {
                try? writer.close()
                process.waitUntilExit()
                throw WindowError.unavailable
            }
        }
        let data = try output.fileHandleForReading.readToEnd() ?? Data()
        process.waitUntilExit()
        if process.terminationReason == .uncaughtSignal && process.terminationStatus == SIGKILL {
            throw WindowError.timeout
        }
        return (process.terminationStatus, data)
    }

    func status() throws -> Int? {
        let (code, data) = try run(broker, ["status"])
        if code == 1 { return nil }
        if code == 4 { throw WindowError.busy }
        let line = String(decoding: data, as: UTF8.self).trimmingCharacters(in: .newlines)
        let prefix = "Bitwarden window open; "
        let suffix = " seconds remaining."
        guard code == 0, line.hasPrefix(prefix), line.hasSuffix(suffix),
              let seconds = Int(line.dropFirst(prefix.count).dropLast(suffix.count)), (0...3600).contains(seconds)
        else { throw WindowError.unavailable }
        return seconds
    }

    func unlock(password: Data, holding lock: AuthLock) throws {
        defer { withExtendedLifetime(lock) {} }
        // A prompt can remain open while another client starts a window.
        guard try status() == nil else { throw WindowError.busy }
        let tool = URL(fileURLWithPath: try paths().bw)
        do {
            let (code, raw) = try run(tool, ["--nointeraction", "unlock", "--passwordfile", "/dev/stdin", "--raw"],
                                      input: password)
            guard code == 0 else { throw WindowError.authentication }
            var scale = mach_timebase_info_data_t()
            guard mach_timebase_info(&scale) == KERN_SUCCESS, scale.denom != 0 else { throw WindowError.clock }
            let stamp = String(Int(Double(mach_continuous_time()) * Double(scale.numer) / Double(scale.denom) / 1e9))
            var token = raw
            while token.last == 10 || token.last == 13 { token.removeLast() }
            guard (1...1024).contains(token.count), token.allSatisfy({ (33...126).contains($0) })
            else { throw WindowError.authentication }
            guard try run(broker, ["start", stamp], input: token).0 == 0 else { throw WindowError.unavailable }
        } catch {
            let failure = error
            // Still holding auth.lock. A live or starting lease owns its own relock.
            let shouldRelock: Bool
            do { shouldRelock = try status() == nil }
            catch WindowError.busy { shouldRelock = false }
            catch { shouldRelock = true }
            if shouldRelock { _ = try? run(tool, ["--nointeraction", "lock"]) }
            throw failure
        }
    }

}

@MainActor
final class MenuApp: NSObject, NSApplicationDelegate, NSWindowDelegate {
    private let client = WindowClient(home: URL(fileURLWithPath: ProcessInfo.processInfo.environment["HOME"] ?? NSHomeDirectory()))
    private let item = NSStatusBar.system.statusItem(withLength: NSStatusItem.variableLength)
    private var deadline: ContinuousClock.Instant?
    private var generation = 0
    private var poll: Task<Void, Never>?
    private var preparing = false
    private var starting = false
    private var errorText: String?
    private var panel: NSPanel?
    private var field: NSSecureTextField?
    private var authLock: AuthLock?

    func applicationDidFinishLaunching(_ notification: Notification) {
        item.autosaveName = "BitwardenWindowPublic"
        guard let button = item.button else { return }
        button.imagePosition = .imageLeading
        button.target = self
        button.action = #selector(clicked)
        render()
        refresh()
        for (interval, selector) in [(1.0, #selector(tick)), (30.0, #selector(refresh))] {
            let timer = Timer(timeInterval: interval, target: self, selector: selector, userInfo: nil, repeats: true)
            RunLoop.main.add(timer, forMode: .common)
        }
        let center = NSWorkspace.shared.notificationCenter
        for name in [NSWorkspace.willSleepNotification, NSWorkspace.sessionDidResignActiveNotification] {
            center.addObserver(self, selector: #selector(suspend), name: name, object: nil)
        }
        for name in [NSWorkspace.didWakeNotification, NSWorkspace.sessionDidBecomeActiveNotification] {
            center.addObserver(self, selector: #selector(resume), name: name, object: nil)
        }
    }

    private func render() {
        let remaining = deadline.map { ContinuousClock.now.duration(to: $0).components }
        let seconds = remaining.map { max(0, Int($0.seconds) + ($0.attoseconds > 0 ? 1 : 0)) } ?? 0
        let open = seconds > 0
        let title = open ? "BW \((seconds + 59) / 60) min" : "BW"
        let hint = errorText ?? (starting ? "Unlocking…" :
            (open ? "Locks in \((seconds + 59) / 60) min" : "Unlock Bitwarden for one hour"))
        if let button = item.button {
            button.title = title
            button.image = NSImage(systemSymbolName: open ? "lock.open" : "lock", accessibilityDescription: nil)
            button.toolTip = hint
            button.setAccessibilityLabel("\(title). \(hint)")
        }
    }

    @objc private func tick(_ timer: Timer) {
        if let deadline, deadline <= .now {
            self.deadline = nil
            refresh()
        }
        render()
    }

    @objc private func refresh(_ timer: Timer? = nil) {
        guard poll == nil else { return }
        let requested = ContinuousClock.now
        poll = Task { [client] in
            let result = await Task.detached { Result { try client.status() } }.value
            guard !Task.isCancelled else { return }
            poll = nil
            switch result {
            case .success(let seconds):
                deadline = seconds.map { requested.advanced(by: .seconds($0)) }
            case .failure:
                deadline = nil
            }
            render()
        }
    }

    @objc private func suspend(_ note: Notification) {
        generation += 1
        closePrompt()
        poll?.cancel()
        poll = nil
        deadline = nil
        render()
    }

    @objc private func resume(_ note: Notification) {
        suspend(note)
        refresh()
    }

    @objc private func clicked() {
        if let panel {
            NSApp.activate(ignoringOtherApps: true)
            panel.makeKeyAndOrderFront(nil)
            return
        }
        guard !preparing, !starting else { return }
        preparing = true
        let current = generation
        Task { [client] in
            defer { preparing = false }
            do {
                let (lock, seconds) = try await Task.detached {
                    let lock = try AuthLock(home: client.home)
                    return (lock, try client.status())
                }.value
                guard current == generation else { return }
                if let seconds {
                    deadline = .now.advanced(by: .seconds(seconds))
                    render()
                    showInfo(errorText ?? "Locks in \((seconds + 59) / 60) min")
                } else {
                    errorText = nil
                    deadline = nil
                    render()
                    prompt(holding: lock)
                }
            } catch {
                if current == generation { showError(error) }
            }
        }
    }

    private func showInfo(_ text: String) {
        guard let button = item.button else { return }
        let menu = NSMenu()
        menu.addItem(withTitle: text, action: nil, keyEquivalent: "")
        menu.popUp(positioning: nil, at: NSPoint(x: 0, y: button.bounds.minY), in: button)
    }

    private func showError(_ error: Error) {
        let message = (error as? WindowError ?? .unavailable).rawValue
        errorText = message
        render()
        showInfo(message)
    }

    private func prompt(holding lock: AuthLock) {
        let panel = NSPanel(contentRect: NSRect(x: 0, y: 0, width: 320, height: 100),
                            styleMask: [.titled, .closable], backing: .buffered, defer: false)
        panel.title = "Unlock Bitwarden for one hour"
        panel.isReleasedWhenClosed = false
        panel.isRestorable = false
        panel.delegate = self
        let field = NSSecureTextField(frame: NSRect(x: 16, y: 58, width: 288, height: 24))
        field.placeholderString = "Master password"
        field.setAccessibilityLabel("Bitwarden master password")
        let unlock = NSButton(title: "Unlock", target: self, action: #selector(submit))
        let cancel = NSButton(title: "Cancel", target: self, action: #selector(closePrompt))
        unlock.keyEquivalent = "\r"
        cancel.keyEquivalent = "\u{1b}"
        unlock.frame = NSRect(x: 220, y: 12, width: 88, height: 32)
        cancel.frame = NSRect(x: 130, y: 12, width: 88, height: 32)
        field.target = self
        field.action = #selector(submit)
        for control in [field, cancel, unlock] as [NSView] { panel.contentView?.addSubview(control) }
        self.authLock = lock
        self.field = field
        self.panel = panel
        panel.initialFirstResponder = field
        panel.center()
        NSApp.activate(ignoringOtherApps: true)
        panel.makeKeyAndOrderFront(nil)
    }

    @objc private func closePrompt() { panel?.close() }

    func windowWillClose(_ notification: Notification) {
        field?.abortEditing()
        field?.stringValue = ""
        field = nil
        panel = nil
        authLock = nil
    }

    @objc private func submit() {
        guard !starting, let field, let lock = authLock else { return }
        let password = Data(field.stringValue.utf8)
        guard !password.isEmpty, !password.contains(10), !password.contains(13) else { NSSound.beep(); return }
        starting = true
        closePrompt()
        render()
        let current = generation
        let operation = Task.detached { [client] in try client.unlock(password: password, holding: lock) }
        Task {
            let result = await operation.result
            starting = false
            poll?.cancel()
            poll = nil
            refresh()
            if case .failure(let error) = result, current == generation { showError(error) }
        }
    }
}

var coreLimit = rlimit(rlim_cur: 0, rlim_max: 0)
guard setrlimit(RLIMIT_CORE, &coreLimit) == 0 else { exit(1) }
signal(SIGPIPE, SIG_IGN)
MainActor.assumeIsolated {
    let app = NSApplication.shared
    let delegate = MenuApp()
    app.delegate = delegate
    withExtendedLifetime(delegate) { app.run() }
}
