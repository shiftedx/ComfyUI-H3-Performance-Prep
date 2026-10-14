# ComfyUI H3 Performance Prep

Prepare a MiniMax H3 scene from a complete audio master: exact audio window,
structured prompt, supported generation length, and editorial trim metadata.

[Setup and node reference](docs/guide.md) · [Example workflow](examples/h3_performance_scene_prep_vocal.json) · [MIT](LICENSE)

## Install

Requires Python 3.11+, ComfyUI with H3 Ref2VA nodes, Video Helper Suite, and
MiniMaxH3TimelineAudioGuide. [Install the tested dependency versions](docs/guide.md#requirements).

From your ComfyUI installation:

```bash
cd custom_nodes
git clone https://github.com/shiftedx/ComfyUI-H3-Performance-Prep.git
```

Restart ComfyUI. Desktop and Windows Portable use different Python environments;
follow the [platform installation commands](docs/guide.md#installation).

## Use

1. Load the [vocal workflow](examples/h3_performance_scene_prep_vocal.json).
2. Select your complete audio master, performer image, and installed H3 models.
3. Set `start_frame`, `editorial_frames`, performer/scene descriptions, and verified lyrics.
4. Queue the workflow; review the FFV1/FLAC MKV in ComfyUI's output folder.

| Contract | Behavior |
| --- | --- |
| Audio | 24 fps timing; sample-aligned 32 kHz stereo; one batch, mono or stereo input |
| Video | Raw H3 lengths on the `17n + 5` grid, 124–362 frames; trim to editorial length |
| Modes | Vocals require lyrics and language; instrumental mode rejects lyrics |
| Assets | Models, source media, and generated files stay in your local installation |

The example targets 124 editorial frames. Split longer scenes; keep the
`audio_window` path through the audio guide and video muxer.
[Timing and limitations](docs/guide.md#how-timing-works).

## Develop

```bash
python -m pytest -q
python scripts/validate_workflow.py examples/h3_performance_scene_prep_vocal.json
```

For runtime validation, add `--object-info http://127.0.0.1:8188/object_info`.
Report issues with versions, settings, and reproduction steps; use placeholder
assets in committed workflows. [Troubleshooting](docs/guide.md#troubleshooting).
