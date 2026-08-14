import Foundation
import AVFoundation

if CommandLine.arguments.count < 4 {
    fputs("usage: concat_mp4s.swift <output.mp4> <input1.mp4> <input2.mp4> ...\n", stderr)
    exit(2)
}

let outputURL = URL(fileURLWithPath: CommandLine.arguments[1])
let inputURLs = CommandLine.arguments.dropFirst(2).map { URL(fileURLWithPath: $0) }
try? FileManager.default.removeItem(at: outputURL)

let composition = AVMutableComposition()
var cursor = CMTime.zero

for url in inputURLs {
    let asset = AVURLAsset(url: url)
    let duration = try await asset.load(.duration)
    let range = CMTimeRange(start: .zero, duration: duration)

    if let video = try await asset.loadTracks(withMediaType: .video).first {
        let track = composition.addMutableTrack(withMediaType: .video, preferredTrackID: kCMPersistentTrackID_Invalid)!
        try track.insertTimeRange(range, of: video, at: cursor)
        let transform = try await video.load(.preferredTransform)
        track.preferredTransform = transform
    }

    if let audio = try await asset.loadTracks(withMediaType: .audio).first {
        let track = composition.addMutableTrack(withMediaType: .audio, preferredTrackID: kCMPersistentTrackID_Invalid)!
        try track.insertTimeRange(range, of: audio, at: cursor)
    }

    cursor = cursor + duration
}

guard let export = AVAssetExportSession(asset: composition, presetName: AVAssetExportPresetHighestQuality) else {
    fputs("failed to create export session\n", stderr)
    exit(1)
}
export.outputURL = outputURL
export.outputFileType = .mp4
export.shouldOptimizeForNetworkUse = true

await export.export()

if export.status != .completed {
    fputs("export failed: \(String(describing: export.error))\n", stderr)
    exit(1)
}

print(outputURL.path)
