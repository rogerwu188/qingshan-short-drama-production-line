import Foundation
import AVFoundation
import AppKit

if CommandLine.arguments.count < 4 {
    fputs("usage: extract_specific_frames.swift <input.mp4> <output-dir> <seconds...>\n", stderr)
    exit(2)
}

let inputURL = URL(fileURLWithPath: CommandLine.arguments[1])
let outputDir = URL(fileURLWithPath: CommandLine.arguments[2], isDirectory: true)
let requestedTimes = CommandLine.arguments.dropFirst(3).compactMap(Double.init)
try FileManager.default.createDirectory(at: outputDir, withIntermediateDirectories: true)

let asset = AVURLAsset(url: inputURL)
let duration = try await asset.load(.duration)
let durationSeconds = CMTimeGetSeconds(duration)
let safeDuration = durationSeconds.isFinite && durationSeconds > 0 ? durationSeconds : 1.0
let generator = AVAssetImageGenerator(asset: asset)
generator.appliesPreferredTrackTransform = true
generator.requestedTimeToleranceBefore = CMTime(seconds: 0.25, preferredTimescale: 600)
generator.requestedTimeToleranceAfter = CMTime(seconds: 0.25, preferredTimescale: 600)

func savePNG(_ image: CGImage, to url: URL) throws {
    let bitmap = NSBitmapImageRep(cgImage: image)
    guard let data = bitmap.representation(using: .png, properties: [:]) else {
        throw NSError(domain: "SpecificFrameExtract", code: 1, userInfo: [NSLocalizedDescriptionKey: "PNG encoding failed"])
    }
    try data.write(to: url)
}

var saved = 0
for requested in requestedTimes {
    let seconds = min(max(0.05, requested), max(0.05, safeDuration - 0.2))
    let time = CMTime(seconds: seconds, preferredTimescale: 600)
    do {
        let image = try generator.copyCGImage(at: time, actualTime: nil)
        let outName = String(format: "frame_%06.2f.png", seconds).replacingOccurrences(of: ".", with: "_")
        try savePNG(image, to: outputDir.appendingPathComponent(outName))
        saved += 1
    } catch {
        fputs("failed @ \(seconds): \(error)\n", stderr)
    }
}

print("duration=\(String(format: "%.3f", safeDuration))")
print("saved_frames=\(saved)")
