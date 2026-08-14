import Foundation
import AVFoundation
import AppKit

let base = URL(fileURLWithPath: "/Users/rogerwu/qingshan_short_drama", isDirectory: true)
let inputURL = base.appendingPathComponent("qa_videos/final_e01/Qingshan_E01_final_v1.mp4")
let tempVideoURL = base.appendingPathComponent("qa_videos/final_e01/Qingshan_E01_final_v2_video_only.mp4")
let outputURL = base.appendingPathComponent("qa_videos/final_e01/Qingshan_E01_final_v2.mp4")
let renderSize = CGSize(width: 720, height: 1280)

struct Subtitle {
    let start: Double
    let end: Double
    let text: String
}

let openingDuration = 75.416
let subtitles: [Subtitle] = [
    .init(start: openingDuration + 1.0, end: openingDuration + 4.4, text: "六楼，到了。别乱看。"),
    .init(start: openingDuration + 12.0, end: openingDuration + 16.2, text: "铁门后面，一百张病床排得像棺材。"),
    .init(start: openingDuration + 23.0, end: openingDuration + 26.4, text: "陈迹：不用换病号服吗？"),
    .init(start: openingDuration + 34.0, end: openingDuration + 37.8, text: "护士：进了六楼，就没人问这个。"),
    .init(start: openingDuration + 45.0, end: openingDuration + 49.0, text: "黑暗里，所有病人同时坐了起来。"),
    .init(start: openingDuration + 56.0, end: openingDuration + 59.6, text: "老人：归零……你终于来了。"),
    .init(start: openingDuration + 67.0, end: openingDuration + 69.8, text: "陈迹：你认识我？"),
    .init(start: openingDuration + 78.0, end: openingDuration + 81.8, text: "老人：有人说，你今晚会来。"),
    .init(start: openingDuration + 89.0, end: openingDuration + 92.8, text: "李青鸟：你也要去那个世界了。"),
    .init(start: openingDuration + 99.0, end: openingDuration + 103.4, text: "李青鸟：北俱芦洲的人，会负责偷渡。"),
    .init(start: openingDuration + 104.2, end: openingDuration + 108.8, text: "陈迹：怎么会呢？他们可是我的亲人。"),
    .init(start: openingDuration + 109.0, end: openingDuration + 113.0, text: "可他，真的是被骗进来的吗？")
]

func activeSubtitle(at seconds: Double) -> Subtitle? {
    subtitles.first { seconds >= $0.start && seconds <= $0.end }
}

func drawSubtitle(_ text: String, in ctx: CGContext) {
    let paragraph = NSMutableParagraphStyle()
    paragraph.alignment = .center
    paragraph.lineBreakMode = .byWordWrapping
    let font = NSFont.boldSystemFont(ofSize: 38)
    let attrs: [NSAttributedString.Key: Any] = [
        .font: font,
        .foregroundColor: NSColor.white,
        .paragraphStyle: paragraph,
        .strokeColor: NSColor.black,
        .strokeWidth: -3.5
    ]
    let textRect = CGRect(x: 50, y: 118, width: 620, height: 110)
    let bg = NSBezierPath(roundedRect: textRect.insetBy(dx: -14, dy: -8), xRadius: 16, yRadius: 16)
    NSColor(calibratedWhite: 0.0, alpha: 0.38).setFill()
    bg.fill()
    (text as NSString).draw(in: textRect, withAttributes: attrs)
}

try? FileManager.default.removeItem(at: tempVideoURL)
try? FileManager.default.removeItem(at: outputURL)

let asset = AVURLAsset(url: inputURL)
guard let srcVideo = asset.tracks(withMediaType: .video).first else {
    throw NSError(domain: "BurnSubs", code: 1, userInfo: [NSLocalizedDescriptionKey: "No video track"])
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
    if let sub = activeSubtitle(at: seconds),
       let baseAddress = CVPixelBufferGetBaseAddress(pixelBuffer) {
        let ctx = CGContext(
            data: baseAddress,
            width: CVPixelBufferGetWidth(pixelBuffer),
            height: CVPixelBufferGetHeight(pixelBuffer),
            bitsPerComponent: 8,
            bytesPerRow: CVPixelBufferGetBytesPerRow(pixelBuffer),
            space: CGColorSpaceCreateDeviceRGB(),
            bitmapInfo: CGImageAlphaInfo.premultipliedFirst.rawValue | CGBitmapInfo.byteOrder32Little.rawValue
        )
        if let ctx {
            NSGraphicsContext.saveGraphicsState()
            NSGraphicsContext.current = NSGraphicsContext(cgContext: ctx, flipped: false)
            drawSubtitle(sub.text, in: ctx)
            NSGraphicsContext.restoreGraphicsState()
        }
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
    throw writer.error ?? NSError(domain: "BurnSubs", code: 2, userInfo: [NSLocalizedDescriptionKey: "Video subtitle burn failed"])
}

let finalComposition = AVMutableComposition()
let videoAsset = AVURLAsset(url: tempVideoURL)
if let videoTrack = videoAsset.tracks(withMediaType: .video).first {
    let compVideo = finalComposition.addMutableTrack(withMediaType: .video, preferredTrackID: kCMPersistentTrackID_Invalid)!
    try compVideo.insertTimeRange(CMTimeRange(start: .zero, duration: videoAsset.duration), of: videoTrack, at: .zero)
}
if let audioTrack = asset.tracks(withMediaType: .audio).first {
    let compAudio = finalComposition.addMutableTrack(withMediaType: .audio, preferredTrackID: kCMPersistentTrackID_Invalid)!
    try compAudio.insertTimeRange(CMTimeRange(start: .zero, duration: min(asset.duration, videoAsset.duration)), of: audioTrack, at: .zero)
}
guard let export = AVAssetExportSession(asset: finalComposition, presetName: AVAssetExportPresetHighestQuality) else {
    throw NSError(domain: "BurnSubs", code: 3, userInfo: [NSLocalizedDescriptionKey: "Cannot create export session"])
}
export.outputURL = outputURL
export.outputFileType = .mp4
export.shouldOptimizeForNetworkUse = true
let exportGroup = DispatchGroup()
exportGroup.enter()
export.exportAsynchronously { exportGroup.leave() }
exportGroup.wait()
if export.status != .completed {
    throw export.error ?? NSError(domain: "BurnSubs", code: 4, userInfo: [NSLocalizedDescriptionKey: "Final mux failed"])
}
print("output=\(outputURL.path)")
print("duration=\(String(format: "%.3f", CMTimeGetSeconds(finalComposition.duration)))")
