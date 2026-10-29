// Global hotkey for Voice Claude: Control + Option + R runs `voice_claude.py read`.
// Usage: voice-claude-hotkey <python3> <voice_claude.py>
import AppKit
import Carbon

let hotKeyCode = UInt32(kVK_ANSI_R)
let hotKeyModifiers = UInt32(controlKey | optionKey)

let args = CommandLine.arguments
guard args.count == 3 else {
    FileHandle.standardError.write("usage: voice-claude-hotkey <python3> <voice_claude.py>\n".data(using: .utf8)!)
    exit(64)
}
let python = args[1]
let script = args[2]

func runRead() {
    let process = Process()
    process.executableURL = URL(fileURLWithPath: python)
    process.arguments = [script, "read"]
    do {
        try process.run()
    } catch {
        FileHandle.standardError.write("failed to start reader: \(error)\n".data(using: .utf8)!)
    }
}

var eventSpec = EventTypeSpec(eventClass: OSType(kEventClassKeyboard), eventKind: UInt32(kEventHotKeyPressed))
InstallEventHandler(GetApplicationEventTarget(), { _, _, _ in
    runRead()
    return noErr
}, 1, &eventSpec, nil, nil)

var hotKeyRef: EventHotKeyRef?
let hotKeyID = EventHotKeyID(signature: OSType(0x5643_4C44), id: 1)  // "VCLD"
let status = RegisterEventHotKey(hotKeyCode, hotKeyModifiers, hotKeyID, GetApplicationEventTarget(), 0, &hotKeyRef)
guard status == noErr else {
    FileHandle.standardError.write("could not register hotkey (status \(status)); is another app using it?\n".data(using: .utf8)!)
    exit(1)
}
FileHandle.standardError.write("Voice Claude hotkey ready: Control+Option+R\n".data(using: .utf8)!)

let app = NSApplication.shared
app.setActivationPolicy(.prohibited)
app.run()
