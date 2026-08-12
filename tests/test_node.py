import importlib
import importlib.util
import json
import sys
import types
from pathlib import Path

import pytest
import torch

from h3_performance_prep.core import build_metadata, plan_scene


def test_node_schema_is_native_and_has_no_import_time_comfy_dependency():
    sys.modules.pop("h3_performance_prep.node", None)
    module = importlib.import_module("h3_performance_prep.node")
    node = module.H3PerformanceScenePrep

    assert "comfy" not in sys.modules
    assert list(node.INPUT_TYPES()["required"]) == [
        "source_audio",
        "start_frame",
        "editorial_frames",
        "mode",
        "performer_description",
        "scene_description",
        "verified_lyric",
        "lyric_language",
    ]
    assert node.INPUT_TYPES()["required"]["source_audio"][0] == "AUDIO"
    assert node.RETURN_TYPES == ("AUDIO", "STRING", "INT", "INT", "INT", "FLOAT", "FLOAT", "STRING")
    assert node.RETURN_NAMES == (
        "audio_window",
        "h3_prompt",
        "h3_raw_frames",
        "editorial_frames",
        "tail_trim_frames",
        "actual_start_seconds",
        "actual_duration_seconds",
        "scene_metadata_json",
    )
    assert node.FUNCTION == "prepare"
    assert node.CATEGORY == "H3/Performance"


def test_root_registration_exposes_the_scene_prep_node():
    root = importlib.import_module("__init__")

    assert root.NODE_CLASS_MAPPINGS["H3PerformanceScenePrep"].__name__ == "H3PerformanceScenePrep"
    assert root.NODE_DISPLAY_NAME_MAPPINGS["H3PerformanceScenePrep"] == "H3 Performance Scene Prep"


def test_root_registration_loads_with_comfyui_directory_package_context(monkeypatch):
    root_path = Path(__file__).parents[1] / "__init__.py"
    root_directory = str(root_path.parent.resolve())
    monkeypatch.setattr(sys, "path", [path for path in sys.path if str(Path(path).resolve()) != root_directory])
    monkeypatch.delitem(sys.modules, "h3_performance_prep", raising=False)
    monkeypatch.delitem(sys.modules, "h3_performance_prep.node", raising=False)
    spec = importlib.util.spec_from_file_location(
        root_directory, root_path
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)

    assert "H3PerformanceScenePrep" in module.NODE_CLASS_MAPPINGS


@pytest.mark.parametrize("shape", [(2, 1, 4000), (1, 3, 4000), (1, 4000)])
def test_prepare_rejects_invalid_batch_or_channels(shape):
    from h3_performance_prep.node import H3PerformanceScenePrep

    with pytest.raises(ValueError):
        H3PerformanceScenePrep().prepare(
            {"waveform": torch.zeros(shape), "sample_rate": 32000}, 0, 1, "instrumental", "p", "s", ""
        )


def test_prepare_resamples_the_full_master_before_slicing(monkeypatch):
    calls = []
    resampled_master = torch.arange(4000, dtype=torch.float32).reshape(1, 1, 4000)

    def resample(waveform, original_rate, new_rate):
        calls.append((waveform.clone(), original_rate, new_rate))
        return resampled_master

    torchaudio = types.ModuleType("torchaudio")
    functional = types.ModuleType("torchaudio.functional")
    functional.resample = resample
    torchaudio.functional = functional
    monkeypatch.setitem(sys.modules, "torchaudio", torchaudio)
    monkeypatch.setitem(sys.modules, "torchaudio.functional", functional)

    from h3_performance_prep.node import H3PerformanceScenePrep

    source = {"waveform": torch.zeros((1, 1, 44100)), "sample_rate": 44100}
    result = H3PerformanceScenePrep().prepare(source, 1, 1, "instrumental", "p", "s", "")

    assert len(calls) == 1
    assert calls[0][0].shape == (1, 1, 44100)
    assert calls[0][1:] == (44100, 32000)
    window = result[0]["waveform"]
    assert result[0]["sample_rate"] == 32000
    assert window.shape == (1, 2, 1334)
    assert torch.equal(window[0, 0], resampled_master[0, 0, 1333:2667])
    assert torch.equal(window[0, 1], resampled_master[0, 0, 1333:2667])
    assert window.data_ptr() != resampled_master.data_ptr()


def test_prepare_rejects_original_rate_overrun_before_resampling(monkeypatch):
    resample_called = False

    def resample(waveform, original_rate, new_rate):
        nonlocal resample_called
        resample_called = True
        return torch.zeros((1, 2, 1333))

    torchaudio = types.ModuleType("torchaudio")
    functional = types.ModuleType("torchaudio.functional")
    functional.resample = resample
    torchaudio.functional = functional
    monkeypatch.setitem(sys.modules, "torchaudio", torchaudio)
    monkeypatch.setitem(sys.modules, "torchaudio.functional", functional)

    from h3_performance_prep.node import H3PerformanceScenePrep

    source = {"waveform": torch.zeros((1, 2, 1836)), "sample_rate": 44100}
    with pytest.raises(ValueError, match="overruns"):
        H3PerformanceScenePrep().prepare(source, 0, 1, "instrumental", "p", "s", "")

    assert not resample_called


@pytest.mark.parametrize(
    ("source_sample_rate", "source_samples", "editorial_frames", "output_samples"),
    [(8000, 333, 1, 1333), (16000, 1333, 2, 2667)],
)
def test_prepare_reconciles_valid_exact_end_resample_rounding_without_silence_padding(
    monkeypatch, source_sample_rate, source_samples, editorial_frames, output_samples
):
    def resample(waveform, original_rate, new_rate):
        assert waveform.shape[-1] == source_samples
        return torch.ones((1, 2, output_samples - 1), dtype=waveform.dtype)

    torchaudio = types.ModuleType("torchaudio")
    functional = types.ModuleType("torchaudio.functional")
    functional.resample = resample
    torchaudio.functional = functional
    monkeypatch.setitem(sys.modules, "torchaudio", torchaudio)
    monkeypatch.setitem(sys.modules, "torchaudio.functional", functional)

    from h3_performance_prep.node import H3PerformanceScenePrep

    source = {"waveform": torch.ones((1, 2, source_samples)), "sample_rate": source_sample_rate}
    result = H3PerformanceScenePrep().prepare(
        source, 0, editorial_frames, "instrumental", "p", "s", "   "
    )

    assert result[0]["waveform"].shape == (1, 2, output_samples)
    assert torch.all(result[0]["waveform"] == 1)
    metadata = json.loads(result[7])
    assert metadata["lyric"] == ""
    assert metadata["output_batch"] == 1
    assert metadata["output_channels"] == 2


def test_prepare_uses_the_exact_end_boundary_and_matching_metadata():
    from h3_performance_prep.node import H3PerformanceScenePrep

    source = {"waveform": torch.arange(6000, dtype=torch.float32).reshape(1, 2, 3000), "sample_rate": 32000}
    result = H3PerformanceScenePrep().prepare(source, 1, 1, "vocal", "p", "s", "line", "English")
    plan = plan_scene(1, 1)

    assert torch.equal(result[0]["waveform"], source["waveform"][:, :, 1333:2667])
    assert result[0]["waveform"].device.type == "cpu"
    assert result[0]["waveform"].dtype == source["waveform"].dtype
    assert result[0]["waveform"].shape[-1] == plan.output_end_sample - plan.output_start_sample
    assert result[2] > result[3]
    assert result[2:7] == (
        plan.raw_frames,
        1,
        plan.tail_trim_frames,
        plan.actual_start_seconds,
        plan.actual_duration_seconds,
    )
    assert result[7] == build_metadata(
        plan,
        mode="vocal",
        lyric_language="English",
        lyric="line",
        source_sample_rate=32000,
        source_samples=3000,
        input_channels=2,
        channel_policy="preserve_stereo",
        warnings=[],
    )
    assert json.loads(result[7])["output_end_sample"] == 2667
    assert json.loads(result[7])["output_device_policy"] == "cpu_for_comfyui_audio_interoperability"


def test_prepare_rejects_source_overrun_and_empty_source():
    from h3_performance_prep.node import H3PerformanceScenePrep

    node = H3PerformanceScenePrep()
    with pytest.raises(ValueError, match="overruns"):
        node.prepare({"waveform": torch.zeros((1, 2, 4000)), "sample_rate": 32000}, 3, 1, "instrumental", "p", "s", "")
    with pytest.raises(ValueError, match="empty"):
        node.prepare({"waveform": torch.zeros((1, 2, 0)), "sample_rate": 32000}, 0, 1, "instrumental", "p", "s", "")
