from .fixture import FIXTURE_BODY, FIXTURE_TEXT, build_json_body, generate_text
from .runtime import evaluate_resource_guard

__all__ = [
    "FIXTURE_BODY",
    "FIXTURE_TEXT",
    "build_json_body",
    "build_profile",
    "evaluate_resource_guard",
    "generate_text",
]


def __getattr__(name: str):
    if name == "build_profile":
        from .package import build_profile
        return build_profile
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
