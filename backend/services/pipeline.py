from dataclasses import dataclass


@dataclass(frozen=True)
class Pipeline:
    name: str
    page_images: bool = False
    structured_evidence: bool = False


PIPELINES = {
    "baseline": Pipeline("baseline"),
    "improved": Pipeline("improved", structured_evidence=True),
}
DEFAULT_PIPELINE = "improved"


def get_pipeline(name: str | None = None) -> Pipeline:
    chosen = name or DEFAULT_PIPELINE
    try:
        return PIPELINES[chosen]
    except KeyError:
        raise ValueError(f"Unknown extraction pipeline {chosen!r}.") from None
