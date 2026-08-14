import Foundation
import AVFoundation
import AppKit

let base = URL(fileURLWithPath: "/Users/rogerwu/qingshan_short_drama", isDirectory: true)
let workDir = base.appendingPathComponent("exports/e03_fast_rebuild_ad", isDirectory: true)
let rawURL = workDir.appendingPathComponent("qingshan_E03_fast_rebuild_ad_raw_20260623.mp4")
let titleURL = workDir.appendingPathComponent("qingshan_E03_fast_rebuild_title_card_20260623.mov")
let endURL = workDir.appendingPathComponent("qingshan_E03_fast_rebuild_nalu_end_card_20260623.mov")
let outputURL = workDir.appendingPathComponent("qingshan_E03_fast_rebuild_final_titled_subtitled_nalu_20260623.mp4")
let logoURL = base.appendingPathComponent("libraries/brand/nalu_motion_cat_logo_v1.png")

let renderSize = CGSize(width: 720, height: 1280)
let fps: Int32 = 30

func cgImage(from url: URL) throws -> CGImage {
    guard let image = NSImage(contentsOf: url) else {
        throw NSError(domain: "QSE03Package", code: 1, userInfo: [NSLocalizedDescriptionKey: "Cannot load \(url.path)"])
    }
    var rect = CGRect(origin: .zero, size: image.size)
    guard let cg = image.cgImage(forProposedRect: &rect, context: nil, hints: nil) else {
        throw NSError(domain: "QSE03Package", code: 2, userInfo: [NSLocalizedDescriptionKey: "Cannot decode \(url.path)"])
    }
    return cg
}

func drawCentered(_ text: String, in rect: CGRect, font: NSFont, color: NSColor, kern: CGFloat = 0, lineHeight: CGFloat? = nil) {
    let paragraph = NSMutableParagraphStyle()
    paragraph.alignment = .center
    paragraph.lineBreakMode = .byWordWrapping
    if let lineHeight {
        paragraph.minimumLineHeight = lineHeight
        paragraph.maximumLineHeight = lineHeight
    }
    let attrs: [NSAttributedString.Key: Any] = [
        .font: font,
        .foregroundColor: color,
        .paragraphStyle: paragraph,
        .kern: kern
    ]
    (text as NSString).draw(in: rect, withAttributes: attrs)
}

func drawLogo(_ logo: CGImage, in rect: CGRect, alpha: CGFloat = 1) {
    let ctx = NSGraphicsContext.current!.cgContext
    ctx.saveGState()
    ctx.setAlpha(alpha)
    ctx.interpolationQuality = .high
    ctx.draw(logo, in: rect)
    ctx.restoreGState()
}

func makeCardVideo(outputURL: URL, duration: Double, draw: @escaping (Double) throws -> Void) throws {
    try? FileManager.default.removeItem(at: outputURL)
    let writer = try AVAssetWriter(outputURL: outputURL, fileType: .mov)
    let input = AVAssetWriterInput(mediaType: .video, outputSettings: [
        AVVideoCodecKey: AVVideoCodecType.h264,
        AVVideoWidthKey: Int(renderSize.width),
        AVVideoHeightKey: Int(renderSize.height),
        AVVideoCompressionPropertiesKey: [
            AVVideoAverageBitRateKey: 6_000_000,
            AVVideoProfileLevelKey: AVVideoProfileLevelH264HighAutoLevel
        ]
    ])
    input.expectsMediaDataInRealTime = false
    let adaptor = AVAssetWriterInputPixelBufferAdaptor(assetWriterInput: input, sourcePixelBufferAttributes: [
        kCVPixelBufferPixelFormatTypeKey as String: Int(kCVPixelFormatType_32BGRA),
        kCVPixelBufferWidthKey as String: Int(renderSize.width),
        kCVPixelBufferHeightKey as String: Int(renderSize.height)
    ])
    guard writer.canAdd(input) else { throw NSError(domain: "QSE03Package", code: 3) }
    writer.add(input)
    writer.startWriting()
    writer.startSession(atSourceTime: .zero)

    let totalFrames = Int(duration * Double(fps))
    for frameIndex in 0..<totalFrames {
        while !input.isReadyForMoreMediaData { usleep(5_000) }
        var px: CVPixelBuffer?
        CVPixelBufferCreate(
            kCFAllocatorDefault,
            Int(renderSize.width),
            Int(renderSize.height),
            kCVPixelFormatType_32BGRA,
            [
                kCVPixelBufferCGImageCompatibilityKey as String: true,
                kCVPixelBufferCGBitmapContextCompatibilityKey as String: true
            ] as CFDictionary,
            &px
        )
        guard let buffer = px else { continue }
        CVPixelBufferLockBaseAddress(buffer, [])
        let ctx = CGContext(
            data: CVPixelBufferGetBaseAddress(buffer),
            width: Int(renderSize.width),
            height: Int(renderSize.height),
            bitsPerComponent: 8,
            bytesPerRow: CVPixelBufferGetBytesPerRow(buffer),
            space: CGColorSpaceCreateDeviceRGB(),
            bitmapInfo: CGImageAlphaInfo.premultipliedFirst.rawValue | CGBitmapInfo.byteOrder32Little.rawValue
        )!
        NSGraphicsContext.saveGraphicsState()
        NSGraphicsContext.current = NSGraphicsContext(cgContext: ctx, flipped: false)
        try draw(Double(frameIndex) / Double(fps))
        NSGraphicsContext.restoreGraphicsState()
        CVPixelBufferUnlockBaseAddress(buffer, [])
        adaptor.append(buffer, withPresentationTime: CMTime(value: CMTimeValue(frameIndex), timescale: fps))
    }

    input.markAsFinished()
    let group = DispatchGroup()
    group.enter()
    writer.finishWriting { group.leave() }
    group.wait()
    if writer.status != .completed {
        throw writer.error ?? NSError(domain: "QSE03Package", code: 4, userInfo: [NSLocalizedDescriptionKey: "Card writer failed"])
    }
}

let logo = try cgImage(from: logoURL)

try makeCardVideo(outputURL: titleURL, duration: 5.0) { t in
    let alpha = min(1.0, max(0.0, t / 0.9)) * min(1.0, max(0.0, (5.0 - t) / 0.8))
    NSColor.black.setFill()
    CGRect(origin: .zero, size: renderSize).fill()
    drawLogo(logo, in: CGRect(x: 228, y: 765, width: 264, height: 148), alpha: alpha)
    drawCentered("青山", in: CGRect(x: 50, y: 640, width: 620, height: 100), font: NSFont.systemFont(ofSize: 82, weight: .heavy), color: NSColor(white: 1, alpha: alpha), kern: 6)
    drawCentered("第3集：真凶就在六楼", in: CGRect(x: 50, y: 570, width: 620, height: 66), font: NSFont.systemFont(ofSize: 34, weight: .semibold), color: NSColor(white: 0.90, alpha: alpha))
    drawCentered("一个被判疯的少年，摸到仇人的床边。", in: CGRect(x: 68, y: 488, width: 584, height: 68), font: NSFont.systemFont(ofSize: 24, weight: .medium), color: NSColor(white: 0.72, alpha: alpha))
    drawCentered("NALU MOTION 出品", in: CGRect(x: 50, y: 416, width: 620, height: 42), font: NSFont.systemFont(ofSize: 22, weight: .medium), color: NSColor(white: 0.58, alpha: alpha), kern: 1.2)
}

try makeCardVideo(outputURL: endURL, duration: 3.0) { t in
    let alpha = min(1.0, max(0.0, t / 0.6))
    NSColor.black.setFill()
    CGRect(origin: .zero, size: renderSize).fill()
    drawLogo(logo, in: CGRect(x: 205, y: 690, width: 310, height: 174), alpha: alpha)
    drawCentered("NALU MOTION", in: CGRect(x: 60, y: 610, width: 600, height: 70), font: NSFont.boldSystemFont(ofSize: 48), color: NSColor(white: 1, alpha: alpha), kern: 2.5)
    drawCentered("A Nalu Motion Pictures Production", in: CGRect(x: 60, y: 568, width: 600, height: 42), font: NSFont.systemFont(ofSize: 23, weight: .medium), color: NSColor(white: 0.78, alpha: alpha))
}

try? FileManager.default.removeItem(at: outputURL)
let composition = AVMutableComposition()
var cursor = CMTime.zero
let finalVideoTrack = composition.addMutableTrack(withMediaType: .video, preferredTrackID: kCMPersistentTrackID_Invalid)!
let finalAudioTrack = composition.addMutableTrack(withMediaType: .audio, preferredTrackID: kCMPersistentTrackID_Invalid)!

func appendClip(_ url: URL) async throws {
    let asset = AVURLAsset(url: url)
    let duration = try await asset.load(.duration)
    let range = CMTimeRange(start: .zero, duration: duration)
    if let sourceVideo = try await asset.loadTracks(withMediaType: .video).first {
        try finalVideoTrack.insertTimeRange(range, of: sourceVideo, at: cursor)
        finalVideoTrack.preferredTransform = try await sourceVideo.load(.preferredTransform)
    }
    if let sourceAudio = try await asset.loadTracks(withMediaType: .audio).first {
        try finalAudioTrack.insertTimeRange(range, of: sourceAudio, at: cursor)
    }
    cursor = cursor + duration
}

try await appendClip(titleURL)
try await appendClip(rawURL)
try await appendClip(endURL)

guard let export = AVAssetExportSession(asset: composition, presetName: AVAssetExportPresetHighestQuality) else {
    throw NSError(domain: "QSE03Package", code: 5, userInfo: [NSLocalizedDescriptionKey: "Cannot create export session"])
}
export.outputURL = outputURL
export.outputFileType = .mp4
export.shouldOptimizeForNetworkUse = true
let exportGroup = DispatchGroup()
exportGroup.enter()
export.exportAsynchronously { exportGroup.leave() }
exportGroup.wait()

if export.status != .completed {
    throw export.error ?? NSError(domain: "QSE03Package", code: 6, userInfo: [NSLocalizedDescriptionKey: "Final export failed"])
}

print("output=\(outputURL.path)")
print("duration=\(String(format: "%.3f", CMTimeGetSeconds(composition.duration)))")
