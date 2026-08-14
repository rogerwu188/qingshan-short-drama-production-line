import Foundation
import AVFoundation
import AppKit

if CommandLine.arguments.count < 3 {
    fputs("usage: extract_video_frames.swift <input-dir> <output-dir>\n", stderr)
    exit(2)
}

let inputDir = URL(fileURLWithPath: CommandLine.arguments[1], isDirectory: true)
let outputDir = URL(fileURLWithPath: CommandLine.arguments[2], isDirectory: true)
try FileManager.default.createDirectory(at: outputDir, withIntermediateDirectories: true)

let files = try FileManager.default.contentsOfDirectory(at: inputDir, includingPropertiesForKeys: nil)
    .filter { $0.pathExtension.lowercased() == "mp4" && $0.lastPathComponent.hasPrefix("shot_") }
    .sorted { $0.lastPathComponent < $1.lastPathComponent }

let sampleTimes: [Double] = [0.5, 5.0, 10.0]

func savePNG(_ image: CGImage, to url: URL) throws {
    let bitmap = NSBitmapImageRep(cgImage: image)
    guard let data = bitmap.representation(using: .png, properties: [:]) else {
        throw NSError(domain: "FrameExtract", code: 1, userInfo: [NSLocalizedDescriptionKey: "PNG encoding failed"])
    }
    try data.write(to: url)
}

for file in files {
    let asset = AVURLAsset(url: file)
    let generator = AVAssetImageGenerator(asset: asset)
    generator.appliesPreferredTrackTransform = true
    generator.requestedTimeToleranceBefore = .zero
    generator.requestedTimeToleranceAfter = .zero

    let durationSeconds = CMTimeGetSeconds(asset.duration)
    let safeDuration = durationSeconds.isFinite && durationSeconds > 0 ? durationSeconds : 15.0
    print("\(file.lastPathComponent),duration=\(String(format: "%.3f", safeDuration))")

    for t in sampleTimes {
        let clamped = min(t, max(0.1, safeDuration - 0.2))
        let time = CMTime(seconds: clamped, preferredTimescale: 600)
        do {
            let image = try generator.copyCGImage(at: time, actualTime: nil)
            let outName = file.deletingPathExtension().lastPathComponent + "_t" + String(format: "%04.1f", clamped).replacingOccurrences(of: ".", with: "_") + ".png"
            try savePNG(image, to: outputDir.appendingPathComponent(outName))
        } catch {
            fputs("failed \(file.lastPathComponent) @ \(clamped): \(error)\n", stderr)
        }
    }
}
