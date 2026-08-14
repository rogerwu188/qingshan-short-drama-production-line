import Foundation
import AppKit

if CommandLine.arguments.count < 4 {
    fputs("usage: make_contact_sheet.swift <input-dir> <output-path> <columns>\n", stderr)
    exit(2)
}

let inputDir = URL(fileURLWithPath: CommandLine.arguments[1], isDirectory: true)
let outputURL = URL(fileURLWithPath: CommandLine.arguments[2])
let columns = max(1, Int(CommandLine.arguments[3]) ?? 3)
let thumbWidth = 240
let labelHeight = 28
let gap = 12

let files = try FileManager.default.contentsOfDirectory(at: inputDir, includingPropertiesForKeys: nil)
    .filter { ["png", "jpg", "jpeg"].contains($0.pathExtension.lowercased()) }
    .sorted { $0.lastPathComponent < $1.lastPathComponent }

guard !files.isEmpty else {
    fputs("no images found\n", stderr)
    exit(1)
}

struct Tile {
    let file: URL
    let image: NSImage
    let size: NSSize
}

let tiles: [Tile] = files.compactMap { file in
    guard let image = NSImage(contentsOf: file), let rep = image.representations.first else { return nil }
    let original = NSSize(width: rep.pixelsWide, height: rep.pixelsHigh)
    let scale = CGFloat(thumbWidth) / max(1, original.width)
    let size = NSSize(width: CGFloat(thumbWidth), height: original.height * scale)
    return Tile(file: file, image: image, size: size)
}

let rows = Int(ceil(Double(tiles.count) / Double(columns)))
let cellHeight = Int(tiles.map { $0.size.height }.max() ?? 180) + labelHeight
let canvasWidth = columns * thumbWidth + (columns + 1) * gap
let canvasHeight = rows * cellHeight + (rows + 1) * gap
let canvas = NSImage(size: NSSize(width: canvasWidth, height: canvasHeight))

canvas.lockFocus()
NSColor.black.setFill()
NSRect(x: 0, y: 0, width: canvasWidth, height: canvasHeight).fill()

let attrs: [NSAttributedString.Key: Any] = [
    .font: NSFont.boldSystemFont(ofSize: 13),
    .foregroundColor: NSColor.white
]

for (idx, tile) in tiles.enumerated() {
    let row = idx / columns
    let col = idx % columns
    let x = gap + col * (thumbWidth + gap)
    let yTop = gap + row * (cellHeight + gap)
    let y = canvasHeight - yTop - Int(tile.size.height) - labelHeight
    let rect = NSRect(x: x, y: y + labelHeight, width: Int(tile.size.width), height: Int(tile.size.height))
    tile.image.draw(in: rect)
    let label = String(format: "%02d  %@", idx + 1, tile.file.deletingPathExtension().lastPathComponent)
    label.draw(in: NSRect(x: x, y: y, width: thumbWidth, height: labelHeight), withAttributes: attrs)
}

canvas.unlockFocus()

guard let tiff = canvas.tiffRepresentation,
      let bitmap = NSBitmapImageRep(data: tiff),
      let png = bitmap.representation(using: .png, properties: [:]) else {
    fputs("failed to encode contact sheet\n", stderr)
    exit(1)
}

try png.write(to: outputURL)
print(outputURL.path)
