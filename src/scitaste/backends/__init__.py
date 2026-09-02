"""Provider-neutral model backends for taste calibration and decisions."""

from scitaste.backends.base import (
    PreferenceBackend,
    PreferenceRequest,
    PreferenceResponse,
    Usage,
)
from scitaste.backends.local_transformers import (
    LocalTransformersBackend,
    LocalTransformersConfig,
    load_local_transformers_config,
)
from scitaste.backends.openai_compatible import (
    APIStyle,
    OpenAICompatibleBackend,
    OpenAICompatibleConfig,
    load_openai_compatible_config,
)
from scitaste.backends.replay import RecordingBackend, ReplayBackend, ReplayMissError
from scitaste.backends.scripted import ScriptedPreferenceBackend, ScriptedSelection

__all__ = [
    "APIStyle",
    "LocalTransformersBackend",
    "LocalTransformersConfig",
    "OpenAICompatibleBackend",
    "OpenAICompatibleConfig",
    "PreferenceBackend",
    "PreferenceRequest",
    "PreferenceResponse",
    "RecordingBackend",
    "ReplayBackend",
    "ReplayMissError",
    "ScriptedPreferenceBackend",
    "ScriptedSelection",
    "Usage",
    "load_local_transformers_config",
    "load_openai_compatible_config",
]
