import Foundation
import AVFoundation
import AppKit

if CommandLine.arguments.count < 4 {
    fputs("usage: extract_video_timeline_frames.swift <input.mp4> <output-dir> <interval-seconds>\n", stderr)
    exit(2)
}

let inputURL = URL(fileURLWithPath: CommandLine.arguments[1])
let outputDir = URL(fileURLWithPath: CommandLine.arguments[2], isDirectory: true)
let interval = max(1.0, Double(CommandLine.arguments[3]) ?? 10.0)
try FileManager.default.createDirectory(at: outputDir, withIntermediateDirectories: true)

let asset = AVURLAsset(url: inputURL)
guard let track = try await asset.loadTracks(withMediaType: .video).first else {
    fputs("no video track\n", stderr)
    exit(1)
}

let reader = try AVAssetReader(asset: asset)
let output = AVAssetReaderTrackOutput(track: track, outputSettings: [
    kCVPixelBufferPixelFormatTypeKey as String: Int(kCVPixelFormatType_32BGRA)
])
output.alwaysCopiesSampleData = false
reader.add(output)

func savePNG(_ pixelBuffer: CVPixelBuffer, to url: URL) throws {
    let ci = CIImage(cvPixelBuffer: pixelBuffer)
    let context = CIContext(options: [.useSoftwareRenderer: false])
    guard let cg = context.createCGImage(ci, from: ci.extent) else {
        throw NSError(domain: "FrameExtract", code: 1, userInfo: [NSLocalizedDescriptionKey: "failed to create CGImage"])
    }
    let bitmap = NSBitmapImageRep(cgImage: cg)
    guard let data = bitmap.representation(using: .png, properties: [:]) else {
        throw NSError(domain: "FrameExtract", code: 2, userInfo: [NSLocalizedDescriptionKey: "failed to encode PNG"])
    }
    try data.write(to: url)
}

var nextTarget = 0.0
var saved = 0
reader.startReading()

while let sample = output.copyNextSampleBuffer() {
    let seconds = CMTimeGetSeconds(CMSampleBufferGetPresentationTimeStamp(sample))
    guard seconds.isFinite else { continue }
    if seconds + 0.001 >= nextTarget, let px = CMSampleBufferGetImageBuffer(sample) {
        let name = String(format: "frame_%06.2f.png", seconds).replacingOccurrences(of: ".", with: "_")
        try savePNG(px, to: outputDir.appendingPathComponent(name))
        saved += 1
        nextTarget += interval
    }
}

if reader.status == .failed {
    fputs("reader failed: \(String(describing: reader.error))\n", stderr)
    exit(1)
}

print("saved_frames=\(saved)")
