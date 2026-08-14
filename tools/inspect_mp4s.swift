import Foundation
import AVFoundation

if CommandLine.arguments.count < 2 {
    fputs("usage: inspect_mp4s.swift <input-dir>\n", stderr)
    exit(2)
}

let inputDir = URL(fileURLWithPath: CommandLine.arguments[1], isDirectory: true)
let files = try FileManager.default.contentsOfDirectory(at: inputDir, includingPropertiesForKeys: nil)
    .filter { $0.pathExtension.lowercased() == "mp4" }
    .sorted { $0.lastPathComponent < $1.lastPathComponent }

print("file,duration,width,height,videoTracks,audioTracks")

for file in files {
    let asset = AVURLAsset(url: file)
    let videoTracks = try await asset.loadTracks(withMediaType: .video)
    let audioTracks = try await asset.loadTracks(withMediaType: .audio)
    let duration = try await asset.load(.duration)
    var width = 0
    var height = 0

    if let track = videoTracks.first {
        let naturalSize = try await track.load(.naturalSize)
        let transform = try await track.load(.preferredTransform)
        let transformed = naturalSize.applying(transform)
        width = Int(abs(transformed.width).rounded())
        height = Int(abs(transformed.height).rounded())
    }

    let seconds = CMTimeGetSeconds(duration)
    print("\(file.lastPathComponent),\(String(format: "%.3f", seconds)),\(width),\(height),\(videoTracks.count),\(audioTracks.count)")
}
