// Opt-in real clipboard smoke. All original data types stay in memory and are restored.
// swift scripts/test-rex-annotate-clipboard.swift [--self-test]
import AppKit
import Foundation

typealias Clipboard = [[NSPasteboard.PasteboardType: Data]]
let board = NSPasteboard.general
func snapshot() -> Clipboard {
    return (board.pasteboardItems ?? []).map { item in
        var data: [NSPasteboard.PasteboardType: Data] = [:]
        for type in item.types {
            guard let value = item.data(forType: type) else {
                fputs("Cannot preserve clipboard type; aborting\n", stderr)
                exit(1)
            }
            data[type] = value
        }
        return data
    }
}
let saved = snapshot()
let initialChange = board.changeCount
let token = UUID().uuidString
let childStatus: Int32
if CommandLine.arguments.contains("--self-test") {
    // Simulate a failed smoke with malformed output: token is neither a prefix nor a suffix.
    board.clearContents()
    guard board.setString("unexpected \(token) formatter output", forType: .string) else { exit(1) }
    childStatus = 0
} else {
    let child = Process()
    child.environment = ProcessInfo.processInfo.environment.merging(["REX_ANNOTATE_CLIPBOARD_TOKEN": token]) { _, value in value }
    child.executableURL = URL(fileURLWithPath: "/usr/bin/env")
    child.arguments = ["python3", "scripts/test-rex-annotate-live.py", "--overlay", "--clipboard"]
    do { try child.run() } catch {
        fputs("Could not start overlay test: \(error)\n", stderr)
        exit(1)
    }
    child.waitUntilExit()
    childStatus = child.terminationStatus
}
let observedChange = board.changeCount
if observedChange == initialChange {
    exit(childStatus) // The test never touched the clipboard.
}
// Ownership comes from the unique marker, NOT from whether formatting assertions passed.
guard (board.string(forType: .string) ?? "").contains(token) else {
    fputs("Clipboard changed to unidentified content; preserved it without overwriting. Restoration not verified.\n", stderr)
    exit(1)
}
let items = saved.map { data -> NSPasteboardItem in
    let item = NSPasteboardItem()
    for (type, value) in data {
        guard item.setData(value, forType: type) else {
            fputs("Could not reconstruct saved clipboard type\n", stderr)
            exit(1)
        }
    }
    return item
}
guard board.changeCount == observedChange else {
    fputs("Clipboard changed during restoration; preserved the concurrent change\n", stderr)
    exit(1)
}
board.clearContents()
if !items.isEmpty && !board.writeObjects(items) {
    fputs("Clipboard restoration failed\n", stderr)
    exit(1)
}
guard snapshot() == saved else {
    fputs("Restored clipboard data types differ from the original\n", stderr)
    exit(1)
}
print("PASS clipboard: all original data types restored and verified")
exit(childStatus)
