# ComfyUI H3 Performance Prep

`H3PerformanceScenePrep` prepares one MiniMax H3 performance scene from an authoritative source master. It emits a CPU `AUDIO` window, structured H3 prompt, raw and editorial frame counts, timing values, and deterministic scene metadata. This package makes no quality guarantee.

## Install

Clone this repository under `ComfyUI/custom_nodes`, or create a directory junction from that folder to this checkout. Restart ComfyUI after installation. The portable example also needs stock MiniMax H3 Ref2VA nodes, Video Helper Suite, and `ComfyUI-MiniMaxH3-Contex-Loop` 0.3.8 (the tested timeline-guide dependency).

## V1 contract

V1 is fixed at 24 fps, stereo 32 kHz. `source_audio` is the complete master; `start_frame` and `editorial_frames` select the review window. The node returns, in order: `audio_window`, `h3_prompt`, `h3_raw_frames`, `editorial_frames`, `tail_trim_frames`, actual start/duration seconds, and `scene_metadata_json`.

Frame boundaries use integer half-up rounding of `frame * 32000 / 24`. The complete master is resampled to 32 kHz before one exact slice is taken, so adjacent scenes share the same boundary. Input must be `[B, C, L]`, `B=1`, and one or two channels: mono is duplicated without gain change; stereo is preserved. Other channel layouts and source overruns are rejected.

Vocal prompts require a lyric and language; instrumental prompts reject lyrics. Both use structured `subject_definitions`, `summary`, `retention_analysis`, `detailed_description`, `overall_soundscape`, and `non_diegetic_music`. Describe cuts, framing, transitions, and microphone placement in the scene description.

## Example workflow

Open `examples/h3_performance_scene_prep_vocal.json`, select your local master, identity image, and installed H3 model assets. It uses 1344x768, `ref_image_size=max`, `res_multistep`, a 20-step `BasicScheduler`, and normal model attention; it does not use Turbo or EasyCache.

The prep prompt and raw frame count drive Ref2VA. Ref2VA conditioning, prep `audio_window`, raw frame count, and the audio VAE feed `MiniMaxH3TimelineAudioGuide`; its conditioning drives `BasicGuider`. Standalone Ref2VA `ref_audios` stay disconnected. Generated H3 audio is intentionally discarded: only video latent is decoded with `VAEDecode`.

Ref2VA produces the raw H3 grid, then `ImageFromBatch` keeps exactly `editorial_frames` (starting at zero). A second `ImageFromBatch` selects the final editorial frame and `ImageBatch` appends that duplicate only at the mux boundary. The 125-frame input extends just beyond the 124-frame audio end; VHS `trim_to_audio`/FFmpeg `-shortest` retains the intended 124 frames while allowing the final partial FLAC packet to complete. The workflow writes an FFV1 MKV review with lossless FLAC audio, avoiding AAC priming/padding and keeping the muxed audio sample-exact with `audio_window`. The node returns CPU audio for Video Helper Suite interoperability.

The example asks for 124 editorial frames, hence 124 raw frames. H3 raw lengths are snapped to the supported `17n + 5` grid; production lengths span 124–362. Contex Loop 0.3.8 has an unpadded raw-guide-tail limitation, so this 124/124 example avoids an extra raw tail. Split longer scenes rather than exceeding the maximum.

## Validate and troubleshoot

Run structural validation before importing:

```powershell
python scripts/validate_workflow.py examples/h3_performance_scene_prep_vocal.json
python scripts/validate_workflow.py examples/h3_performance_scene_prep_vocal.json --object-info http://127.0.0.1:8188/object_info
```

If validation says the timeline guide is missing, install `ComfyUI-MiniMaxH3-Contex-Loop` 0.3.8. If the workflow cannot resolve placeholder filenames, select installed local assets in the UI; do not commit them. If the requested window overruns the master, choose a valid start/frame range. Check that VHS exposes the `video/ffv1-mkv` format and that the loaded audio is readable before queuing work.
