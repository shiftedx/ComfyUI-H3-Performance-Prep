import json

import pytest
import torch

from h3_performance_prep.core import (
    build_metadata,
    build_prompt,
    frame_boundary_sample,
    normalize_channels,
    plan_scene,
)


@pytest.mark.parametrize("frame, expected", [(0, 0), (1, 1333), (2, 2667), (3, 4000)])
def test_frame_boundaries_round_half_up(frame, expected):
    assert frame_boundary_sample(frame) == expected


def test_adjacent_editorial_windows_share_their_boundary():
    first = plan_scene(start_frame=7, editorial_frames=11)
    second = plan_scene(start_frame=18, editorial_frames=9)

    assert first.output_end_sample == second.output_start_sample


def test_scene_plan_enforces_minimum_and_grid():
    plan = plan_scene(start_frame=12, editorial_frames=100)

    assert plan.start_frame == 12
    assert plan.end_frame == 112
    assert plan.raw_frames == 124
    assert plan.tail_trim_frames == 24
    assert plan.raw_frames % 17 == 5
    assert plan.output_start_sample == 16000
    assert plan.output_end_sample == frame_boundary_sample(112)
    assert plan.requested_start_seconds == 0.5
    assert plan.requested_duration_seconds == pytest.approx(100 / 24)
    assert plan.actual_start_seconds == 0.5
    assert plan.actual_duration_seconds == pytest.approx((plan.output_end_sample - plan.output_start_sample) / 32000)


def test_scene_plan_snaps_up_and_accepts_the_maximum():
    plan = plan_scene(start_frame=0, editorial_frames=125)
    maximum = plan_scene(start_frame=0, editorial_frames=362)

    assert plan.raw_frames == 141
    assert maximum.raw_frames == 362
    assert maximum.tail_trim_frames == 0


def test_scene_plan_rejects_a_result_above_the_maximum():
    with pytest.raises(ValueError, match="split the scene"):
        plan_scene(start_frame=0, editorial_frames=363)


def test_vocal_prompt_contains_the_timing_and_articulation_contract():
    prompt = build_prompt(
        "vocal",
        "A focused singer in a silver jacket.",
        "Close-up that cuts to a profile at the chorus.",
        "Stay with me",
        "English",
    )

    for heading in (
        "subject_definitions",
        "summary",
        "retention_analysis",
        "detailed_description",
        "overall_soundscape",
        "non_diegetic_music",
    ):
        assert heading in prompt
    assert prompt.count("(S1)") == 1
    assert "<Picture 1>" in prompt
    assert "<Audio 1>" not in prompt
    assert "pinned target-timeline source audio is the timing authority" in prompt
    assert "generated audio is discarded" in prompt
    assert "phoneme-timed articulation" in prompt
    assert "jaw and cheek motion" in prompt
    assert "natural breath" in prompt
    assert "resting lips in gaps" in prompt
    assert "continuity through cuts and occlusion" in prompt
    assert "correct lyric resumption" in prompt


def test_instrumental_prompt_forbids_vocal_direction_and_requires_resting_mouth():
    prompt = build_prompt("instrumental", "A drummer.", "Wide performance view.", "", "English")

    assert "singing" not in prompt.lower()
    assert "articulation" not in prompt.lower()
    assert "naturally closed/resting mouth" in prompt
    assert "body rhythm only" in prompt


@pytest.mark.parametrize(
    ("mode", "lyric", "language", "message"),
    [
        ("vocal", "", "English", "lyric"),
        ("vocal", "line", "", "language"),
        ("instrumental", "stale", "English", "lyric"),
    ],
)
def test_prompt_rejects_invalid_mode_lyric_combinations(mode, lyric, language, message):
    with pytest.raises(ValueError, match=message):
        build_prompt(mode, "performer", "scene", lyric, language)


def test_normalize_channels_duplicates_mono_and_preserves_stereo():
    mono = torch.tensor([[[1.0, -0.5]]])
    stereo = torch.tensor([[[1.0, 2.0], [3.0, 4.0]]])

    normalized_mono, mono_policy = normalize_channels(mono)
    normalized_stereo, stereo_policy = normalize_channels(stereo)

    assert mono_policy == "duplicate_mono_to_stereo"
    assert torch.equal(normalized_mono, mono.repeat(1, 2, 1))
    assert stereo_policy == "preserve_stereo"
    assert normalized_stereo is stereo


@pytest.mark.parametrize("shape", [(2, 1, 4), (1, 3, 4), (1, 4), (1, 1, 0)])
def test_normalize_channels_rejects_invalid_audio_shapes(shape):
    with pytest.raises(ValueError):
        normalize_channels(torch.zeros(shape))


def test_metadata_is_deterministic_and_has_all_boundary_fields():
    plan = plan_scene(start_frame=1, editorial_frames=24)
    metadata = build_metadata(
        plan,
        mode="vocal",
        lyric_language="Korean",
        lyric="가나다",
        source_sample_rate=44100,
        source_samples=88200,
        input_channels=1,
        channel_policy="duplicate_mono_to_stereo",
        warnings=[],
    )

    assert metadata == build_metadata(
        plan,
        mode="vocal",
        lyric_language="Korean",
        lyric="가나다",
        source_sample_rate=44100,
        source_samples=88200,
        input_channels=1,
        channel_policy="duplicate_mono_to_stereo",
        warnings=[],
    )
    assert metadata == json.dumps(json.loads(metadata), sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    payload = json.loads(metadata)
    assert payload["schema"] == "h3-performance-scene-prep/v1"
    assert payload["requested_frame_start"] == 1
    assert payload["requested_frame_end"] == 25
    assert payload["raw_frames"] == plan.raw_frames
    assert payload["tail_trim_frames"] == plan.tail_trim_frames
    assert payload["output_start_sample"] == plan.output_start_sample
    assert payload["output_end_sample"] == plan.output_end_sample
    assert payload["source_sample_rate"] == 44100
    assert payload["source_samples"] == 88200
    assert payload["source_start_sample"] == 1838
    assert payload["source_end_sample"] == 45938
    assert payload["output_device"] == "cpu"
    assert payload["output_device_policy"] == "cpu_for_comfyui_audio_interoperability"
    assert payload["output_batch"] == 1
    assert payload["output_channels"] == 2
    assert payload["input_channels"] == 1
    assert payload["channel_policy"] == "duplicate_mono_to_stereo"


def test_metadata_normalizes_lyric_whitespace():
    metadata = build_metadata(
        plan_scene(start_frame=0, editorial_frames=1),
        mode="instrumental",
        lyric_language="English",
        lyric=" \t\n ",
        source_sample_rate=32000,
        source_samples=2000,
        input_channels=2,
        channel_policy="preserve_stereo",
        warnings=[],
    )

    assert json.loads(metadata)["lyric"] == ""
