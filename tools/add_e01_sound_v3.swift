import Foundation
import AVFoundation

let project = URL(fileURLWithPath: "/Users/rogerwu/qingshan_short_drama", isDirectory: true)
let finalDir = project.appendingPathComponent("qa_videos/final_e01", isDirectory: true)
let inputVideo = finalDir.appendingPathComponent("Qingshan_E01_final_v2.mp4")
let outputVideo = finalDir.appendingPathComponent("Qingshan_E01_final_v3_sound.mp4")
let audioDir = finalDir.appendingPathComponent("audio_v3", isDirectory: true)
try FileManager.default.createDirectory(at: audioDir, withIntermediateDirectories: true)

let openingDuration = 75.416
let totalDuration = 187.433
let sampleRate = 44_100.0

struct Cue {
    let id: String
    let at: Double
    let voice: String
    let rate: Int
    let text: String
    let volume: Float
}

let cues: [Cue] = [
    .init(id: "nurse_01", at: 77.0, voice: "Reed (中文（中国大陆）)", rate: 170, text: "六楼，到了。别乱看。", volume: 0.95),
    .init(id: "nurse_02", at: 109.0, voice: "Reed (中文（中国大陆）)", rate: 165, text: "进了六楼，就没人问这个。", volume: 0.92),
    .init(id: "chen_01", at: 98.6, voice: "Eddy (中文（中国大陆）)", rate: 155, text: "不用换病号服吗？", volume: 0.9),
    .init(id: "chen_02", at: 142.5, voice: "Eddy (中文（中国大陆）)", rate: 150, text: "你认识我？", volume: 0.88),
    .init(id: "old_01", at: 132.0, voice: "Grandpa (中文（中国大陆）)", rate: 138, text: "归零……你终于来了。", volume: 1.0),
    .init(id: "old_02", at: 153.5, voice: "Grandpa (中文（中国大陆）)", rate: 136, text: "有人说，你今晚会来。", volume: 1.0),
    .init(id: "li_01", at: 164.8, voice: "Rocko (中文（中国大陆）)", rate: 128, text: "你也要去那个世界了。", volume: 0.94),
    .init(id: "li_02", at: 174.5, voice: "Rocko (中文（中国大陆）)", rate: 126, text: "北俱芦洲的人，会负责偷渡。", volume: 0.96),
    .init(id: "chen_03", at: 180.0, voice: "Eddy (中文（中国大陆）)", rate: 142, text: "怎么会呢？他们可是我的亲人。", volume: 0.9)
]

func run(_ launchPath: String, _ args: [String]) throws {
    let process = Process()
    process.executableURL = URL(fileURLWithPath: launchPath)
    process.arguments = args
    try process.run()
    process.waitUntilExit()
    if process.terminationStatus != 0 {
        throw NSError(domain: "E01Sound", code: Int(process.terminationStatus), userInfo: [NSLocalizedDescriptionKey: "\(launchPath) failed \(args)"])
    }
}

func synthesizeDialogue() throws -> [String: URL] {
    var result: [String: URL] = [:]
    for cue in cues {
        let out = audioDir.appendingPathComponent("\(cue.id).aiff")
        try? FileManager.default.removeItem(at: out)
        try run("/usr/bin/say", ["-v", cue.voice, "-r", "\(cue.rate)", "-o", out.path, cue.text])
        result[cue.id] = out
    }
    return result
}

func writeMonoCAF(name: String, duration: Double, generator: (Int, Double) -> Float) throws -> URL {
    let url = audioDir.appendingPathComponent(name)
    try? FileManager.default.removeItem(at: url)
    let format = AVAudioFormat(commonFormat: .pcmFormatFloat32, sampleRate: sampleRate, channels: 1, interleaved: false)!
    let file = try AVAudioFile(forWriting: url, settings: format.settings)
    let frameCount = AVAudioFrameCount(duration * sampleRate)
    let buffer = AVAudioPCMBuffer(pcmFormat: format, frameCapacity: frameCount)!
    buffer.frameLength = frameCount
    let ptr = buffer.floatChannelData![0]
    for i in 0..<Int(frameCount) {
        ptr[i] = generator(i, Double(i) / sampleRate)
    }
    try file.write(from: buffer)
    return url
}

func envAudio() throws -> URL {
    try writeMonoCAF(name: "hospital_ambience.caf", duration: totalDuration - openingDuration) { i, t in
        let hum = Float(sin(2.0 * Double.pi * 50.0 * t) * 0.012 + sin(2.0 * Double.pi * 100.0 * t) * 0.006)
        var hiss = Float.random(in: -0.006...0.006)
        let pulse = (Int(t * 1.2) % 9 == 0) ? Float(sin(2.0 * Double.pi * 180.0 * t) * 0.006) : 0
        if i % 4410 == 0 { hiss += Float.random(in: -0.02...0.02) }
        return hum + hiss + pulse
    }
}

func tone(name: String, duration: Double, hz: Double, volume: Float, decay: Bool = true) throws -> URL {
    try writeMonoCAF(name: name, duration: duration) { _, t in
        let env = decay ? exp(-3.5 * t / max(duration, 0.01)) : 1.0
        return Float(sin(2.0 * Double.pi * hz * t) * Double(volume) * env)
    }
}

func noiseHit(name: String, duration: Double, volume: Float) throws -> URL {
    try writeMonoCAF(name: name, duration: duration) { _, t in
        let env = exp(-7.0 * t / max(duration, 0.01))
        return Float.random(in: -volume...volume) * Float(env)
    }
}

let dialogueFiles = try synthesizeDialogue()
let ambience = try envAudio()
let doorBang = try noiseHit(name: "door_bang.caf", duration: 0.8, volume: 0.22)
let keypad = try tone(name: "keypad_beep.caf", duration: 0.18, hz: 1600, volume: 0.10)
let strap = try noiseHit(name: "strap_tight.caf", duration: 0.45, volume: 0.13)
let paper = try noiseHit(name: "paper_reveal.caf", duration: 0.65, volume: 0.10)
let lowHit = try tone(name: "low_hit.caf", duration: 1.5, hz: 58, volume: 0.14)
let motif = try tone(name: "qingshan_motif.caf", duration: 4.8, hz: 82, volume: 0.06, decay: false)

let source = AVURLAsset(url: inputVideo)
let composition = AVMutableComposition()

guard let srcVideo = source.tracks(withMediaType: .video).first else {
    throw NSError(domain: "E01Sound", code: 10, userInfo: [NSLocalizedDescriptionKey: "Missing video track"])
}
let vTrack = composition.addMutableTrack(withMediaType: .video, preferredTrackID: kCMPersistentTrackID_Invalid)!
try vTrack.insertTimeRange(CMTimeRange(start: .zero, duration: source.duration), of: srcVideo, at: .zero)
vTrack.preferredTransform = srcVideo.preferredTransform

var mixParams: [AVMutableAudioMixInputParameters] = []

func addAudio(url: URL, at seconds: Double, volume: Float, trimTo duration: Double? = nil) throws {
    let asset = AVURLAsset(url: url)
    guard let audio = asset.tracks(withMediaType: .audio).first else { return }
    let dur = duration.map { CMTime(seconds: min($0, CMTimeGetSeconds(asset.duration)), preferredTimescale: 600) } ?? asset.duration
    let track = composition.addMutableTrack(withMediaType: .audio, preferredTrackID: kCMPersistentTrackID_Invalid)!
    let start = CMTime(seconds: seconds, preferredTimescale: 600)
    try track.insertTimeRange(CMTimeRange(start: .zero, duration: dur), of: audio, at: start)
    let p = AVMutableAudioMixInputParameters(track: track)
    p.setVolume(volume, at: start)
    mixParams.append(p)
}

// Keep original opening audio only. The v2 audio track ends at the opening anyway, but trimming is explicit.
if let openingAudio = source.tracks(withMediaType: .audio).first {
    let openingTrack = composition.addMutableTrack(withMediaType: .audio, preferredTrackID: kCMPersistentTrackID_Invalid)!
    let range = CMTimeRange(start: .zero, duration: CMTime(seconds: openingDuration, preferredTimescale: 600))
    try openingTrack.insertTimeRange(range, of: openingAudio, at: .zero)
    let p = AVMutableAudioMixInputParameters(track: openingTrack)
    p.setVolume(1.0, at: .zero)
    mixParams.append(p)
}

try addAudio(url: ambience, at: openingDuration, volume: 0.38)
for cue in cues {
    if let url = dialogueFiles[cue.id] {
        try addAudio(url: url, at: cue.at, volume: cue.volume)
    }
}

let sfxEvents: [(URL, Double, Float)] = [
    (keypad, 86.2, 0.9),
    (keypad, 86.8, 0.8),
    (doorBang, 89.2, 0.9),
    (lowHit, 91.2, 0.55),
    (strap, 118.5, 0.75),
    (strap, 121.0, 0.65),
    (paper, 151.0, 0.7),
    (lowHit, 163.8, 0.45),
    (motif, 174.2, 0.75),
    (lowHit, 181.8, 0.6)
]
for event in sfxEvents {
    try addAudio(url: event.0, at: event.1, volume: event.2)
}

let audioMix = AVMutableAudioMix()
audioMix.inputParameters = mixParams

try? FileManager.default.removeItem(at: outputVideo)
guard let export = AVAssetExportSession(asset: composition, presetName: AVAssetExportPresetHighestQuality) else {
    throw NSError(domain: "E01Sound", code: 11, userInfo: [NSLocalizedDescriptionKey: "Cannot create export session"])
}
export.outputURL = outputVideo
export.outputFileType = .mp4
export.audioMix = audioMix
export.shouldOptimizeForNetworkUse = true
let group = DispatchGroup()
group.enter()
export.exportAsynchronously { group.leave() }
group.wait()
if export.status != .completed {
    throw export.error ?? NSError(domain: "E01Sound", code: 12, userInfo: [NSLocalizedDescriptionKey: "Export failed"])
}

print("output=\(outputVideo.path)")
print("duration=\(String(format: "%.3f", CMTimeGetSeconds(composition.duration)))")
print("dialogue_files=\(dialogueFiles.count)")
