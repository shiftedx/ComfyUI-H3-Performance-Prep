from __future__ import annotations

from dataclasses import dataclass
import json

import torch


OUTPUT_SAMPLE_RATE = 32000
FPS = 24
MIN_RAW_FRAMES = 124
MAX_RAW_FRAMES = 362


@dataclass(frozen=True)
class ScenePlan:
    start_frame: int
    end_frame: int
    editorial_frames: int
    raw_frames: int
    tail_trim_frames: int
    output_start_sample: int
    output_end_sample: int
    requested_start_seconds: float
    requested_duration_seconds: float
    actual_start_seconds: float
    actual_duration_seconds: float


def round_ratio_half_up(numerator: int, denominator: int) -> int:
    if denominator <= 0:
        raise ValueError("denominator must be positive")
    if numerator < 0:
        return -round_ratio_half_up(-numerator, denominator)
    return (numerator * 2 + denominator) // (denominator * 2)


def frame_boundary_sample(frame: int, sample_rate: int = OUTPUT_SAMPLE_RATE, fps: int = FPS) -> int:
    if frame < 0:
        raise ValueError("frame must not be negative")
    return round_ratio_half_up(frame * sample_rate, fps)


def plan_scene(start_frame: int, editorial_frames: int) -> ScenePlan:
    if start_frame < 0:
        raise ValueError("start_frame must not be negative")
    if editorial_frames <= 0:
        raise ValueError("editorial_frames must be positive")

    raw_frames = max(MIN_RAW_FRAMES, editorial_frames)
    raw_frames = ((raw_frames - 5 + 16) // 17) * 17 + 5
    if raw_frames > MAX_RAW_FRAMES:
        raise ValueError("raw frame length exceeds 362; split the scene")

    end_frame = start_frame + editorial_frames
    output_start_sample = frame_boundary_sample(start_frame)
    output_end_sample = frame_boundary_sample(end_frame)
    return ScenePlan(
        start_frame=start_frame,
        end_frame=end_frame,
        editorial_frames=editorial_frames,
        raw_frames=raw_frames,
        tail_trim_frames=raw_frames - editorial_frames,
        output_start_sample=output_start_sample,
        output_end_sample=output_end_sample,
        requested_start_seconds=start_frame / FPS,
        requested_duration_seconds=editorial_frames / FPS,
        actual_start_seconds=output_start_sample / OUTPUT_SAMPLE_RATE,
        actual_duration_seconds=(output_end_sample - output_start_sample) / OUTPUT_SAMPLE_RATE,
    )


def normalize_channels(waveform: torch.Tensor) -> tuple[torch.Tensor, str]:
    if waveform.ndim != 3:
        raise ValueError("waveform must have shape [B,C,L]")
    batch, channels, samples = waveform.shape
    if batch != 1:
        raise ValueError("waveform must contain exactly one batch")
    if channels not in (1, 2):
        raise ValueError("waveform must have one or two channels")
    if samples == 0:
        raise ValueError("waveform must not be empty")
    if channels == 1:
        return waveform.repeat(1, 2, 1), "duplicate_mono_to_stereo"
    return waveform, "preserve_stereo"


def build_prompt(
    mode: str,
    performer_description: str,
    scene_description: str,
    verified_lyric: str,
    lyric_language: str,
) -> str:
    lyric = verified_lyric.strip()
    language = lyric_language.strip()
    if mode == "vocal":
        if not lyric:
            raise ValueError("vocal mode requires a verified lyric")
        if not language:
            raise ValueError("vocal mode requires a lyric language")
        performance_direction = (
            "Use phoneme-timed articulation with jaw and cheek motion, natural breath, and resting lips in gaps. "
            "Maintain articulation whenever visible, continuity through cuts and occlusion, and correct lyric resumption. "
            "Maintain identity, wardrobe, and performance continuity."
        )
        soundscape = f"Perform the verified {language} lyric: {lyric}"
    elif mode == "instrumental":
        if lyric:
            raise ValueError("instrumental mode requires an empty lyric")
        performance_direction = "Keep a naturally closed/resting mouth with body rhythm only."
        soundscape = "Preserve the instrumental performance timing."
    else:
        raise ValueError("mode must be vocal or instrumental")

    return "\n".join(
        (
            "subject_definitions:",
            f"(S1) {performer_description}",
            "summary:",
            "<Picture 1> is a performance scene whose pinned target-timeline source audio is the timing authority; generated audio is discarded.",
            "retention_analysis:",
            "Keep the performer visually coherent while preserving the supplied target timeline.",
            "detailed_description:",
            f"{scene_description}",
            performance_direction,
            "overall_soundscape:",
            soundscape,
            "non_diegetic_music:",
            "Do not add non-diegetic music; use the pinned target-timeline source audio only.",
        )
    )


def build_metadata(
    plan: ScenePlan,
    *,
    mode: str,
    lyric_language: str,
    lyric: str,
    source_sample_rate: int,
    source_samples: int,
    input_channels: int,
    channel_policy: str,
    warnings: list[str],
) -> str:
    payload = {
        "actual_duration_seconds": plan.actual_duration_seconds,
        "actual_start_seconds": plan.actual_start_seconds,
        "channel_policy": channel_policy,
        "editorial_frames": plan.editorial_frames,
        "input_batch": 1,
        "input_channels": input_channels,
        "lyric": lyric.strip(),
        "lyric_language": lyric_language,
        "mode": mode,
        "output_batch": 1,
        "output_channels": 2,
        "output_end_sample": plan.output_end_sample,
        "output_device": "cpu",
        "output_device_policy": "cpu_for_comfyui_audio_interoperability",
        "output_sample_rate": OUTPUT_SAMPLE_RATE,
        "output_start_sample": plan.output_start_sample,
        "raw_frames": plan.raw_frames,
        "requested_duration_seconds": plan.requested_duration_seconds,
        "requested_frame_end": plan.end_frame,
        "requested_frame_start": plan.start_frame,
        "requested_start_seconds": plan.requested_start_seconds,
        "schema": "h3-performance-scene-prep/v1",
        "source_sample_rate": source_sample_rate,
        "source_end_sample": frame_boundary_sample(plan.end_frame, source_sample_rate),
        "source_samples": source_samples,
        "source_start_sample": frame_boundary_sample(plan.start_frame, source_sample_rate),
        "tail_trim_frames": plan.tail_trim_frames,
        "version": "v1",
        "warnings": warnings,
    }
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
