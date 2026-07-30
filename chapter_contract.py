import hashlib
import json
import os
from enum import Enum
from pathlib import Path


class SegmentationMode(str, Enum):
    """Stable, browser-facing segmentation choices."""

    STANDARD = "standard"
    GPT_5_6_LAYOUT = "gpt-5.6-layout"


class AccessPolicy(str, Enum):
    PUBLIC = "public"
    AUTHENTICATED = "authenticated"


def normalize_source_url(source_url: str) -> str:
    """Preserve the API's historical cache normalization behavior."""

    return source_url.split("?", 1)[0]


def chapter_cache_key(source_url: str, mode: SegmentationMode) -> str:
    normalized_url = normalize_source_url(source_url)
    if mode is SegmentationMode.STANDARD:
        # Standard deliberately retains the legacy hash so existing links and
        # cached results remain valid.
        identity = normalized_url
    else:
        identity = f"{normalized_url}\n{mode.value}"
    return hashlib.md5(identity.encode()).hexdigest()


def access_policy_for(mode: SegmentationMode) -> AccessPolicy:
    if mode is SegmentationMode.STANDARD:
        return AccessPolicy.PUBLIC
    return AccessPolicy.AUTHENTICATED


def detector_options_for(mode: SegmentationMode) -> dict:
    """Translate a product mode to server-owned detector configuration.

    Provider model identifiers only come from server environment variables;
    API callers cannot select or submit them.
    """

    options = {
        "debug": False,
        "progress": False,
        "rtl": True,
        "min_panel_size_ratio": False,
        "panel_llm_mode": "off",
    }
    if mode is SegmentationMode.GPT_5_6_LAYOUT:
        options["panel_llm_mode"] = "always"
        configured_model = os.environ.get("PANEL_LLM_MODEL")
        if configured_model:
            options["panel_llm_model"] = configured_model
    return options


def metadata_for(mode: SegmentationMode) -> dict:
    return {
        "segmentation_mode": mode.value,
        "access_policy": access_policy_for(mode).value,
    }


def write_metadata(result_directory: Path, mode: SegmentationMode) -> None:
    with (result_directory / "metadata.json").open("w") as metadata_file:
        json.dump(metadata_for(mode), metadata_file)


def read_metadata(result_directory: Path) -> dict:
    metadata_path = result_directory / "metadata.json"
    if not metadata_path.exists():
        # Results created before segmentation modes were introduced are
        # Standard results and retain their public-link behavior.
        return metadata_for(SegmentationMode.STANDARD)

    with metadata_path.open() as metadata_file:
        payload = json.load(metadata_file)
    mode = SegmentationMode(payload["segmentation_mode"])
    expected_policy = access_policy_for(mode)
    policy = AccessPolicy(payload["access_policy"])
    if policy is not expected_policy:
        raise ValueError("chapter metadata has an invalid access policy")
    return {
        "segmentation_mode": mode.value,
        "access_policy": policy.value,
    }
