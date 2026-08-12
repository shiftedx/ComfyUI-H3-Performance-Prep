from __future__ import annotations

import torch
import torch.nn.functional as F

from .core import (
    OUTPUT_SAMPLE_RATE,
    build_metadata,
    build_prompt,
    frame_boundary_sample,
    normalize_channels,
    plan_scene,
)


class H3PerformanceScenePrep:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "source_audio": ("AUDIO",),
                "start_frame": ("INT", {"default": 0, "min": 0}),
                "editorial_frames": ("INT", {"default": 124, "min": 1}),
                "mode": (["vocal", "instrumental"],),
                "performer_description": ("STRING", {"default": "", "multiline": True}),
                "scene_description": ("STRING", {"default": "", "multiline": True}),
                "verified_lyric": ("STRING", {"default": "", "multiline": True}),
                "lyric_language": ("STRING", {"default": "English"}),
            }
        }

    RETURN_TYPES = ("AUDIO", "STRING", "INT", "INT", "INT", "FLOAT", "FLOAT", "STRING")
    RETURN_NAMES = (
        "audio_window",
        "h3_prompt",
        "h3_raw_frames",
        "editorial_frames",
        "tail_trim_frames",
        "actual_start_seconds",
        "actual_duration_seconds",
        "scene_metadata_json",
    )
    FUNCTION = "prepare"
    CATEGORY = "H3/Performance"

    def prepare(
        self,
        source_audio,
        start_frame,
        editorial_frames,
        mode,
        performer_description,
        scene_description,
        verified_lyric,
        lyric_language="English",
    ):
        if not isinstance(source_audio, dict):
            raise ValueError("source_audio must be an AUDIO dictionary")
        waveform = source_audio.get("waveform")
        source_sample_rate = source_audio.get("sample_rate")
        if not isinstance(waveform, torch.Tensor):
            raise ValueError("source_audio waveform must be a torch.Tensor")
        if not isinstance(source_sample_rate, int) or source_sample_rate <= 0:
            raise ValueError("source_audio sample_rate must be a positive integer")
        if waveform.ndim != 3:
            raise ValueError("waveform must have shape [B,C,L]")
        if waveform.shape[0] != 1:
            raise ValueError("waveform must contain exactly one batch")
        if waveform.shape[1] not in (1, 2):
            raise ValueError("waveform must have one or two channels")
        if waveform.shape[2] == 0:
            raise ValueError("source audio is empty")

        input_channels = waveform.shape[1]
        source_samples = waveform.shape[2]
        plan = plan_scene(start_frame, editorial_frames)
        if frame_boundary_sample(plan.end_frame, source_sample_rate) > source_samples:
            raise ValueError("requested audio window overruns the source master")
        if source_sample_rate != OUTPUT_SAMPLE_RATE:
            from torchaudio.functional import resample

            waveform = resample(waveform, source_sample_rate, OUTPUT_SAMPLE_RATE)
        waveform, channel_policy = normalize_channels(waveform)
        audio_window = waveform[:, :, plan.output_start_sample : plan.output_end_sample]
        expected_samples = plan.output_end_sample - plan.output_start_sample
        if audio_window.shape[2] < expected_samples:
            expected_resampled_master = (source_samples * OUTPUT_SAMPLE_RATE + source_sample_rate - 1) // source_sample_rate
            if waveform.shape[2] != expected_resampled_master or audio_window.shape[2] == 0:
                raise ValueError("requested audio window overruns the source master")
            audio_window = F.interpolate(audio_window, size=expected_samples, mode="linear", align_corners=False)

        prompt = build_prompt(mode, performer_description, scene_description, verified_lyric, lyric_language)
        metadata = build_metadata(
            plan,
            mode=mode,
            lyric_language=lyric_language,
            lyric=verified_lyric,
            source_sample_rate=source_sample_rate,
            source_samples=source_samples,
            input_channels=input_channels,
            channel_policy=channel_policy,
            warnings=[],
        )
        audio_window = audio_window.to(device="cpu").clone()
        return (
            {"waveform": audio_window, "sample_rate": OUTPUT_SAMPLE_RATE},
            prompt,
            plan.raw_frames,
            plan.editorial_frames,
            plan.tail_trim_frames,
            plan.actual_start_seconds,
            plan.actual_duration_seconds,
            metadata,
        )
