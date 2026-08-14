import Foundation
import AVFoundation
import AppKit
import CoreImage
import QuartzCore

let base = URL(fileURLWithPath: "/Users/rogerwu/qingshan_short_drama", isDirectory: true)
let openingURL = base.appendingPathComponent("qa_videos/E01_opening_nobgm_title_subs_v2.mp4")
let clipsDir = base.appendingPathComponent("qa_videos/e01_remainder_clips", isDirectory: true)
let framesDir = clipsDir.appendingPathComponent("frames", isDirectory: true)
let outDir = base.appendingPathComponent("qa_videos/final_e01", isDirectory: true)
try FileManager.default.createDirectory(at: outDir, withIntermediateDirectories: true)

let renderSize = CGSize(width: 720, height: 1280)
let fps: Int32 = 30
let trimSeconds = 11.0

func cgImage(from url: URL) throws -> CGImage {
    guard let image = NSImage(contentsOf: url) else {
        throw NSError(domain: "AssembleE01", code: 1, userInfo: [NSLocalizedDescriptionKey: "Cannot load image \(url.path)"])
    }
    var rect = CGRect(origin: .zero, size: image.size)
    guard let cg = image.cgImage(forProposedRect: &rect, context: nil, hints: nil) else {
        throw NSError(domain: "AssembleE01", code: 2, userInfo: [NSLocalizedDescriptionKey: "Cannot decode image \(url.path)"])
    }
    return cg
}

func drawImage(_ image: CGImage, into ctx: CGContext, frame: CGRect, zoom: CGFloat, darken: CGFloat = 0.0) {
    ctx.setFillColor(NSColor.black.cgColor)
    ctx.fill(frame)
    let imageSize = CGSize(width: image.width, height: image.height)
    let scale = max(frame.width / imageSize.width, frame.height / imageSize.height) * zoom
    let drawSize = CGSize(width: imageSize.width * scale, height: imageSize.height * scale)
    let drawRect = CGRect(
        x: frame.midX - drawSize.width / 2,
        y: frame.midY - drawSize.height / 2,
        width: drawSize.width,
        height: drawSize.height
    )
    ctx.draw(image, in: drawRect)
    if darken > 0 {
        ctx.setFillColor(NSColor(calibratedWhite: 0, alpha: darken).cgColor)
        ctx.fill(frame)
    }
}

func makeStillVideo(imageURL: URL, outputURL: URL, duration: Double, startZoom: CGFloat, endZoom: CGFloat, darken: CGFloat = 0.0) throws {
    try? FileManager.default.removeItem(at: outputURL)
    let image = try cgImage(from: imageURL)
    let writer = try AVAssetWriter(outputURL: outputURL, fileType: .mp4)
    let settings: [String: Any] = [
        AVVideoCodecKey: AVVideoCodecType.h264,
        AVVideoWidthKey: Int(renderSize.width),
        AVVideoHeightKey: Int(renderSize.height),
        AVVideoCompressionPropertiesKey: [
            AVVideoAverageBitRateKey: 5_000_000,
            AVVideoProfileLevelKey: AVVideoProfileLevelH264HighAutoLevel
        ]
    ]
    let input = AVAssetWriterInput(mediaType: .video, outputSettings: settings)
    input.expectsMediaDataInRealTime = false
    let attrs: [String: Any] = [
        kCVPixelBufferPixelFormatTypeKey as String: Int(kCVPixelFormatType_32ARGB),
        kCVPixelBufferWidthKey as String: Int(renderSize.width),
        kCVPixelBufferHeightKey as String: Int(renderSize.height)
    ]
    let adaptor = AVAssetWriterInputPixelBufferAdaptor(assetWriterInput: input, sourcePixelBufferAttributes: attrs)
    guard writer.canAdd(input) else { throw NSError(domain: "AssembleE01", code: 3) }
    writer.add(input)
    writer.startWriting()
    writer.startSession(atSourceTime: .zero)

    let totalFrames = Int(duration * Double(fps))
    let frameRect = CGRect(origin: .zero, size: renderSize)
    for frameIndex in 0..<totalFrames {
        while !input.isReadyForMoreMediaData { usleep(10_000) }
        var buffer: CVPixelBuffer?
        CVPixelBufferPoolCreatePixelBuffer(nil, adaptor.pixelBufferPool!, &buffer)
        guard let px = buffer else { continue }
        CVPixelBufferLockBaseAddress(px, [])
        let data = CVPixelBufferGetBaseAddress(px)!
        let bytesPerRow = CVPixelBufferGetBytesPerRow(px)
        let colorSpace = CGColorSpaceCreateDeviceRGB()
        guard let ctx = CGContext(
            data: data,
            width: Int(renderSize.width),
            height: Int(renderSize.height),
            bitsPerComponent: 8,
            bytesPerRow: bytesPerRow,
            space: colorSpace,
            bitmapInfo: CGImageAlphaInfo.noneSkipFirst.rawValue
        ) else {
            CVPixelBufferUnlockBaseAddress(px, [])
            continue
        }
        ctx.interpolationQuality = .high
        let progress = CGFloat(frameIndex) / CGFloat(max(totalFrames - 1, 1))
        let zoom = startZoom + (endZoom - startZoom) * progress
        drawImage(image, into: ctx, frame: frameRect, zoom: zoom, darken: darken)
        CVPixelBufferUnlockBaseAddress(px, [])
        let time = CMTime(value: CMTimeValue(frameIndex), timescale: fps)
        adaptor.append(px, withPresentationTime: time)
    }
    input.markAsFinished()
    let group = DispatchGroup()
    group.enter()
    writer.finishWriting { group.leave() }
    group.wait()
    if writer.status != .completed {
        throw writer.error ?? NSError(domain: "AssembleE01", code: 4, userInfo: [NSLocalizedDescriptionKey: "Writer failed"])
    }
}

func makeBrandVideo(logoURL: URL, outputURL: URL, duration: Double) throws {
    let tmp = outDir.appendingPathComponent("_brand_frame.png")
    let logo = try cgImage(from: logoURL)
    let rep = NSBitmapImageRep(bitmapDataPlanes: nil, pixelsWide: Int(renderSize.width), pixelsHigh: Int(renderSize.height), bitsPerSample: 8, samplesPerPixel: 4, hasAlpha: true, isPlanar: false, colorSpaceName: .deviceRGB, bytesPerRow: 0, bitsPerPixel: 0)!
    NSGraphicsContext.saveGraphicsState()
    NSGraphicsContext.current = NSGraphicsContext(bitmapImageRep: rep)
    NSColor.black.setFill()
    CGRect(origin: .zero, size: renderSize).fill()
    let logoSize = CGSize(width: 230, height: 230)
    NSGraphicsContext.current?.cgContext.draw(logo, in: CGRect(x: (renderSize.width - logoSize.width) / 2, y: 690, width: logoSize.width, height: logoSize.height))
    let titleAttrs: [NSAttributedString.Key: Any] = [.font: NSFont.boldSystemFont(ofSize: 46), .foregroundColor: NSColor.white, .kern: 2.5]
    let subAttrs: [NSAttributedString.Key: Any] = [.font: NSFont.systemFont(ofSize: 22, weight: .medium), .foregroundColor: NSColor(white: 0.78, alpha: 1.0)]
    let title = "NALU MOTION" as NSString
    let subtitle = "A Nalu Motion Pictures Production" as NSString
    title.draw(at: CGPoint(x: (renderSize.width - title.size(withAttributes: titleAttrs).width) / 2, y: 620), withAttributes: titleAttrs)
    subtitle.draw(at: CGPoint(x: (renderSize.width - subtitle.size(withAttributes: subAttrs).width) / 2, y: 585), withAttributes: subAttrs)
    NSGraphicsContext.restoreGraphicsState()
    try rep.representation(using: .png, properties: [:])!.write(to: tmp)
    try makeStillVideo(imageURL: tmp, outputURL: outputURL, duration: duration, startZoom: 1.0, endZoom: 1.0)
}

func transformFor(track: AVAssetTrack, renderSize: CGSize) -> CGAffineTransform {
    let natural = track.naturalSize
    let preferred = track.preferredTransform
    let transformed = CGRect(origin: .zero, size: natural).applying(preferred)
    let cleanSize = CGSize(width: abs(transformed.width), height: abs(transformed.height))
    let scale = max(renderSize.width / cleanSize.width, renderSize.height / cleanSize.height)
    let scaled = CGSize(width: cleanSize.width * scale, height: cleanSize.height * scale)
    let tx = (renderSize.width - scaled.width) / 2
    let ty = (renderSize.height - scaled.height) / 2
    return preferred
        .concatenating(CGAffineTransform(translationX: -transformed.minX, y: -transformed.minY))
        .concatenating(CGAffineTransform(scaleX: scale, y: scale))
        .concatenating(CGAffineTransform(translationX: tx, y: ty))
}

struct Subtitle {
    let start: Double
    let duration: Double
    let text: String
    let y: CGFloat
    let fontSize: CGFloat
}

func subtitleLayer(_ item: Subtitle) -> CATextLayer {
    let layer = CATextLayer()
    layer.string = item.text
    layer.alignmentMode = .center
    layer.contentsScale = 2
    layer.isWrapped = true
    layer.font = NSFont.boldSystemFont(ofSize: item.fontSize)
    layer.fontSize = item.fontSize
    layer.foregroundColor = NSColor.white.cgColor
    layer.shadowColor = NSColor.black.cgColor
    layer.shadowOpacity = 0.95
    layer.shadowRadius = 5
    layer.shadowOffset = CGSize(width: 0, height: -2)
    layer.frame = CGRect(x: 45, y: item.y, width: renderSize.width - 90, height: 90)
    layer.opacity = 0
    let anim = CAKeyframeAnimation(keyPath: "opacity")
    anim.values = [0, 1, 1, 0]
    anim.keyTimes = [0, 0.08, 0.92, 1]
    anim.beginTime = AVCoreAnimationBeginTimeAtZero + item.start
    anim.duration = item.duration
    anim.isRemovedOnCompletion = false
    anim.fillMode = .both
    layer.add(anim, forKey: "opacity")
    return layer
}

let shot08Replacement = outDir.appendingPathComponent("shot_08_replacement_no_glowing_eyes.mp4")
let shot10Replacement = outDir.appendingPathComponent("shot_10_replacement_normal_eyes.mp4")
let brandURL = outDir.appendingPathComponent("nalu_motion_end_card.mp4")
try makeStillVideo(
    imageURL: framesDir.appendingPathComponent("shot_08_t00_5.png"),
    outputURL: shot08Replacement,
    duration: trimSeconds,
    startZoom: 1.00,
    endZoom: 1.08,
    darken: 0.05
)
try makeStillVideo(
    imageURL: framesDir.appendingPathComponent("shot_10_t00_5.png"),
    outputURL: shot10Replacement,
    duration: trimSeconds,
    startZoom: 1.00,
    endZoom: 1.10,
    darken: 0.04
)
try makeBrandVideo(
    logoURL: base.appendingPathComponent("libraries/brand/nalu_motion_cat_logo_v1.png"),
    outputURL: brandURL,
    duration: 2.0
)

let composition = AVMutableComposition()
let videoComposition = AVMutableVideoComposition()
videoComposition.renderSize = renderSize
videoComposition.frameDuration = CMTime(value: 1, timescale: fps)

var instructions: [AVMutableVideoCompositionInstruction] = []
var current = CMTime.zero
var subtitles: [Subtitle] = []
let openingAsset = AVURLAsset(url: openingURL)
let openingDuration = openingAsset.duration

func addAsset(_ url: URL, duration seconds: Double? = nil) throws {
    let asset = AVURLAsset(url: url)
    guard let sourceVideo = asset.tracks(withMediaType: .video).first else {
        throw NSError(domain: "AssembleE01", code: 5, userInfo: [NSLocalizedDescriptionKey: "No video track: \(url.path)"])
    }
    let useDuration = seconds.map { CMTime(seconds: min($0, CMTimeGetSeconds(asset.duration)), preferredTimescale: 600) } ?? asset.duration
    let range = CMTimeRange(start: .zero, duration: useDuration)
    let compVideo = composition.addMutableTrack(withMediaType: .video, preferredTrackID: kCMPersistentTrackID_Invalid)!
    try compVideo.insertTimeRange(range, of: sourceVideo, at: current)
    let layer = AVMutableVideoCompositionLayerInstruction(assetTrack: compVideo)
    layer.setTransform(transformFor(track: sourceVideo, renderSize: renderSize), at: current)
    let instruction = AVMutableVideoCompositionInstruction()
    instruction.timeRange = CMTimeRange(start: current, duration: useDuration)
    instruction.layerInstructions = [layer]
    instructions.append(instruction)

    if let sourceAudio = asset.tracks(withMediaType: .audio).first {
        let compAudio = composition.addMutableTrack(withMediaType: .audio, preferredTrackID: kCMPersistentTrackID_Invalid)!
        try? compAudio.insertTimeRange(range, of: sourceAudio, at: current)
    }
    current = current + useDuration
}

try addAsset(openingURL)
let t0 = CMTimeGetSeconds(openingDuration)
let lines = [
    ("六楼，到了。别乱看。", 1.0, 3.4),
    ("铁门后面，一百张病床排得像棺材。", 12.0, 4.2),
    ("陈迹：不用换病号服吗？", 23.0, 3.4),
    ("护士：进了六楼，就没人问这个。", 34.0, 3.8),
    ("黑暗里，所有病人同时坐了起来。", 45.0, 4.0),
    ("老人：归零……你终于来了。", 56.0, 3.6),
    ("陈迹：你认识我？", 67.0, 2.8),
    ("老人：有人说，你今晚会来。", 78.0, 3.8),
    ("李青鸟：你也要去那个世界了。", 89.0, 3.8),
    ("李青鸟：北俱芦洲的人，会负责偷渡。", 99.0, 4.4),
    ("陈迹：怎么会呢？他们可是我的亲人。", 104.2, 4.6),
    ("可他，真的是被骗进来的吗？", 109.0, 4.0)
]
for (text, offset, dur) in lines {
    subtitles.append(Subtitle(start: t0 + offset, duration: dur, text: text, y: 118, fontSize: 36))
}

for i in 1...10 {
    let url: URL
    if i == 8 {
        url = shot08Replacement
    } else if i == 10 {
        url = shot10Replacement
    } else {
        url = clipsDir.appendingPathComponent(String(format: "shot_%02d.mp4", i))
    }
    try addAsset(url, duration: trimSeconds)
}
try addAsset(brandURL)

videoComposition.instructions = instructions

let parent = CALayer()
let videoLayer = CALayer()
parent.frame = CGRect(origin: .zero, size: renderSize)
videoLayer.frame = parent.frame
parent.addSublayer(videoLayer)
for sub in subtitles {
    parent.addSublayer(subtitleLayer(sub))
}
videoComposition.animationTool = AVVideoCompositionCoreAnimationTool(postProcessingAsVideoLayer: videoLayer, in: parent)

let outputURL = outDir.appendingPathComponent("Qingshan_E01_final_v1.mp4")
try? FileManager.default.removeItem(at: outputURL)
guard let export = AVAssetExportSession(asset: composition, presetName: AVAssetExportPresetHighestQuality) else {
    throw NSError(domain: "AssembleE01", code: 6, userInfo: [NSLocalizedDescriptionKey: "Cannot create export session"])
}
export.outputURL = outputURL
export.outputFileType = .mp4
export.videoComposition = videoComposition
export.shouldOptimizeForNetworkUse = true

let group = DispatchGroup()
group.enter()
export.exportAsynchronously { group.leave() }
group.wait()
if export.status != .completed {
    throw export.error ?? NSError(domain: "AssembleE01", code: 7, userInfo: [NSLocalizedDescriptionKey: "Export failed"])
}
print("output=\(outputURL.path)")
print("duration=\(String(format: "%.3f", CMTimeGetSeconds(composition.duration)))")
print("replacements=\(shot08Replacement.path),\(shot10Replacement.path)")
