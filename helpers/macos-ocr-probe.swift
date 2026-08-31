import AppKit
import CoreGraphics
import Foundation
import ImageIO
import Vision

func emit(_ payload: [String: Any]) {
    if let data = try? JSONSerialization.data(withJSONObject: payload, options: [.sortedKeys]),
       let text = String(data: data, encoding: .utf8) {
        print(text)
    }
}

let args = CommandLine.arguments
let expectedApp = args.count > 1 ? args[1] : ""
let maxLines = args.count > 2 ? max(1, min(Int(args[2]) ?? 12, 40)) : 12
let minConfidence = args.count > 3 ? max(0.0, min(Float(args[3]) ?? 0.35, 1.0)) : 0.35
let provider = args.count > 4 ? args[4] : "apple_vision"
let tesseractPath = args.count > 5 ? args[5] : "/opt/homebrew/bin/tesseract"

let activeApp = NSWorkspace.shared.frontmostApplication
let appName = activeApp?.localizedName ?? activeApp?.bundleIdentifier ?? "unknown"
let pid = activeApp?.processIdentifier ?? -1

if !expectedApp.isEmpty && appName != expectedApp {
    emit([
        "status": "skipped",
        "reason": "frontmost app changed",
        "app": appName
    ])
    exit(0)
}

var targetWindowID: CGWindowID?
var windowTitle = ""

if let windows = CGWindowListCopyWindowInfo([.optionOnScreenOnly, .excludeDesktopElements], kCGNullWindowID) as? [[String: Any]] {
    for window in windows {
        let ownerPid = window[kCGWindowOwnerPID as String] as? pid_t ?? -2
        let layer = window[kCGWindowLayer as String] as? Int ?? -1
        if ownerPid == pid && layer == 0 {
            if let number = window[kCGWindowNumber as String] as? UInt32 {
                targetWindowID = CGWindowID(number)
                windowTitle = window[kCGWindowName as String] as? String ?? ""
                break
            }
        }
    }
}

guard let windowID = targetWindowID else {
    emit([
        "status": "empty",
        "reason": "no active window image",
        "app": appName
    ])
    exit(0)
}

let tempURL = FileManager.default.temporaryDirectory
    .appendingPathComponent("digital-twin-ocr-\(UUID().uuidString)")
    .appendingPathExtension("png")
defer {
    try? FileManager.default.removeItem(at: tempURL)
}

let capture = Process()
capture.executableURL = URL(fileURLWithPath: "/usr/sbin/screencapture")
capture.arguments = ["-x", "-l", String(windowID), tempURL.path]

do {
    try capture.run()
    capture.waitUntilExit()
} catch {
    emit([
        "status": "error",
        "reason": error.localizedDescription,
        "app": appName
    ])
    exit(1)
}

guard capture.terminationStatus == 0,
      let imageSource = CGImageSourceCreateWithURL(tempURL as CFURL, nil),
      let image = CGImageSourceCreateImageAtIndex(imageSource, 0, nil) else {
    emit([
        "status": "empty",
        "reason": "window image unavailable; Screen Recording permission may be required",
        "app": appName
    ])
    exit(0)
}

func runTesseract() {
    let ocr = Process()
    ocr.executableURL = URL(fileURLWithPath: tesseractPath)
    ocr.arguments = [tempURL.path, "stdout", "--oem", "1", "--psm", "6", "-l", "eng"]
    let pipe = Pipe()
    ocr.standardOutput = pipe
    ocr.standardError = Pipe()

    do {
        try ocr.run()
        ocr.waitUntilExit()
    } catch {
        emit([
            "status": "error",
            "reason": error.localizedDescription,
            "provider": "tesseract",
            "app": appName
        ])
        exit(1)
    }

    if ocr.terminationStatus != 0 {
        emit([
            "status": "empty",
            "reason": "tesseract returned no readable text",
            "provider": "tesseract",
            "app": appName
        ])
        exit(0)
    }

    let data = pipe.fileHandleForReading.readDataToEndOfFile()
    let output = String(data: data, encoding: .utf8) ?? ""
    let rows = output
        .components(separatedBy: .newlines)
        .map { $0.trimmingCharacters(in: .whitespacesAndNewlines) }
        .filter { !$0.isEmpty }
        .prefix(maxLines)
        .map { ["text": $0, "confidence": 0.0] as [String: Any] }

    emit([
        "status": rows.isEmpty ? "empty" : "captured",
        "provider": "tesseract",
        "source": "tesseract_cli",
        "app": appName,
        "window_title": windowTitle,
        "line_count": rows.count,
        "lines": Array(rows)
    ])
}

if provider == "tesseract" {
    runTesseract()
    exit(0)
}

if #available(macOS 10.15, *) {
    let request = VNRecognizeTextRequest()
    request.recognitionLevel = .accurate
    request.usesLanguageCorrection = true
    if #available(macOS 11.0, *) {
        request.recognitionLanguages = ["en-US"]
    }

    let handler = VNImageRequestHandler(cgImage: image, options: [:])
    do {
        try handler.perform([request])
    } catch {
        emit([
            "status": "error",
            "reason": error.localizedDescription,
            "app": appName
        ])
        exit(1)
    }

    let observations = request.results ?? []
    let rows = observations.compactMap { observation -> [String: Any]? in
        guard let candidate = observation.topCandidates(1).first else { return nil }
        if candidate.confidence < minConfidence { return nil }
        let box = observation.boundingBox
        return [
            "text": candidate.string,
            "confidence": Double(candidate.confidence),
            "box": [
                "x": Double(box.origin.x),
                "y": Double(box.origin.y),
                "width": Double(box.size.width),
                "height": Double(box.size.height)
            ]
        ]
    }
    .sorted { left, right in
        let leftBox = left["box"] as? [String: Double] ?? [:]
        let rightBox = right["box"] as? [String: Double] ?? [:]
        let leftY = leftBox["y"] ?? 0.0
        let rightY = rightBox["y"] ?? 0.0
        if abs(leftY - rightY) > 0.03 {
            return leftY > rightY
        }
        return (leftBox["x"] ?? 0.0) < (rightBox["x"] ?? 0.0)
    }
    .prefix(maxLines)

    emit([
        "status": rows.isEmpty ? "empty" : "captured",
        "provider": "apple_vision",
        "source": "VNRecognizeTextRequest",
        "app": appName,
        "window_title": windowTitle,
        "line_count": rows.count,
        "lines": Array(rows)
    ])
} else {
    emit([
        "status": "unsupported",
        "reason": "VNRecognizeTextRequest requires macOS 10.15 or newer",
        "app": appName
    ])
}
