# ComfyUI H3 Performance Prep

`H3PerformanceScenePrep` prepares one MiniMax H3 performance scene from a complete source-audio master. It turns a frame-range request into an exact 32 kHz audio window, an H3 prompt, supported raw-frame length, and scene metadata. This keeps the picture and source audio on one timeline when H3's supported generation lengths do not match the editorial cut exactly.

## What it does

- Slices the authoritative source master at frame-derived sample boundaries.
- Resamples the complete master to 32 kHz before slicing, so adjacent scenes share a boundary.
- Preserves stereo or duplicates mono to stereo without changing gain.
- Builds a structured vocal or instrumental H3 prompt.
- Returns raw and editorial frame counts for the H3 workflow.
- Supplies CPU `AUDIO` for ComfyUI and Video Helper Suite interoperability.
- Includes a vocal workflow that writes a 24 fps FFV1/FLAC MKV review.

## Requirements

Tested with Python 3.11, ComfyUI, PyTorch, and torchaudio. The included workflow also requires stock MiniMax H3 Ref2VA nodes, Video Helper Suite, and `ComfyUI-MiniMaxH3-Contex-Loop` 0.3.8 for `MiniMaxH3TimelineAudioGuide`.

This repository does not include ComfyUI, H3 model files, CLIP or VAE files, identity images, source audio, or generated media. Install those assets in your ComfyUI setup and select them in the workflow UI.

## Installation

Clone the repository into ComfyUI's `custom_nodes` directory.

```bash
cd /path/to/ComfyUI/custom_nodes
git clone https://github.com/shiftedx/ComfyUI-H3-Performance-Prep.git
```

```powershell
git clone https://github.com/shiftedx/ComfyUI-H3-Performance-Prep.git
```

Run either command from ComfyUI's `custom_nodes` directory. Restart ComfyUI after cloning. Install the workflow dependencies from their usual ComfyUI sources before loading the example.

## Quick start

1. Open `examples/h3_performance_scene_prep_vocal.json` in ComfyUI.
2. In `LoadAudio`, choose the complete source master. Do not load a pre-cut excerpt.
3. In `LoadImage`, choose the performer identity image.
4. In the H3 loader nodes, choose your installed H3 CLIP, video VAE, audio VAE, and model files.
5. In `H3 Performance Scene Prep`, set `start_frame`, `editorial_frames`, the performer and scene descriptions, and a verified lyric with its language.
6. Queue the workflow. `VHS_VideoCombine` saves the FFV1/FLAC review under ComfyUI's output directory.

The example starts at frame 0 and requests 124 editorial frames in vocal mode. It uses 1344×768, `ref_image_size=max`, `res_multistep`, and a 20-step `BasicScheduler`. It does not use Turbo or EasyCache.

## Inputs

| Input | Type | Use |
| --- | --- | --- |
| `source_audio` | `AUDIO` | Complete source master. It must contain one batch, one or two channels, and samples through the requested end frame. |
| `start_frame` | `INT` | First editorial frame in the source master. Defaults to `0`. |
| `editorial_frames` | `INT` | Number of frames in the final edit. Defaults to `124`. |
| `mode` | `vocal` or `instrumental` | Selects prompt and lyric rules. |
| `performer_description` | `STRING` | Identity, wardrobe, and visible performance details. |
| `scene_description` | `STRING` | Camera, cuts, setting, transitions, and microphone placement. |
| `verified_lyric` | `STRING` | Required in `vocal` mode. Leave it empty in `instrumental` mode. |
| `lyric_language` | `STRING` | Required for vocals. Defaults to `English`. |

Vocal mode requires a non-empty lyric and language. Instrumental mode rejects a lyric.

## Outputs

| Output | Type | Use |
| --- | --- | --- |
| `audio_window` | `AUDIO` | Exact 32 kHz stereo window on CPU. Connect it to `MiniMaxH3TimelineAudioGuide` and `VHS_VideoCombine`. |
| `h3_prompt` | `STRING` | Structured H3 prompt. Connect it to `MiniMaxH3ReferenceToVideo`. |
| `h3_raw_frames` | `INT` | H3-supported generation length. Connect it to `MiniMaxH3ReferenceToVideo` and `MiniMaxH3TimelineAudioGuide`. |
| `editorial_frames` | `INT` | Final cut length. Connect it to the trim `ImageFromBatch` node. |
| `tail_trim_frames` | `INT` | Extra generated frames after the editorial cut. |
| `actual_start_seconds` | `FLOAT` | Sample-aligned start time after rounding. |
| `actual_duration_seconds` | `FLOAT` | Sample-aligned audio-window duration. |
| `scene_metadata_json` | `STRING` | Deterministic JSON record of timing, channel, source, and prompt settings. |

## How timing works

The node runs at 24 fps and 32 kHz. For each boundary frame, it uses integer half-up rounding of `frame × 32000 / 24`, then slices the resampled master between the start and end boundaries. At 24 fps, a one-frame duration averages 1333⅓ samples, so sample counts alternate around that value while neighboring scenes still meet at the same sample.

H3 accepts raw lengths on a `17n + 5` grid. The node rounds the requested editorial length up to that grid, with a minimum of 124 and a maximum of 362 raw frames. It returns `tail_trim_frames` so the workflow can keep the requested editorial duration.

The workflow first trims decoded images to `editorial_frames`. It duplicates that final editorial image once and appends it only at the mux boundary. The extra image extends the image stream past the audio end; Video Helper Suite uses `trim_to_audio` and FFmpeg `-shortest` to retain the editorial frames while FLAC finishes its final partial packet. The resulting FFV1/FLAC MKV keeps the muxed audio sample-exact with `audio_window` without AAC priming or padding.

`MiniMaxH3ReferenceToVideo` receives the prep prompt and raw frame count. Its conditioning, `audio_window`, raw frame count, and the audio VAE feed `MiniMaxH3TimelineAudioGuide`; the guide then feeds `BasicGuider`. Leave standalone Ref2VA `ref_audios` disconnected. The workflow discards generated H3 audio and decodes video only.

## Troubleshooting

Run the checks below from the repository root before importing the workflow:

```powershell
python -m pytest -q
python scripts/validate_workflow.py examples/h3_performance_scene_prep_vocal.json --object-info http://127.0.0.1:8188/object_info
```

| Symptom | Remedy |
| --- | --- |
| Validator reports that `MiniMaxH3TimelineAudioGuide` is missing | Install `ComfyUI-MiniMaxH3-Contex-Loop` 0.3.8 and restart ComfyUI. |
| Placeholder filename cannot resolve | Select your installed model, image, and source-audio files in the workflow UI. Keep those local choices out of commits. |
| Requested audio window overruns the master | Lower `start_frame` or `editorial_frames`, or load the complete master. |
| Vocal prompt fails validation | Supply a verified lyric and its language. |
| Instrumental prompt fails validation | Clear `verified_lyric`. |
| FFV1 format is unavailable | Update or configure Video Helper Suite so `video/ffv1-mkv` is available. |

## Limitations

V1 supports a single batch and mono or stereo input only. It converts output to 32 kHz stereo, accepts raw H3 lengths from 124 through 362 frames, and requires you to split longer scenes. The included workflow targets a 124-frame vocal scene and relies on `ComfyUI-MiniMaxH3-Contex-Loop` 0.3.8; that release has an unpadded raw-guide-tail limitation, so the example avoids an extra raw tail. The node prepares timing and prompts; it does not provide models, media, generation quality guarantees, or automatic editorial decisions.

## Development

Run the test suite and structural workflow validation after changes:

```powershell
python -m pytest -q
python scripts/validate_workflow.py examples/h3_performance_scene_prep_vocal.json
```

Keep workflow examples portable: use placeholders for local assets, never commit media or model files, and preserve the `audio_window` timing path through `MiniMaxH3TimelineAudioGuide` and `VHS_VideoCombine`.

## License

Original code in this repository is released under the [MIT License](LICENSE).
