from __future__ import annotations

import importlib
import importlib.util
import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).parents[1]
WORKFLOW = ROOT / "examples" / "h3_performance_scene_prep_vocal.json"
VALIDATOR = ROOT / "scripts" / "validate_workflow.py"
GUIDE_MISSING_MESSAGE = (
    "MiniMaxH3TimelineAudioGuide is required "
    "(tested with ComfyUI-MiniMaxH3-Contex-Loop 0.3.8)"
)


def load_workflow() -> dict:
    return json.loads(WORKFLOW.read_text(encoding="utf-8"))


def nodes_by_type(workflow: dict) -> dict[str, dict]:
    return {node["type"]: node for node in workflow["nodes"]}


def node_by_title(workflow: dict, title: str) -> dict:
    return next(node for node in workflow["nodes"] if node.get("title") == title)


def node_by_id(workflow: dict) -> dict[int, dict]:
    return {node["id"]: node for node in workflow["nodes"]}


def links(workflow: dict) -> set[tuple[int, int, int, int]]:
    return {
        tuple((link["value"] if isinstance(link, dict) else link)[1:5])
        for link in workflow["links"]
    }


def assert_link(workflow: dict, source_type: str, source_slot: int, target_type: str, target_slot: int) -> None:
    typed_nodes = nodes_by_type(workflow)
    assert (
        typed_nodes[source_type]["id"],
        source_slot,
        typed_nodes[target_type]["id"],
        target_slot,
    ) in links(workflow)


def test_workflow_has_portable_required_classes_and_live_slot_names():
    workflow = load_workflow()
    types = {node["type"] for node in workflow["nodes"]}

    assert {
        "LoadAudio",
        "LoadImage",
        "H3PerformanceScenePrep",
        "MiniMaxH3ReferenceToVideo",
        "MiniMaxH3TimelineAudioGuide",
        "KSamplerSelect",
        "BasicScheduler",
        "BasicGuider",
        "SamplerCustomAdvanced",
        "VAEDecode",
        "ImageFromBatch",
        "VHS_VideoCombine",
    } <= types

    ref2va = nodes_by_type(workflow)["MiniMaxH3ReferenceToVideo"]
    assert any(item["name"] == "ref_images.ref_image_0" for item in ref2va["inputs"])
    assert any(item["name"] == "ref_audios.ref_audio_0" and item["link"] is None for item in ref2va["inputs"])


def test_workflow_uses_the_complete_modern_comfyui_serialization_envelope():
    workflow = load_workflow()

    assert workflow["version"] == 0.4
    assert isinstance(workflow["id"], str) and workflow["id"]
    assert workflow["revision"] == 0
    assert workflow["groups"] == []
    assert workflow["config"] == {}
    assert {"ue_links", "ds"} <= workflow["extra"].keys()

    required_node_fields = {
        "id",
        "type",
        "pos",
        "size",
        "flags",
        "order",
        "mode",
        "inputs",
        "outputs",
        "properties",
    }
    assert all(required_node_fields <= node.keys() for node in workflow["nodes"])
    assert {"widgets_values"} <= nodes_by_type(workflow)["H3PerformanceScenePrep"].keys()
    assert {"widgets_values"} <= nodes_by_type(workflow)["VHS_VideoCombine"].keys()


def test_workflow_routes_exact_audio_guide_topology_and_discards_generated_audio():
    workflow = load_workflow()
    typed_nodes = nodes_by_type(workflow)

    assert_link(workflow, "LoadAudio", 0, "H3PerformanceScenePrep", 0)
    assert_link(workflow, "LoadImage", 0, "MiniMaxH3ReferenceToVideo", 3)
    assert_link(workflow, "H3PerformanceScenePrep", 1, "MiniMaxH3ReferenceToVideo", 7)
    assert_link(workflow, "H3PerformanceScenePrep", 2, "MiniMaxH3ReferenceToVideo", 10)
    assert_link(workflow, "MiniMaxH3ReferenceToVideo", 0, "MiniMaxH3TimelineAudioGuide", 0)
    assert_link(workflow, "H3PerformanceScenePrep", 0, "MiniMaxH3TimelineAudioGuide", 2)
    assert_link(workflow, "H3PerformanceScenePrep", 2, "MiniMaxH3TimelineAudioGuide", 3)
    assert_link(workflow, "MiniMaxH3TimelineAudioGuide", 0, "BasicGuider", 1)
    assert_link(workflow, "MiniMaxH3ReferenceToVideo", 1, "SamplerCustomAdvanced", 4)
    assert_link(workflow, "H3PerformanceScenePrep", 0, "VHS_VideoCombine", 1)
    trim = node_by_title(workflow, "Trim to editorial frames")
    assert (typed_nodes["VAEDecode"]["id"], 0, trim["id"], 0) in links(workflow)
    assert (typed_nodes["H3PerformanceScenePrep"]["id"], 3, trim["id"], 2) in links(workflow)

    decoded_audio = [node for node in workflow["nodes"] if "DecodeAudio" in node["type"]]
    assert decoded_audio == []
    assert all("MiniMaxH3Turbo" not in node["type"] and "EasyCache" not in node["type"] for node in workflow["nodes"])
    assert typed_nodes["MiniMaxH3ReferenceToVideo"]["inputs"][6]["link"] is None


def test_workflow_uses_current_ref2va_dynamic_socket_order_and_complete_links():
    workflow = load_workflow()
    ref2va = nodes_by_type(workflow)["MiniMaxH3ReferenceToVideo"]

    assert [input_["name"] for input_ in ref2va["inputs"]] == [
        "clip",
        "vae",
        "audio_vae",
        "ref_images.ref_image_0",
        "ref_videos.ref_video_0",
        "ref_video_audios.ref_video_audio_0",
        "ref_audios.ref_audio_0",
        "prompt",
        "width",
        "height",
        "length",
        "ref_image_size",
        "ref_images.ref_image_1",
        "ref_audios.ref_audio_1",
    ]
    assert_link(workflow, "H3PerformanceScenePrep", 1, "MiniMaxH3ReferenceToVideo", 7)
    assert_link(workflow, "H3PerformanceScenePrep", 2, "MiniMaxH3ReferenceToVideo", 10)

    assert all(isinstance(link, list) for link in workflow["links"])
    workflow_links = workflow["links"]
    assert len(workflow_links) == 28
    assert all(len(link) == 6 and all(value is not None for value in link[:5]) for link in workflow_links)
    assert workflow["last_link_id"] == max(link[0] for link in workflow_links) == 28
    assert sorted(link[0] for link in workflow_links) == list(range(1, 29))


def test_workflow_uses_the_required_dense_review_settings_and_exact_trim():
    workflow = load_workflow()
    typed_nodes = nodes_by_type(workflow)

    prep = typed_nodes["H3PerformanceScenePrep"]
    ref2va = typed_nodes["MiniMaxH3ReferenceToVideo"]
    sampler = typed_nodes["KSamplerSelect"]
    scheduler = typed_nodes["BasicScheduler"]
    trim = node_by_title(workflow, "Trim to editorial frames")
    mux = typed_nodes["VHS_VideoCombine"]

    assert prep["widgets_values"][:3] == [0, 124, "vocal"]
    assert ref2va["widgets_values"][1:5] == [1344, 768, 124, "max"]
    assert sampler["widgets_values"] == ["res_multistep"]
    assert scheduler["widgets_values"] == ["simple", 20, 1.0]
    assert trim["widgets_values"][:2] == [0, 124]
    assert mux["widgets_values"]["frame_rate"] == 24
    assert "attention" not in json.dumps(workflow).lower()


def test_workflow_appends_one_duplicate_frame_only_for_sample_exact_muxing():
    workflow = load_workflow()
    trim = node_by_title(workflow, "Trim to editorial frames")
    last_frame = node_by_title(workflow, "Duplicate final frame for mux boundary")
    append = node_by_title(workflow, "Append mux boundary frame")
    mux = nodes_by_type(workflow)["VHS_VideoCombine"]
    workflow_link_set = links(workflow)

    assert last_frame["type"] == "ImageFromBatch"
    assert last_frame["widgets_values"] == [-1, 1]
    assert append["type"] == "ImageBatch"
    assert (trim["id"], 0, last_frame["id"], 0) in workflow_link_set
    assert (trim["id"], 0, append["id"], 0) in workflow_link_set
    assert (last_frame["id"], 0, append["id"], 1) in workflow_link_set
    assert (append["id"], 0, mux["id"], 0) in workflow_link_set
    assert (trim["id"], 0, mux["id"], 0) not in workflow_link_set
    assert mux["widgets_values"]["trim_to_audio"] is True
    serialized_links = [link["value"] if isinstance(link, dict) else link for link in workflow["links"]]
    assert workflow["last_link_id"] == max(link[0] for link in serialized_links)


def test_workflow_uses_current_vhs_object_widget_schema_without_value_shifting():
    mux = nodes_by_type(load_workflow())["VHS_VideoCombine"]

    assert mux["widgets_values"] == {
        "frame_rate": 24,
        "loop_count": 0,
        "filename_prefix": "review/h3_performance_scene_prep_vocal",
        "format": "video/ffv1-mkv",
        "level": "3",
        "coder": "1",
        "context": "1",
        "gop_size": 1,
        "slices": "16",
        "slicecrc": "1",
        "pix_fmt": "rgba64le",
        "save_metadata": True,
        "trim_to_audio": True,
        "pingpong": False,
        "save_output": True,
        "videopreview": {"hidden": False, "paused": False, "params": {}},
    }


def test_workflow_and_docs_require_lossless_exact_audio_muxing():
    workflow = load_workflow()
    mux = nodes_by_type(workflow)["VHS_VideoCombine"]
    readme = (ROOT / "README.md").read_text(encoding="utf-8")

    assert mux["widgets_values"]["format"] == "video/ffv1-mkv"
    assert mux["widgets_values"]["trim_to_audio"] is True
    assert "FFV1" in readme
    assert "FLAC" in readme
    assert "sample-exact" in readme


def test_workflow_is_fictional_and_has_no_local_paths_or_private_identifiers():
    text = WORKFLOW.read_text(encoding="utf-8")
    lower = text.lower()

    assert "placeholder_identity.png" in text
    assert "placeholder_master.wav" in text
    assert "C" + ":" + "\\" not in text
    assert "/users/" not in lower
    assert "ju" "lian" not in lower
    assert "ve" "x" not in lower
    assert "<audio 1>" not in lower


def test_validator_accepts_complete_catalog_and_rejects_missing_guide(tmp_path: Path):
    complete_catalog = tmp_path / "complete.json"
    missing_guide_catalog = tmp_path / "missing-guide.json"
    required = [node["type"] for node in load_workflow()["nodes"]]
    complete_catalog.write_text(json.dumps({name: {} for name in required}), encoding="utf-8")
    missing_guide_catalog.write_text(
        json.dumps({name: {} for name in required if name != "MiniMaxH3TimelineAudioGuide"}),
        encoding="utf-8",
    )

    success = subprocess.run(
        [sys.executable, str(VALIDATOR), str(WORKFLOW), "--object-info", complete_catalog.as_uri()],
        text=True,
        capture_output=True,
        check=False,
    )
    missing = subprocess.run(
        [sys.executable, str(VALIDATOR), str(WORKFLOW), "--object-info", missing_guide_catalog.as_uri()],
        text=True,
        capture_output=True,
        check=False,
    )

    assert success.returncode == 0, success.stderr
    assert missing.returncode != 0
    assert GUIDE_MISSING_MESSAGE in missing.stderr


def test_validator_accepts_modern_vhs_widget_object_without_crashing():
    spec = importlib.util.spec_from_file_location("validate_workflow", VALIDATOR)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    workflow = load_workflow()
    nodes_by_type(workflow)["VHS_VideoCombine"]["widgets_values"] = {
        "frame_rate": 24,
        "loop_count": 0,
        "filename_prefix": "review/h3_performance_scene_prep_vocal",
        "format": "video/ffv1-mkv",
        "level": "3",
        "coder": "1",
        "context": "1",
        "gop_size": 1,
        "slices": "16",
        "slicecrc": "1",
        "pix_fmt": "rgba64le",
        "save_metadata": True,
        "trim_to_audio": True,
        "pingpong": False,
        "save_output": True,
    }

    assert module.validate_structure(workflow) == []


def test_validator_reports_malformed_workflow_without_a_traceback(tmp_path: Path):
    malformed = tmp_path / "malformed.json"
    workflow = load_workflow()
    del workflow["links"]
    malformed.write_text(json.dumps(workflow), encoding="utf-8")

    result = subprocess.run(
        [sys.executable, str(VALIDATOR), str(malformed)],
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode != 0
    assert "workflow structure" in result.stderr.lower()
    assert "traceback" not in result.stderr.lower()


def test_validator_rejects_wrapped_link_records_as_invalid_structure():
    spec = importlib.util.spec_from_file_location("validate_workflow_wrapped_links", VALIDATOR)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    workflow = load_workflow()
    workflow["links"][0] = {"value": workflow["links"][0], "Count": 6}

    assert module.validate_structure(workflow) == [
        "invalid workflow structure: every link must be a six-field array"
    ]


def test_validator_reports_non_object_workflow_without_a_traceback(tmp_path: Path):
    malformed = tmp_path / "array.json"
    malformed.write_text("[]", encoding="utf-8")

    result = subprocess.run(
        [sys.executable, str(VALIDATOR), str(malformed)],
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode != 0
    assert "workflow structure" in result.stderr.lower()
    assert "traceback" not in result.stderr.lower()


def test_catalog_fetch_uses_a_bounded_timeout(monkeypatch):
    spec = importlib.util.spec_from_file_location("validate_workflow_timeout", VALIDATOR)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    calls = []

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def read(self):
            return b"{}"

    def fake_urlopen(location, **kwargs):
        calls.append((location, kwargs))
        return Response()

    monkeypatch.setattr(module, "urlopen", fake_urlopen)

    assert module.load_catalog("http://127.0.0.1:8188/object_info") == {}
    assert calls == [("http://127.0.0.1:8188/object_info", {"timeout": 10})]


def test_node_registration_does_not_depend_on_the_external_guide_package():
    root = importlib.import_module("__init__")

    assert "H3PerformanceScenePrep" in root.NODE_CLASS_MAPPINGS
