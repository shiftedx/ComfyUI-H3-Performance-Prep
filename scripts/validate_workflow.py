from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from urllib.request import urlopen


GUIDE_CLASS = "MiniMaxH3TimelineAudioGuide"
GUIDE_MISSING_MESSAGE = (
    "MiniMaxH3TimelineAudioGuide is required "
    "(tested with ComfyUI-MiniMaxH3-Contex-Loop 0.3.8)"
)
REQUIRED_TYPES = {
    "LoadAudio",
    "LoadImage",
    "H3PerformanceScenePrep",
    "MiniMaxH3ReferenceToVideo",
    GUIDE_CLASS,
    "KSamplerSelect",
    "BasicScheduler",
    "BasicGuider",
    "SamplerCustomAdvanced",
    "VAEDecode",
    "ImageFromBatch",
    "ImageBatch",
    "VHS_VideoCombine",
}


def workflow_links(workflow: dict) -> set[tuple[int, int, int, int]]:
    return {
        tuple(link[1:5])
        for link in workflow["links"]
    }


def validate_structure(workflow: dict) -> list[str]:
    if not isinstance(workflow, dict):
        return ["invalid workflow structure: top level must be an object"]
    if not isinstance(workflow.get("nodes"), list):
        return ["invalid workflow structure: nodes must be an array"]
    if not isinstance(workflow.get("links"), list):
        return ["invalid workflow structure: links must be an array"]
    if any(not isinstance(node, dict) or not isinstance(node.get("type"), str) for node in workflow["nodes"]):
        return ["invalid workflow structure: every node must be an object with a type"]
    if any(
        not isinstance(link, list)
        or len(link) != 6
        for link in workflow["links"]
    ):
        return ["invalid workflow structure: every link must be a six-field array"]

    nodes = {}
    for node in workflow["nodes"]:
        nodes.setdefault(node["type"], node)
    errors = [f"missing required node type: {name}" for name in sorted(REQUIRED_TYPES - nodes.keys())]
    if errors:
        return errors

    links = workflow_links(workflow)

    def requires(source: str, source_slot: int, target: str, target_slot: int) -> None:
        if (nodes[source]["id"], source_slot, nodes[target]["id"], target_slot) not in links:
            errors.append(f"missing link: {source}[{source_slot}] -> {target}[{target_slot}]")

    def requires_input(source: str, source_slot: int, target: str, input_name: str) -> None:
        target_slots = {input_["name"]: index for index, input_ in enumerate(nodes[target].get("inputs", []))}
        if input_name not in target_slots:
            errors.append(f"missing input: {target}.{input_name}")
            return
        requires(source, source_slot, target, target_slots[input_name])

    requires("LoadAudio", 0, "H3PerformanceScenePrep", 0)
    requires_input("LoadImage", 0, "MiniMaxH3ReferenceToVideo", "ref_images.ref_image_0")
    requires_input("H3PerformanceScenePrep", 1, "MiniMaxH3ReferenceToVideo", "prompt")
    requires_input("H3PerformanceScenePrep", 2, "MiniMaxH3ReferenceToVideo", "length")
    requires_input("MiniMaxH3ReferenceToVideo", 0, GUIDE_CLASS, "conditioning")
    requires_input("H3PerformanceScenePrep", 0, GUIDE_CLASS, "audio")
    requires_input("H3PerformanceScenePrep", 2, GUIDE_CLASS, "frame_count")
    requires_input(GUIDE_CLASS, 0, "BasicGuider", "conditioning")
    requires_input("MiniMaxH3ReferenceToVideo", 1, "SamplerCustomAdvanced", "latent_image")
    titled_nodes = {node.get("title"): node for node in workflow["nodes"] if node.get("title")}
    trim = titled_nodes.get("Trim to editorial frames")
    final_frame = titled_nodes.get("Duplicate final frame for mux boundary")
    append = titled_nodes.get("Append mux boundary frame")
    if not trim or not final_frame or not append:
        errors.append("missing exact-mux trim, final-frame, or append node")
    else:
        def requires_nodes(source: dict, source_slot: int, target: dict, target_slot: int) -> None:
            if (source["id"], source_slot, target["id"], target_slot) not in links:
                source_name = source.get("title", source.get("type", "unknown node"))
                target_name = target.get("title", target.get("type", "unknown node"))
                errors.append(f"missing link: {source_name}[{source_slot}] -> {target_name}[{target_slot}]")

        requires_nodes(nodes["VAEDecode"], 0, trim, 0)
        requires_nodes(nodes["H3PerformanceScenePrep"], 3, trim, 2)
        requires_nodes(trim, 0, final_frame, 0)
        requires_nodes(trim, 0, append, 0)
        requires_nodes(final_frame, 0, append, 1)
        requires_nodes(append, 0, nodes["VHS_VideoCombine"], 0)
    requires_input("H3PerformanceScenePrep", 0, "VHS_VideoCombine", "audio")

    ref2va = nodes["MiniMaxH3ReferenceToVideo"]
    if any(input_.get("name", "").startswith("ref_audios.") and input_.get("link") is not None for input_ in ref2va.get("inputs", [])):
        errors.append("MiniMaxH3ReferenceToVideo ref_audios must be disconnected")
    if any("DecodeAudio" in node.get("type", "") for node in workflow["nodes"]):
        errors.append("the workflow must not decode generated audio")
    if any("Turbo" in node.get("type", "") or "EasyCache" in node.get("type", "") for node in workflow["nodes"]):
        errors.append("Turbo and EasyCache nodes are not permitted")

    prep = nodes["H3PerformanceScenePrep"].get("widgets_values", [])
    ref_widgets = ref2va.get("widgets_values", [])
    sampler = nodes["KSamplerSelect"].get("widgets_values", [])
    scheduler = nodes["BasicScheduler"].get("widgets_values", [])
    trim_widgets = trim.get("widgets_values", []) if trim else []
    final_frame_widgets = final_frame.get("widgets_values", []) if final_frame else []
    mux = nodes["VHS_VideoCombine"].get("widgets_values", [])
    if prep[:3] != [0, 124, "vocal"]:
        errors.append("the example must request 124 editorial frames")
    if ref_widgets[1:5] != [1344, 768, 124, "max"]:
        errors.append("Ref2VA must use 1344x768, 124 raw frames, and ref_image_size=max")
    if sampler != ["res_multistep"]:
        errors.append("KSamplerSelect must use res_multistep")
    if scheduler != ["simple", 20, 1.0]:
        errors.append("BasicScheduler must use 20 dense steps")
    if trim_widgets[:2] != [0, 124]:
        errors.append("ImageFromBatch must start at zero and trim to 124 frames")
    # One duplicate frame extends the image stream just beyond the 124-frame audio
    # boundary; VHS -shortest then retains 124 video frames and the full FLAC tail.
    if final_frame_widgets[:2] != [-1, 1]:
        errors.append("the mux boundary ImageFromBatch must duplicate the final editorial frame")
    frame_rate = mux.get("frame_rate") if isinstance(mux, dict) else (mux[0] if mux else None)
    mux_format = mux.get("format") if isinstance(mux, dict) else (mux[3] if len(mux) > 3 else None)
    trim_to_audio = mux.get("trim_to_audio") if isinstance(mux, dict) else None
    if frame_rate != 24:
        errors.append("VHS_VideoCombine must use 24 fps")
    if mux_format != "video/ffv1-mkv":
        errors.append("VHS_VideoCombine must use video/ffv1-mkv for sample-exact FLAC audio")
    if trim_to_audio is not True:
        errors.append("VHS_VideoCombine must enable trim_to_audio to prevent audio padding")

    text = json.dumps(workflow).lower()
    forbidden = ("c" + ":" + "\\", "/users/", "ju" "lian", "ve" "x", "<audio 1>")
    if any(value in text for value in forbidden):
        errors.append("workflow contains a local path, private identifier, or false audio reference")
    return errors


def load_catalog(location: str) -> dict:
    with urlopen(location, timeout=10) as response:
        return json.load(response)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate the portable H3 performance scene prep workflow.")
    parser.add_argument("workflow", type=Path)
    parser.add_argument("--object-info", help="URL or file URI for a ComfyUI /object_info catalog")
    args = parser.parse_args(argv)

    try:
        workflow = json.loads(args.workflow.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        print(f"cannot read workflow: {error}", file=sys.stderr)
        return 2

    try:
        errors = validate_structure(workflow)
    except (AttributeError, IndexError, KeyError, TypeError, ValueError) as error:
        print(f"invalid workflow structure: {error}", file=sys.stderr)
        return 1
    if args.object_info:
        try:
            catalog = load_catalog(args.object_info)
        except Exception as error:  # pragma: no cover - network failures vary by environment.
            print(f"cannot read object catalog: {error}", file=sys.stderr)
            return 2
        if GUIDE_CLASS not in catalog:
            print(GUIDE_MISSING_MESSAGE, file=sys.stderr)
            return 1
        missing = sorted(set(node["type"] for node in workflow["nodes"]) - set(catalog))
        if missing:
            errors.append("object catalog is missing: " + ", ".join(missing))

    if errors:
        print("\n".join(errors), file=sys.stderr)
        return 1
    print("workflow validation passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
