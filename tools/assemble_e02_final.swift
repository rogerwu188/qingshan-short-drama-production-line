import Foundation
import AVFoundation
import AppKit
import ImageIO
import UniformTypeIdentifiers

let base = URL(fileURLWithPath: "/Users/rogerwu/qingshan_short_drama", isDirectory: true)
let inputURL = base.appendingPathComponent("exports/qingshan_E02_ad_director_project_uFfeN17_raw_20260621.mp4")
let tempVideoURL = base.appendingPathComponent("exports/qingshan_E02_overlay_video_only_20260621.mp4")
let brandURL = base.appendingPathComponent("exports/qingshan_E02_nalu_end_card_20260621.mp4")
let outputURL = base.appendingPathComponent("exports/qingshan_E02_final_titled_subtitled_nalu_20260621.mp4")
let logoURL = base.appendingPathComponent("libraries/brand/nalu_motion_cat_logo_v1.png")

let renderSize = CGSize(width: 720, height: 1280)
let fps: Int32 = 30

struct Subtitle {
    let start: Double
    let end: Double
    let text: String
}

let subtitles: [Subtitle] = [
    .init(start: 6.2, end: 10.2, text: "雨夜别墅，陈迹刚被送走。"),
    .init(start: 12.0, end: 16.5, text: "王慧玲：晦气，死人照片摆客厅，谁还敢住？"),
    .init(start: 24.0, end: 28.5, text: "陈硕：找房本，明天就过户。"),
    .init(start: 34.0, end: 39.0, text: "王慧玲：他一个精神病，还配住这么好的房子？"),
    .init(start: 50.0, end: 55.5, text: "红本落地，门铃忽然响了。"),
    .init(start: 67.0, end: 72.0, text: "陈硕：这么晚，谁啊？"),
    .init(start: 82.0, end: 87.5, text: "袍哥：陈迹呢？"),
    .init(start: 92.0, end: 99.0, text: "袍哥：他把这房子抵给我了。"),
    .init(start: 108.0, end: 114.5, text: "王慧玲：这房子是我们的！"),
    .init(start: 120.0, end: 126.0, text: "袍哥：产证上，写你名字了吗？"),
    .init(start: 134.0, end: 141.0, text: "陈硕：陈迹是精神病，他签的合同不算！"),
    .init(start: 145.0, end: 152.0, text: "袍哥：你们商量好了，把我当傻子？"),
    .init(start: 158.0, end: 165.0, text: "陈硕：是陈迹！他故意把你引来！"),
    .init(start: 169.0, end: 176.0, text: "袍哥：一个高中生，利用了我？"),
    .init(start: 180.0, end: 187.0, text: "袍哥：有意思。陈迹现在在哪？"),
    .init(start: 188.0, end: 191.8, text: "陈硕：青山精神病院。"),
    .init(start: 191.9, end: 193.2, text: "猎人进笼，还是猎物入局？")
]

func activeSubtitle(at seconds: Double) -> Subtitle? {
    subtitles.first { seconds >= $0.start && seconds <= $0.end }
}

func drawCentered(_ text: String, rect: CGRect, font: NSFont, color: NSColor, stroke: Bool = false) {
    let paragraph = NSMutableParagraphStyle()
    paragraph.alignment = .center
    paragraph.lineBreakMode = .byWordWrapping
    var attrs: [NSAttributedString.Key: Any] = [
        .font: font,
        .foregroundColor: color,
        .paragraphStyle: paragraph
    ]
    if stroke {
        attrs[.strokeColor] = NSColor.black
        attrs[.strokeWidth] = -3.2
    }
    (text as NSString).draw(in: rect, withAttributes: attrs)
}

func drawSubtitle(_ text: String) {
    let textRect = CGRect(x: 52, y: 108, width: 616, height: 132)
    let bg = NSBezierPath(roundedRect: textRect.insetBy(dx: -16, dy: -10), xRadius: 16, yRadius: 16)
    NSColor(calibratedWhite: 0.0, alpha: 0.42).setFill()
    bg.fill()
    drawCentered(text, rect: textRect, font: NSFont.boldSystemFont(ofSize: 37), color: .white, stroke: true)
}

func drawOpeningTitle(seconds: Double) {
    let alpha = min(1.0, max(0.0, seconds / 1.2)) * min(1.0, max(0.0, (6.0 - seconds) / 1.2))
    guard alpha > 0 else { return }
    NSColor(calibratedWhite: 0.0, alpha: 0.28 * alpha).setFill()
    CGRect(x: 0, y: 0, width: renderSize.width, height: renderSize.height).fill()
    let titleColor = NSColor(calibratedWhite: 1.0, alpha: alpha)
    let subColor = NSColor(calibratedWhite: 0.88, alpha: alpha)
    drawCentered("青山", rect: CGRect(x: 60, y: 720, width: 600, height: 90), font: NSFont.boldSystemFont(ofSize: 62), color: titleColor)
    drawCentered("第2集：叔婶夺房，债主上门", rect: CGRect(x: 60, y: 660, width: 600, height: 70), font: NSFont.systemFont(ofSize: 31, weight: .semibold), color: subColor)
    drawCentered("NALU MOTION 出品", rect: CGRect(x: 80, y: 610, width: 560, height: 42), font: NSFont.systemFont(ofSize: 22, weight: .medium), color: subColor)
}

func cgImage(from url: URL) throws -> CGImage {
    guard let image = NSImage(contentsOf: url) else {
        throw NSError(domain: "QSE02", code: 1, userInfo: [NSLocalizedDescriptionKey: "Cannot load image \(url.path)"])
    }
    var rect = CGRect(origin: .zero, size: image.size)
    guard let cg = image.cgImage(forProposedRect: &rect, context: nil, hints: nil) else {
        throw NSError(domain: "QSE02", code: 2, userInfo: [NSLocalizedDescriptionKey: "Cannot decode image \(url.path)"])
    }
    return cg
}

let brandLogo = try cgImage(from: logoURL)

func drawTailBrand(seconds: Double) {
    guard seconds >= 193.25 else { return }
    let alpha = min(1.0, max(0.0, (seconds - 193.25) / 0.6))
    NSColor(calibratedWhite: 0.0, alpha: alpha).setFill()
    CGRect(origin: .zero, size: renderSize).fill()
    let logoRect = CGRect(x: 210, y: 690, width: 300, height: 169)
    NSGraphicsContext.current?.cgContext.draw(brandLogo, in: logoRect)
    let textColor = NSColor(calibratedWhite: 1.0, alpha: alpha)
    let subColor = NSColor(calibratedWhite: 0.78, alpha: alpha)
    drawCentered("NALU MOTION", rect: CGRect(x: 60, y: 610, width: 600, height: 70), font: NSFont.boldSystemFont(ofSize: 48), color: textColor)
    drawCentered("A Nalu Motion Production", rect: CGRect(x: 60, y: 568, width: 600, height: 42), font: NSFont.systemFont(ofSize: 23, weight: .medium), color: subColor)
}

func makeBrandVideo() throws {
    try? FileManager.default.removeItem(at: brandURL)
    let logo = try cgImage(from: logoURL)
    let writer = try AVAssetWriter(outputURL: brandURL, fileType: .mp4)
    let input = AVAssetWriterInput(mediaType: .video, outputSettings: [
        AVVideoCodecKey: AVVideoCodecType.h264,
        AVVideoWidthKey: Int(renderSize.width),
        AVVideoHeightKey: Int(renderSize.height),
        AVVideoCompressionPropertiesKey: [
            AVVideoAverageBitRateKey: 5_000_000,
            AVVideoProfileLevelKey: AVVideoProfileLevelH264HighAutoLevel
        ]
    ])
    let adaptor = AVAssetWriterInputPixelBufferAdaptor(assetWriterInput: input, sourcePixelBufferAttributes: [
        kCVPixelBufferPixelFormatTypeKey as String: Int(kCVPixelFormatType_32ARGB),
        kCVPixelBufferWidthKey as String: Int(renderSize.width),
        kCVPixelBufferHeightKey as String: Int(renderSize.height)
    ])
    writer.add(input)
    writer.startWriting()
    writer.startSession(atSourceTime: .zero)
    let totalFrames = 90
    for frameIndex in 0..<totalFrames {
        while !input.isReadyForMoreMediaData { usleep(5_000) }
        var px: CVPixelBuffer?
        CVPixelBufferPoolCreatePixelBuffer(nil, adaptor.pixelBufferPool!, &px)
        guard let buffer = px else { continue }
        CVPixelBufferLockBaseAddress(buffer, [])
        let ctx = CGContext(
            data: CVPixelBufferGetBaseAddress(buffer),
            width: Int(renderSize.width),
            height: Int(renderSize.height),
            bitsPerComponent: 8,
            bytesPerRow: CVPixelBufferGetBytesPerRow(buffer),
            space: CGColorSpaceCreateDeviceRGB(),
            bitmapInfo: CGImageAlphaInfo.noneSkipFirst.rawValue
        )!
        NSGraphicsContext.saveGraphicsState()
        NSGraphicsContext.current = NSGraphicsContext(cgContext: ctx, flipped: false)
        NSColor.black.setFill()
        CGRect(origin: .zero, size: renderSize).fill()
        let logoRect = CGRect(x: 210, y: 690, width: 300, height: 169)
        ctx.draw(logo, in: logoRect)
        drawCentered("NALU MOTION", rect: CGRect(x: 60, y: 610, width: 600, height: 70), font: NSFont.boldSystemFont(ofSize: 48), color: .white)
        drawCentered("A Nalu Motion Production", rect: CGRect(x: 60, y: 568, width: 600, height: 42), font: NSFont.systemFont(ofSize: 23, weight: .medium), color: NSColor(white: 0.78, alpha: 1))
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
        throw writer.error ?? NSError(domain: "QSE02", code: 3, userInfo: [NSLocalizedDescriptionKey: "Brand writer failed"])
    }
}

try? FileManager.default.removeItem(at: tempVideoURL)
try? FileManager.default.removeItem(at: outputURL)

let asset = AVURLAsset(url: inputURL)
guard let srcVideo = asset.tracks(withMediaType: .video).first else {
    throw NSError(domain: "QSE02", code: 4, userInfo: [NSLocalizedDescriptionKey: "No video track"])
}
let reader = try AVAssetReader(asset: asset)
let readerOutput = AVAssetReaderTrackOutput(track: srcVideo, outputSettings: [
    kCVPixelBufferPixelFormatTypeKey as String: Int(kCVPixelFormatType_32BGRA)
])
readerOutput.alwaysCopiesSampleData = false
reader.add(readerOutput)

let writer = try AVAssetWriter(outputURL: tempVideoURL, fileType: .mp4)
let writerInput = AVAssetWriterInput(mediaType: .video, outputSettings: [
    AVVideoCodecKey: AVVideoCodecType.h264,
    AVVideoWidthKey: Int(renderSize.width),
    AVVideoHeightKey: Int(renderSize.height),
    AVVideoCompressionPropertiesKey: [
        AVVideoAverageBitRateKey: 7_000_000,
        AVVideoProfileLevelKey: AVVideoProfileLevelH264HighAutoLevel
    ]
])
writerInput.expectsMediaDataInRealTime = false
let adaptor = AVAssetWriterInputPixelBufferAdaptor(assetWriterInput: writerInput, sourcePixelBufferAttributes: [
    kCVPixelBufferPixelFormatTypeKey as String: Int(kCVPixelFormatType_32BGRA),
    kCVPixelBufferWidthKey as String: Int(renderSize.width),
    kCVPixelBufferHeightKey as String: Int(renderSize.height)
])
writer.add(writerInput)

reader.startReading()
writer.startWriting()
writer.startSession(atSourceTime: .zero)

while let sample = readerOutput.copyNextSampleBuffer() {
    let pts = CMSampleBufferGetPresentationTimeStamp(sample)
    let seconds = CMTimeGetSeconds(pts)
    guard let pixelBuffer = CMSampleBufferGetImageBuffer(sample) else { continue }
    CVPixelBufferLockBaseAddress(pixelBuffer, [])
    if let baseAddress = CVPixelBufferGetBaseAddress(pixelBuffer),
       let ctx = CGContext(
        data: baseAddress,
        width: CVPixelBufferGetWidth(pixelBuffer),
        height: CVPixelBufferGetHeight(pixelBuffer),
        bitsPerComponent: 8,
        bytesPerRow: CVPixelBufferGetBytesPerRow(pixelBuffer),
        space: CGColorSpaceCreateDeviceRGB(),
        bitmapInfo: CGImageAlphaInfo.premultipliedFirst.rawValue | CGBitmapInfo.byteOrder32Little.rawValue
       ) {
        NSGraphicsContext.saveGraphicsState()
        NSGraphicsContext.current = NSGraphicsContext(cgContext: ctx, flipped: false)
        drawOpeningTitle(seconds: seconds)
        if let sub = activeSubtitle(at: seconds) {
            drawSubtitle(sub.text)
        }
        drawTailBrand(seconds: seconds)
        NSGraphicsContext.restoreGraphicsState()
    }
    CVPixelBufferUnlockBaseAddress(pixelBuffer, [])
    while !writerInput.isReadyForMoreMediaData { usleep(5_000) }
    adaptor.append(pixelBuffer, withPresentationTime: pts)
}

writerInput.markAsFinished()
let writeGroup = DispatchGroup()
writeGroup.enter()
writer.finishWriting { writeGroup.leave() }
writeGroup.wait()
if writer.status != .completed {
    throw writer.error ?? NSError(domain: "QSE02", code: 5, userInfo: [NSLocalizedDescriptionKey: "Overlay video failed"])
}
try makeBrandVideo()

let finalComposition = AVMutableComposition()
var cursor = CMTime.zero
func appendVideo(_ url: URL) throws {
    let clip = AVURLAsset(url: url)
    guard let video = clip.tracks(withMediaType: .video).first else { return }
    let track = finalComposition.addMutableTrack(withMediaType: .video, preferredTrackID: kCMPersistentTrackID_Invalid)!
    try track.insertTimeRange(CMTimeRange(start: .zero, duration: clip.duration), of: video, at: cursor)
    cursor = CMTimeAdd(cursor, clip.duration)
}
try appendVideo(tempVideoURL)
try appendVideo(brandURL)
if let audio = asset.tracks(withMediaType: .audio).first {
    let audioTrack = finalComposition.addMutableTrack(withMediaType: .audio, preferredTrackID: kCMPersistentTrackID_Invalid)!
    try audioTrack.insertTimeRange(CMTimeRange(start: .zero, duration: asset.duration), of: audio, at: .zero)
}

guard let export = AVAssetExportSession(asset: finalComposition, presetName: AVAssetExportPresetHighestQuality) else {
    throw NSError(domain: "QSE02", code: 6, userInfo: [NSLocalizedDescriptionKey: "Cannot create export session"])
}
export.outputURL = outputURL
export.outputFileType = .mp4
export.shouldOptimizeForNetworkUse = true
let exportGroup = DispatchGroup()
exportGroup.enter()
export.exportAsynchronously { exportGroup.leave() }
exportGroup.wait()
if export.status != .completed {
    throw export.error ?? NSError(domain: "QSE02", code: 7, userInfo: [NSLocalizedDescriptionKey: "Final export failed"])
}
print("output=\(outputURL.path)")
print("duration=\(String(format: "%.3f", CMTimeGetSeconds(finalComposition.duration)))")
