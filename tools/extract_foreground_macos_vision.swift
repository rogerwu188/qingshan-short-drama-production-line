#!/usr/bin/env swift

import AppKit
import CoreImage
import CoreImage.CIFilterBuiltins
import Foundation
import Vision

guard CommandLine.arguments.count == 3 else {
    fputs("usage: extract_foreground_macos_vision.swift INPUT OUTPUT\n", stderr)
    exit(64)
}

let inputURL = URL(fileURLWithPath: CommandLine.arguments[1])
let outputURL = URL(fileURLWithPath: CommandLine.arguments[2])
guard let source = CIImage(contentsOf: inputURL) else {
    fputs("cannot decode input image\n", stderr)
    exit(65)
}

if #available(macOS 14.0, *) {
    let request = VNGenerateForegroundInstanceMaskRequest()
    let handler = VNImageRequestHandler(ciImage: source, options: [:])
    do {
        try handler.perform([request])
        guard let observation = request.results?.first else {
            fputs("no foreground observation\n", stderr)
            exit(66)
        }
        let maskBuffer = try observation.generateScaledMaskForImage(
            forInstances: observation.allInstances,
            from: handler
        )
        let mask = CIImage(cvPixelBuffer: maskBuffer)
        let clear = CIImage(color: CIColor.clear).cropped(to: source.extent)
        let blend = CIFilter.blendWithMask()
        blend.inputImage = source
        blend.backgroundImage = clear
        blend.maskImage = mask
        guard let result = blend.outputImage else {
            fputs("mask blend failed\n", stderr)
            exit(67)
        }
        let context = CIContext(options: [.useSoftwareRenderer: false])
        let colorSpace = CGColorSpace(name: CGColorSpace.sRGB)!
        try context.writePNGRepresentation(
            of: result,
            to: outputURL,
            format: .RGBA8,
            colorSpace: colorSpace
        )
    } catch {
        fputs("Vision foreground extraction failed: \(error)\n", stderr)
        exit(68)
    }
} else {
    fputs("macOS 14 or later is required\n", stderr)
    exit(69)
}
