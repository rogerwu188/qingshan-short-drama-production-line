import Foundation
import AVFoundation
import AppKit

let base = URL(fileURLWithPath: "/Users/rogerwu/qingshan_short_drama", isDirectory: true)
let imageDir = base.appendingPathComponent("working_assets/e03_fast_rebuild_storyboard_full", isDirectory: true)
let logoURL = base.appendingPathComponent("libraries/brand/nalu_motion_cat_logo_v1.png")
let outDir = base.appendingPathComponent("exports/e03_fast_rebuild_local", isDirectory: true)
try FileManager.default.createDirectory(at: outDir, withIntermediateDirectories: true)

let videoOnlyURL = outDir.appendingPathComponent("qingshan_E03_fast_rebuild_video_only_20260623.mp4")
let manifestURL = outDir.appendingPathComponent("qingshan_E03_fast_rebuild_manifest_20260623.txt")

let renderSize = CGSize(width: 720, height: 1280)
let fps: Int32 = 30
let crossfade = 0.28

struct Segment {
    let kind: String
    let imageURL: URL?
    let duration: Double
    let subtitle: String
    let bridge: String
}

let shotCaptions: [(String, String)] = [
    ("雨声压过走廊。隔壁床，王龙还在。", "声桥：雨声"),
    ("六楼灯亮，陈硕带人摸上来。", "方向接：由外向内"),
    ("老刘刚锁柜，门被撞开。", "动作接：锁柜到撞门"),
    ("袍哥进门，二刀封住退路。", "空间接：门口到桌边"),
    ("钥匙和门禁卡，被拿走。", "道具接：钥匙"),
    ("录音笔亮了。老刘的谎，开始留证。", "道具接：录音笔"),
    ("假诊断书摔上桌。", "道具接：诊断书"),
    ("老刘慌了：我只是签字！", "对白接：签字"),
    ("陈硕被拖出来，还想抵赖。", "动作接：拖拽"),
    ("签字页翻开，名字对上了。", "道具接：纸页"),
    ("老刘指向柜底：车祸档案在那。", "方向接：手指"),
    ("旧手机、车祸记录，全倒出来。", "道具接：档案"),
    ("陈硕脸色变了。", "反应接"),
    ("门禁卡一刷，六楼开门。", "声桥：滴声"),
    ("铁门后，冷光像刀。", "空间接：门缝"),
    ("陈迹醒了，手里攥着蝉壳。", "道具接：蝉壳"),
    ("李青鸟低声：别回头。", "对白接"),
    ("陈迹只问一句：王龙在哪？", "目标接"),
    ("老人拦住他：你过去会死。", "阻拦接"),
    ("父亲曾把一碗面推给他。", "情感道具接：碗"),
    ("现在，他只剩一个名字。", "信息接"),
    ("王龙。", "重音接"),
    ("金属护身物出鞘。", "声桥：金属轻响"),
    ("隔壁床的呼吸，停了一下。", "悬念接")
]

var segments: [Segment] = [
    Segment(kind: "title", imageURL: nil, duration: 4.6, subtitle: "青山\n第3集：真凶就在六楼", bridge: "片头")
]

for i in 1...24 {
    let n = String(format: "%02d", i)
    let image = imageDir.appendingPathComponent("e03_fast_shot\(n)_storyboard.jpg")
    let (caption, bridge) = shotCaptions[i - 1]
    segments.append(Segment(kind: "shot", imageURL: image, duration: 6.55, subtitle: caption, bridge: bridge))
}

segments.append(Segment(kind: "outro", imageURL: nil, duration: 4.4, subtitle: "下一集：以命复仇", bridge: "片尾"))

let totalDuration = segments.reduce(0.0) { $0 + $1.duration } - Double(segments.count - 1) * crossfade

func cgImage(from url: URL) throws -> CGImage {
    guard let image = NSImage(contentsOf: url) else {
        throw NSError(domain: "QSE03Local", code: 1, userInfo: [NSLocalizedDescriptionKey: "Cannot load \(url.path)"])
    }
    var rect = CGRect(origin: .zero, size: image.size)
    guard let cg = image.cgImage(forProposedRect: &rect, context: nil, hints: nil) else {
        throw NSError(domain: "QSE03Local", code: 2, userInfo: [NSLocalizedDescriptionKey: "Cannot decode \(url.path)"])
    }
    return cg
}

let logo = try cgImage(from: logoURL)
var shotImages: [Int: CGImage] = [:]
for i in 1...24 {
    let url = imageDir.appendingPathComponent("e03_fast_shot\(String(format: "%02d", i))_storyboard.jpg")
    shotImages[i] = try cgImage(from: url)
}

func drawCentered(_ text: String, rect: CGRect, font: NSFont, color: NSColor, kern: CGFloat = 0, lineHeight: CGFloat? = nil) {
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

func drawSubtitle(_ text: String) {
    let rect = CGRect(x: 54, y: 112, width: 612, height: text.count > 15 ? 104 : 78)
    let bg = NSBezierPath(roundedRect: rect.insetBy(dx: -18, dy: -10), xRadius: 18, yRadius: 18)
    NSColor(calibratedWhite: 0.0, alpha: 0.48).setFill()
    bg.fill()
    let paragraph = NSMutableParagraphStyle()
    paragraph.alignment = .center
    paragraph.lineBreakMode = .byWordWrapping
    let attrs: [NSAttributedString.Key: Any] = [
        .font: NSFont.systemFont(ofSize: 35, weight: .heavy),
        .foregroundColor: NSColor.white,
        .paragraphStyle: paragraph,
        .strokeColor: NSColor.black,
        .strokeWidth: -3.0
    ]
    (text as NSString).draw(in: rect, withAttributes: attrs)
}

func fillBlack() {
    NSColor.black.setFill()
    CGRect(origin: .zero, size: renderSize).fill()
}

func drawLogo(_ cg: CGImage, rect: CGRect, alpha: CGFloat = 1) {
    let ctx = NSGraphicsContext.current!.cgContext
    ctx.saveGState()
    ctx.setAlpha(alpha)
    ctx.interpolationQuality = .high
    ctx.draw(cg, in: rect)
    ctx.restoreGState()
}

func drawVignette() {
    let ctx = NSGraphicsContext.current!.cgContext
    ctx.saveGState()
    ctx.setFillColor(NSColor(calibratedWhite: 0.0, alpha: 0.18).cgColor)
    ctx.fill(CGRect(x: 0, y: 0, width: renderSize.width, height: 140))
    ctx.fill(CGRect(x: 0, y: renderSize.height - 190, width: renderSize.width, height: 190))
    ctx.restoreGState()
}

func drawImageFill(_ image: CGImage, progress: Double, shotIndex: Int, alpha: CGFloat) {
    let ctx = NSGraphicsContext.current!.cgContext
    ctx.saveGState()
    ctx.setAlpha(alpha)
    ctx.interpolationQuality = .high

    let iw = CGFloat(image.width)
    let ih = CGFloat(image.height)
    let baseScale = max(renderSize.width / iw, renderSize.height / ih)
    let zoom = CGFloat(1.00 + 0.055 * progress)
    let scaledW = iw * baseScale * zoom
    let scaledH = ih * baseScale * zoom
    let panX = CGFloat((Double((shotIndex % 3) - 1)) * 22.0 * (progress - 0.5))
    let panY = CGFloat((shotIndex % 2 == 0 ? 1.0 : -1.0) * 18.0 * (progress - 0.5))
    let rect = CGRect(
        x: (renderSize.width - scaledW) / 2 + panX,
        y: (renderSize.height - scaledH) / 2 + panY,
        width: scaledW,
        height: scaledH
    )
    ctx.draw(image, in: rect)
    ctx.restoreGState()
    drawVignette()
}

func drawTitle(time: Double, alpha: CGFloat) {
    fillBlack()
    let pulse = 1.0 + 0.015 * sin(time * 1.4)
    drawLogo(logo, rect: CGRect(x: 220 - 2 * pulse, y: 760, width: 280 * pulse, height: 158 * pulse), alpha: alpha)
    drawCentered("青山", rect: CGRect(x: 50, y: 640, width: 620, height: 100), font: NSFont.systemFont(ofSize: 82, weight: .heavy), color: NSColor(white: 1, alpha: alpha), kern: 6)
    drawCentered("第3集：真凶就在六楼", rect: CGRect(x: 50, y: 568, width: 620, height: 64), font: NSFont.systemFont(ofSize: 34, weight: .semibold), color: NSColor(white: 0.90, alpha: alpha))
    drawCentered("一个被判疯的少年，摸到仇人的床边。", rect: CGRect(x: 68, y: 484, width: 584, height: 68), font: NSFont.systemFont(ofSize: 24, weight: .medium), color: NSColor(white: 0.72, alpha: alpha))
    drawCentered("NALU MOTION 出品", rect: CGRect(x: 50, y: 410, width: 620, height: 42), font: NSFont.systemFont(ofSize: 22, weight: .medium), color: NSColor(white: 0.58, alpha: alpha), kern: 1.2)
}

func drawOutro(time: Double, alpha: CGFloat) {
    fillBlack()
    drawLogo(logo, rect: CGRect(x: 195, y: 675, width: 330, height: 186), alpha: alpha)
    drawCentered("NALU MOTION", rect: CGRect(x: 40, y: 590, width: 640, height: 66), font: NSFont.systemFont(ofSize: 48, weight: .heavy), color: NSColor(white: 1, alpha: alpha), kern: 2.2)
    drawCentered("A Nalu Motion Pictures Production", rect: CGRect(x: 40, y: 548, width: 640, height: 38), font: NSFont.systemFont(ofSize: 22, weight: .medium), color: NSColor(white: 0.76, alpha: alpha))
    drawCentered("下一集：以命复仇", rect: CGRect(x: 50, y: 425, width: 620, height: 58), font: NSFont.systemFont(ofSize: 32, weight: .bold), color: NSColor(white: 0.92, alpha: alpha))
}

var starts: [Double] = []
var cursor = 0.0
for (idx, seg) in segments.enumerated() {
    starts.append(cursor)
    cursor += seg.duration
    if idx < segments.count - 1 {
        cursor -= crossfade
    }
}

func segmentIndex(at time: Double) -> Int {
    var idx = 0
    for i in 0..<starts.count where time >= starts[i] {
        idx = i
    }
    return idx
}

try? FileManager.default.removeItem(at: videoOnlyURL)
let writer = try AVAssetWriter(outputURL: videoOnlyURL, fileType: .mp4)
let input = AVAssetWriterInput(mediaType: .video, outputSettings: [
    AVVideoCodecKey: AVVideoCodecType.h264,
    AVVideoWidthKey: Int(renderSize.width),
    AVVideoHeightKey: Int(renderSize.height),
    AVVideoCompressionPropertiesKey: [
        AVVideoAverageBitRateKey: 7_500_000,
        AVVideoProfileLevelKey: AVVideoProfileLevelH264HighAutoLevel
    ]
])
input.expectsMediaDataInRealTime = false
let adaptor = AVAssetWriterInputPixelBufferAdaptor(assetWriterInput: input, sourcePixelBufferAttributes: [
    kCVPixelBufferPixelFormatTypeKey as String: Int(kCVPixelFormatType_32BGRA),
    kCVPixelBufferWidthKey as String: Int(renderSize.width),
    kCVPixelBufferHeightKey as String: Int(renderSize.height)
])
guard writer.canAdd(input) else { throw NSError(domain: "QSE03Local", code: 3) }
writer.add(input)
writer.startWriting()
writer.startSession(atSourceTime: .zero)

let totalFrames = Int(ceil(totalDuration * Double(fps)))

for frameIndex in 0..<totalFrames {
    while !input.isReadyForMoreMediaData { usleep(5_000) }
    let t = Double(frameIndex) / Double(fps)
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

    let idx = segmentIndex(at: t)
    let seg = segments[idx]
    let localStart = starts[idx]
    let localT = max(0, t - localStart)
    let currentAlpha = idx > 0 && localT < crossfade ? CGFloat(localT / crossfade) : 1.0

    if idx > 0 && localT < crossfade {
        let prev = segments[idx - 1]
        let prevLocal = segments[idx - 1].duration - crossfade + localT
        if prev.kind == "shot", let image = shotImages[idx - 1] {
            drawImageFill(image, progress: min(1, max(0, prevLocal / prev.duration)), shotIndex: idx - 1, alpha: 1.0)
        } else if prev.kind == "title" {
            drawTitle(time: prevLocal, alpha: 1.0)
        } else {
            drawOutro(time: prevLocal, alpha: 1.0)
        }
    }

    if seg.kind == "title" {
        let alpha = CGFloat(min(1, max(0, localT / 0.55)) * min(1, max(0, (seg.duration - localT) / 0.55)))
        drawTitle(time: localT, alpha: alpha)
    } else if seg.kind == "outro" {
        let alpha = CGFloat(min(1, max(0, localT / 0.55)))
        drawOutro(time: localT, alpha: alpha)
    } else {
        let shotIndex = idx
        if let image = shotImages[shotIndex] {
            drawImageFill(image, progress: min(1, max(0, localT / seg.duration)), shotIndex: shotIndex, alpha: currentAlpha)
            drawSubtitle(seg.subtitle)
            drawCentered("青山 EP03", rect: CGRect(x: 34, y: 1190, width: 160, height: 30), font: NSFont.systemFont(ofSize: 18, weight: .semibold), color: NSColor(white: 0.92, alpha: 0.82))
        }
    }

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
    throw writer.error ?? NSError(domain: "QSE03Local", code: 4, userInfo: [NSLocalizedDescriptionKey: "Video writer failed"])
}

var manifest = "E03 fast rebuild local video\n"
manifest += "video_only=\(videoOnlyURL.path)\n"
manifest += "duration=\(String(format: "%.3f", totalDuration))\n"
manifest += "fps=\(fps)\n"
manifest += "segments=\(segments.count)\n"
for (idx, seg) in segments.enumerated() {
    manifest += "\(String(format: "%02d", idx)) start=\(String(format: "%.2f", starts[idx])) dur=\(String(format: "%.2f", seg.duration)) kind=\(seg.kind) bridge=\(seg.bridge) subtitle=\(seg.subtitle.replacingOccurrences(of: "\n", with: " / "))\n"
}
try manifest.write(to: manifestURL, atomically: true, encoding: .utf8)

print("video_only=\(videoOnlyURL.path)")
print("manifest=\(manifestURL.path)")
print("duration=\(String(format: "%.3f", totalDuration))")
