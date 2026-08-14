import AVFoundation
import CoreGraphics
import Foundation
import Vision

struct Sample: Codable {
    let time: Double
    let luma: Double
    let frameDiff: Double
    let text: [String]
    let framePath: String?
}

struct Report: Codable {
    let source: String
    let duration: Double
    let width: Int
    let height: Int
    let nominalFrameRate: Float
    let audioTrackCount: Int
    let sampleInterval: Double
    let sampleCount: Int
    let detectedCutTimes: [Double]
    let estimatedASL: Double
    let meanFrameDiff: Double
    let samples: [Sample]
}

func smallRGB(_ image: CGImage, size: Int = 48) -> [UInt8]? {
    var data = [UInt8](repeating: 0, count: size * size * 4)
    guard let ctx = CGContext(data: &data, width: size, height: size, bitsPerComponent: 8,
                              bytesPerRow: size * 4, space: CGColorSpaceCreateDeviceRGB(),
                              bitmapInfo: CGImageAlphaInfo.premultipliedLast.rawValue) else { return nil }
    ctx.interpolationQuality = .low
    ctx.draw(image, in: CGRect(x: 0, y: 0, width: size, height: size))
    return data
}

func luma(_ rgb: [UInt8]) -> Double {
    var total = 0.0
    var count = 0
    for i in stride(from: 0, to: rgb.count, by: 4) {
        total += 0.2126 * Double(rgb[i]) + 0.7152 * Double(rgb[i + 1]) + 0.0722 * Double(rgb[i + 2])
        count += 1
    }
    return total / Double(max(1, count))
}

func diff(_ a: [UInt8], _ b: [UInt8]) -> Double {
    guard a.count == b.count else { return 0 }
    var total = 0.0
    var count = 0
    for i in stride(from: 0, to: a.count, by: 4) {
        total += abs(Double(a[i]) - Double(b[i]))
        total += abs(Double(a[i + 1]) - Double(b[i + 1]))
        total += abs(Double(a[i + 2]) - Double(b[i + 2]))
        count += 3
    }
    return total / Double(max(1, count))
}

func recognizeText(_ image: CGImage) -> [String] {
    let request = VNRecognizeTextRequest()
    request.recognitionLevel = .fast
    request.recognitionLanguages = ["zh-Hans", "zh-Hant"]
    request.usesLanguageCorrection = true
    do {
        try VNImageRequestHandler(cgImage: image).perform([request])
        return (request.results ?? []).compactMap { $0.topCandidates(1).first?.string }
    } catch {
        return []
    }
}

func saveJPEG(_ image: CGImage, path: URL) {
    guard let destination = CGImageDestinationCreateWithURL(path as CFURL, "public.jpeg" as CFString, 1, nil) else { return }
    CGImageDestinationAddImage(destination, image, [kCGImageDestinationLossyCompressionQuality: 0.82] as CFDictionary)
    CGImageDestinationFinalize(destination)
}

guard CommandLine.arguments.count >= 3 else {
    fputs("usage: swift analyze_reference_video.swift <video> <output-dir>\n", stderr)
    exit(2)
}

let sourceURL = URL(fileURLWithPath: CommandLine.arguments[1])
let outURL = URL(fileURLWithPath: CommandLine.arguments[2])
let framesURL = outURL.appendingPathComponent("frames")
try FileManager.default.createDirectory(at: framesURL, withIntermediateDirectories: true)

let asset = AVURLAsset(url: sourceURL)
let duration = CMTimeGetSeconds(asset.duration)
guard duration.isFinite, duration > 0 else { fatalError("invalid duration") }
let videoTrack = asset.tracks(withMediaType: .video).first
let natural = videoTrack?.naturalSize.applying(videoTrack?.preferredTransform ?? .identity) ?? .zero
let width = Int(abs(natural.width))
let height = Int(abs(natural.height))
let fps = videoTrack?.nominalFrameRate ?? 0
let audioCount = asset.tracks(withMediaType: .audio).count
let interval = max(0.5, duration / 600.0)
let generator = AVAssetImageGenerator(asset: asset)
generator.appliesPreferredTrackTransform = true
generator.requestedTimeToleranceBefore = CMTime(seconds: 0.08, preferredTimescale: 600)
generator.requestedTimeToleranceAfter = CMTime(seconds: 0.08, preferredTimescale: 600)

var samples: [Sample] = []
var previous: [UInt8]? = nil
var cutTimes: [Double] = []
var differences: [Double] = []
var t = 0.0
var index = 0
while t < duration {
    autoreleasepool {
        let time = CMTime(seconds: t, preferredTimescale: 600)
        if let image = try? generator.copyCGImage(at: time, actualTime: nil), let rgb = smallRGB(image) {
            let d = previous.map { diff($0, rgb) } ?? 0
            if d >= 23.0 { cutTimes.append(t) }
            differences.append(d)
            let save = index % max(1, Int(round(2.0 / interval))) == 0
            var framePath: String? = nil
            if save {
                let name = String(format: "t_%07.2f.jpg", t)
                let path = framesURL.appendingPathComponent(name)
                saveJPEG(image, path: path)
                framePath = path.path
            }
            let text = recognizeText(image)
            samples.append(Sample(time: t, luma: luma(rgb), frameDiff: d, text: text, framePath: framePath))
            previous = rgb
        }
    }
    index += 1
    t += interval
}

let meanDiff = differences.reduce(0, +) / Double(max(1, differences.count))
let estimatedASL = duration / Double(max(1, cutTimes.count + 1))
let report = Report(source: sourceURL.path, duration: duration, width: width, height: height,
                    nominalFrameRate: fps, audioTrackCount: audioCount, sampleInterval: interval,
                    sampleCount: samples.count, detectedCutTimes: cutTimes, estimatedASL: estimatedASL,
                    meanFrameDiff: meanDiff, samples: samples)
let json = try JSONEncoder().encode(report)
try json.write(to: outURL.appendingPathComponent("analysis.json"))
print("duration=\(duration) size=\(width)x\(height) fps=\(fps) audioTracks=\(audioCount) samples=\(samples.count) cuts=\(cutTimes.count) ASL=\(estimatedASL) meanDiff=\(meanDiff)")
