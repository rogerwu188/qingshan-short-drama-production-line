#!/usr/bin/env node
const { spawnSync } = require("child_process");
const fs = require("fs");
const path = require("path");

const base = "/Users/rogerwu/qingshan_short_drama";
const ffmpeg = path.join(base, ".video_deps/imageio_ffmpeg/binaries/ffmpeg-macos-aarch64-v7.1");
const outDir = path.join(base, "exports/e03_fast_rebuild_local");
const manifestPath = path.join(outDir, "qingshan_E03_fast_rebuild_manifest_20260623.txt");
const bedAudio = path.join(outDir, "qingshan_E03_fast_rebuild_sound_bridge_20260623.m4a");
const videoOnly = path.join(outDir, "qingshan_E03_fast_rebuild_video_only_20260623.mp4");
const voiceDir = path.join(outDir, "voice_clips");
const voiceMix = path.join(outDir, "qingshan_E03_fast_rebuild_voice_sound_mix_20260623.m4a");
const finalPath = path.join(outDir, "qingshan_E03_fast_rebuild_final_titled_subtitled_voice_nalu_20260623.mp4");

fs.mkdirSync(voiceDir, { recursive: true });

const manifest = fs.readFileSync(manifestPath, "utf8").split(/\r?\n/);
const rows = manifest
  .map((line) => {
    const match = line.match(/^(\d\d) start=([\d.]+).*?kind=(\w+).*?subtitle=(.*)$/);
    if (!match) return null;
    return {
      idx: Number(match[1]),
      start: Number(match[2]),
      kind: match[3],
      text: match[4].replace(/\s*\/\s*/g, "，"),
    };
  })
  .filter(Boolean);

const voiceRows = rows.filter((row) => row.kind === "shot" && row.text.trim());
for (const row of voiceRows) {
  const voicePath = path.join(voiceDir, `voice_${String(row.idx).padStart(2, "0")}.aiff`);
  if (!fs.existsSync(voicePath)) {
    const res = spawnSync("say", [
      "-v",
      "Eddy (中文（中国大陆）)",
      "-r",
      "205",
      "-o",
      voicePath,
      row.text,
    ], { stdio: "inherit" });
    if (res.status !== 0) process.exit(res.status ?? 1);
  }
}

const ffArgs = ["-y", "-i", bedAudio];
for (const row of voiceRows) {
  ffArgs.push("-i", path.join(voiceDir, `voice_${String(row.idx).padStart(2, "0")}.aiff`));
}

const parts = [];
parts.push("[0:a]volume=3.2,highpass=f=70,lowpass=f=5200[bed]");
for (let i = 0; i < voiceRows.length; i++) {
  const row = voiceRows[i];
  const delayMs = Math.max(0, Math.round((row.start + 0.62) * 1000));
  parts.push(`[${i + 1}:a]volume=1.18,adelay=${delayMs}|${delayMs}[v${i + 1}]`);
}
const mixInputs = ["[bed]", ...voiceRows.map((_, i) => `[v${i + 1}]`)].join("");
parts.push(`${mixInputs}amix=inputs=${voiceRows.length + 1}:duration=first:normalize=0,dynaudnorm=f=150:g=7:p=0.55,alimiter=limit=0.90[aout]`);

const mixArgs = [
  ...ffArgs,
  "-filter_complex",
  parts.join(";"),
  "-map",
  "[aout]",
  "-c:a",
  "aac",
  "-b:a",
  "192k",
  voiceMix,
];

let res = spawnSync(ffmpeg, mixArgs, { stdio: "inherit" });
if (res.status !== 0) process.exit(res.status ?? 1);

res = spawnSync(ffmpeg, [
  "-y",
  "-i",
  videoOnly,
  "-i",
  voiceMix,
  "-map",
  "0:v",
  "-map",
  "1:a",
  "-c:v",
  "copy",
  "-c:a",
  "copy",
  "-shortest",
  finalPath,
], { stdio: "inherit" });
if (res.status !== 0) process.exit(res.status ?? 1);

console.log(`final=${finalPath}`);
