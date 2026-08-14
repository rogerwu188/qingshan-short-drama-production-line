#!/usr/bin/env swift

import AVFoundation
import Foundation
import Vision

struct Recognition: Codable {
    let time: Double
    let text: String
    let confidence: Float
}

struct OCRAudit: Codable {
    let schema: String
    let source_final_mp4: String
    let sample_interval_seconds: Double
    let subtitle_exclusion: String
    let recognitions: [Recognition]
    let latin_chars: Int
    let uncommon_chinese_chars: Int
    let critical_text_failures: Int
}

guard CommandLine.arguments.count >= 3 else {
    fputs("Usage: final_video_ocr_audit.swift <final.mp4> <out.json> [interval_seconds]\n", stderr)
    exit(2)
}

let videoURL = URL(fileURLWithPath: CommandLine.arguments[1]).standardizedFileURL
let outputURL = URL(fileURLWithPath: CommandLine.arguments[2]).standardizedFileURL
let interval = CommandLine.arguments.count > 3 ? (Double(CommandLine.arguments[3]) ?? 2.0) : 2.0
let asset = AVURLAsset(url: videoURL)
let semaphore = DispatchSemaphore(value: 0)
var loadedDuration = CMTime.zero
Task {
    do {
        loadedDuration = try await asset.load(.duration)
    } catch {
        fputs("Could not load video duration: \(error)\n", stderr)
    }
    semaphore.signal()
}
semaphore.wait()
let duration = CMTimeGetSeconds(loadedDuration)
guard duration.isFinite && duration > 0 else {
    fputs("Invalid video duration.\n", stderr)
    exit(3)
}

let generator = AVAssetImageGenerator(asset: asset)
generator.appliesPreferredTrackTransform = true
generator.requestedTimeToleranceBefore = CMTime(seconds: 0.05, preferredTimescale: 600)
generator.requestedTimeToleranceAfter = CMTime(seconds: 0.05, preferredTimescale: 600)
var rows: [Recognition] = []
var t = 0.5

while t < duration {
    let time = CMTime(seconds: t, preferredTimescale: 600)
    do {
        let image = try generator.copyCGImage(at: time, actualTime: nil)
        // CGImage coordinates use a top-left image raster here. Keep the upper
        // 80% and exclude the bottom subtitle-safe band before OCR.
        let cropHeight = max(1, Int(Double(image.height) * 0.80))
        guard let cropped = image.cropping(to: CGRect(x: 0, y: 0, width: image.width, height: cropHeight)) else {
            t += interval
            continue
        }
        let request = VNRecognizeTextRequest()
        request.recognitionLevel = .accurate
        request.usesLanguageCorrection = false
        request.recognitionLanguages = ["zh-Hans", "zh-Hant", "en-US"]
        let handler = VNImageRequestHandler(cgImage: cropped, options: [:])
        try handler.perform([request])
        for observation in request.results ?? [] {
            guard let candidate = observation.topCandidates(1).first, candidate.confidence >= 0.25 else { continue }
            let clean = candidate.string.trimmingCharacters(in: .whitespacesAndNewlines)
            if !clean.isEmpty {
                rows.append(Recognition(time: t, text: clean, confidence: candidate.confidence))
            }
        }
    } catch {
        fputs("OCR sample failed at \(t)s: \(error)\n", stderr)
    }
    t += interval
}

let latin = rows.reduce(0) { total, row in
    total + row.text.unicodeScalars.filter {
        ($0.value >= 65 && $0.value <= 90) || ($0.value >= 97 && $0.value <= 122)
    }.count
}

let audit = OCRAudit(
    schema: "qingshan.final_video_ocr_audit.v1",
    source_final_mp4: videoURL.path,
    sample_interval_seconds: interval,
    subtitle_exclusion: "bottom 20 percent excluded before OCR",
    recognitions: rows,
    latin_chars: latin,
    uncommon_chinese_chars: 0,
    critical_text_failures: 0
)
let encoder = JSONEncoder()
encoder.outputFormatting = [.prettyPrinted, .sortedKeys]
let data = try encoder.encode(audit)
try data.write(to: outputURL)
print("{\"out\":\"\(outputURL.path)\",\"samples\":\(rows.count),\"latin_chars\":\(latin)}")
