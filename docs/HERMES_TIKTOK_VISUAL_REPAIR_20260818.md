# TikTok Visual Pipeline Repair - 2026-08-18

## Scope

This repair hardens the high-quality TikTok path without changing the manual-only publish boundary. It addresses weakly matched footage, cross-platform clip reuse, placeholder covers, incomplete subtitles, and handoff before real artifact validation.

## Root Causes

1. `scene_manifest.json` described background images while the renderer consumed different files under `footage/`. Planned evidence therefore did not prove the rendered source.
2. Footage provenance was incomplete and no fail-closed gate compared source clips across platform packages.
3. The first cover was a frame plus one caption. It had no narrative conflict, payoff hierarchy, or evidence badges.
4. Script quality and actual-video checks were executed after rendering during manual review instead of blocking the render and handoff path.
5. Subtitle resolution evidence was absent from the renderer manifest, while long English narration was truncated to three lines.

## Implemented

- `scripts/visual_asset_gate.py`
  - Requires one provenance record per scene.
  - Requires explicit scene search terms, observed subjects, a match reason, and semantic score `>= 0.72`.
  - Rejects exact SHA-256 reuse and near-duplicate first frames using dHash, both within the video and across sibling platform packages.
- `scripts/cinematic_v11.py`
  - Runs the visual asset gate before TTS or rendering.
  - Uses the actual footage paths as the scene-manifest source of truth.
  - Uses complete four-line subtitles, camera drift, scene progress, concise visual claims, platform-specific grading, and semantic transitions.
  - Writes `cinematic-v11.3` evidence with the embedded asset-gate result.
- `config/viral_cover_policy.json` and `scripts/cover_quality_gate.py`
  - Make topic-specific narrative posters the default for every cover.
  - Reject screenshot-caption placeholders, missing conflict/payoff, missing focal subjects, unsafe text, invalid aspect ratio, or explicitly degraded covers.
- `scripts/deliver_media.py`
  - Uses content hashes for cache identity so a replacement at the same source path cannot resend stale media.
  - Blocks any cover delivery without passing `cover_quality_evidence.json`.

## Mandatory Low-Intelligence-Model Sequence

1. Analyze platform, account lane, selected topic, audience pain, and intended content form.
2. Write the script and run `video_script_gate.py`. Do not render on failure.
3. Build `scene_manifest.json` with the real video path, search terms, observed subjects, source URL, match reason, and semantic score for every scene.
4. Run `visual_asset_gate.py`. Replace only failed scenes; never weaken the threshold or relabel external evidence.
5. Invalidate TTS and render checkpoints whenever narration, footage, renderer version, or manifest changes.
6. Render one final version only.
7. Run actual video verification. Require platform resolution, duration, motion, full subtitles, audio stream, and `44.1 kHz stereo`.
8. Generate a topic-specific viral cover and run `cover_quality_gate.py`.
9. Send direct publish copy plus video and cover. Manual platforms remain `handoff_ready`, never `published`.
10. Persist every gate JSON and delivery receipt. An exit code without artifacts and receipts is not success.

## Verified TikTok Result

- Script gate: all eight dimensions passed.
- Visual assets: eight scenes, minimum declared semantic score `0.82`, no internal duplicate, no exact or perceptual duplicate across 32 scanned sibling-platform clips.
- Video: `1080x1920`, H.264, `51.014s`, AAC `44.1 kHz stereo`, motion score `0.04595`, no artifact-gate failures.
- Cover: `1080x1920`, `character_showdown`, safe-zone and content-match evidence passed.
- Delivery: direct copy, video, and cover sent; state remains `handoff_ready`.

## Operational Notes

- A large PNG cover was rejected by the messaging media parser. The same approved poster was encoded as a high-quality JPEG and delivered successfully. Treat transport encoding as a delivery concern, not permission to change the design.
- Pexels query text is not visual proof. Every selected result still requires frame inspection or an equivalent visual classifier before its observed-subject evidence is accepted.
