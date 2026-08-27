import AppKit
import CoreGraphics
import Foundation

let activeApp = NSWorkspace.shared.frontmostApplication
let appName = activeApp?.localizedName ?? activeApp?.bundleIdentifier ?? "unknown"
let pid = activeApp?.processIdentifier ?? -1
var title = ""

if let windows = CGWindowListCopyWindowInfo([.optionOnScreenOnly, .excludeDesktopElements], kCGNullWindowID) as? [[String: Any]] {
    for window in windows {
        let ownerPid = window[kCGWindowOwnerPID as String] as? pid_t ?? -2
        let layer = window[kCGWindowLayer as String] as? Int ?? -1
        if ownerPid == pid && layer == 0 {
            title = window[kCGWindowName as String] as? String ?? ""
            break
        }
    }
}

print("\(appName)\t\(title)")
