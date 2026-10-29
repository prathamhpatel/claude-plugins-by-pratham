// Screen flash for Voice Claude: dims every display, pulses twice, then fades back.
// Usage: voice-claude-flash [done|ask]  (orange: Claude finished; blue: Claude is waiting on you)
import AppKit

let dimLevel: CGFloat = 0.55
let pulseLevel: CGFloat = 0.45
let isAsking = CommandLine.arguments.dropFirst().first == "ask"
let pulseColor = isAsking
    ? NSColor(srgbRed: 0.29, green: 0.56, blue: 0.95, alpha: 1)  // blue
    : NSColor(srgbRed: 0.85, green: 0.47, blue: 0.34, alpha: 1)  // Claude orange

func overlay(on screen: NSScreen, color: NSColor) -> NSWindow {
    let window = NSWindow(contentRect: screen.frame, styleMask: .borderless, backing: .buffered, defer: false)
    window.backgroundColor = color
    window.isOpaque = false
    window.hasShadow = false
    window.alphaValue = 0
    window.level = .screenSaver
    window.ignoresMouseEvents = true
    window.collectionBehavior = [.canJoinAllSpaces, .fullScreenAuxiliary, .stationary, .ignoresCycle]
    window.setFrame(screen.frame, display: false)
    window.orderFrontRegardless()
    return window
}

struct Step {
    let windows: [NSWindow]
    let alpha: CGFloat
    let duration: TimeInterval
    var pause: TimeInterval = 0
}

func run(_ steps: ArraySlice<Step>) {
    guard let step = steps.first else {
        NSApp.terminate(nil)
        return
    }
    NSAnimationContext.runAnimationGroup({ context in
        context.duration = step.duration
        context.timingFunction = CAMediaTimingFunction(name: .easeInEaseOut)
        step.windows.forEach { $0.animator().alphaValue = step.alpha }
    }, completionHandler: {
        DispatchQueue.main.asyncAfter(deadline: .now() + step.pause) { run(steps.dropFirst()) }
    })
}

let app = NSApplication.shared
app.setActivationPolicy(.accessory)

let dim = NSScreen.screens.map { overlay(on: $0, color: .black) }
let pulse = NSScreen.screens.map { overlay(on: $0, color: pulseColor) }

let steps = [
    Step(windows: dim, alpha: dimLevel, duration: 0.4, pause: 0.15),
    Step(windows: pulse, alpha: pulseLevel, duration: 0.15),
    Step(windows: pulse, alpha: 0, duration: 0.3, pause: 0.1),
    Step(windows: pulse, alpha: pulseLevel, duration: 0.15),
    Step(windows: pulse, alpha: 0, duration: 0.3, pause: 0.2),
    Step(windows: dim, alpha: 0, duration: 0.5),
]
DispatchQueue.main.async { run(steps[...]) }
DispatchQueue.main.asyncAfter(deadline: .now() + 5) { exit(0) }  // never leave the screen dimmed
app.run()
