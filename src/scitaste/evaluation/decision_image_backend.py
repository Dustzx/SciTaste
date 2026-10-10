"""Send bound pre-decision images to an OpenAI-compatible decision model."""

from __future__ import annotations

import base64
import hashlib
from pathlib import Path
from typing import ClassVar

from pydantic import JsonValue

from scitaste.evaluation.decision_method_comparison import (
    DecisionMethodRequest,
    verify_visible_evidence_artifacts,
)
from scitaste.model_nodes.models import StructuredModelRequest
from scitaste.model_nodes.openai_compatible import (
    StructuredHTTPTransport,
    StructuredOpenAICompatibleBackend,
    StructuredOpenAICompatibleConfig,
)


class ImageEvidenceDecisionBackend(StructuredOpenAICompatibleBackend):
    """Preserve the text request and attach its exact, hash-bound image bytes.

    No image sampling, resizing, OCR, or outcome-file discovery happens here.
    Unsupported media fail before provider contact rather than disappearing
    from a supposedly equal-information comparison.
    """

    supports_evidence_artifacts = True
    evidence_transport_manifest: ClassVar[dict[str, JsonValue]] = {
        "version": "decision-images-v1",
        "detail": "auto",
        "max_images": 8,
        "max_image_bytes": 8 * 1024 * 1024,
        "max_total_bytes": 16 * 1024 * 1024,
        "media_types": ["image/jpeg", "image/png", "image/webp"],
    }

    def __init__(
        self,
        config: StructuredOpenAICompatibleConfig,
        *,
        evidence_root: Path,
        transport: StructuredHTTPTransport | None = None,
    ) -> None:
        super().__init__(config, transport=transport)
        self.evidence_root = evidence_root.resolve(strict=True)
        if not self.evidence_root.is_dir():
            raise ValueError("image evidence root must be a directory")

    def _payload(
        self,
        request: StructuredModelRequest,
        *,
        config: StructuredOpenAICompatibleConfig,
    ) -> dict[str, JsonValue]:
        decision = DecisionMethodRequest.model_validate(request.input_payload.get("decision"))
        payload = super()._payload(request, config=config)
        artifacts = decision.evidence_artifacts
        if not artifacts:
            return payload
        if len(artifacts) > 8 or sum(item.size_bytes for item in artifacts) > 16 * 1024 * 1024:
            raise ValueError("decision image evidence exceeds the transport budget")
        if any(
            item.media_type not in {"image/jpeg", "image/png", "image/webp"}
            or item.size_bytes > 8 * 1024 * 1024
            for item in artifacts
        ):
            raise ValueError("unsupported decision evidence media type or image size")
        paths = verify_visible_evidence_artifacts(decision, artifact_root=self.evidence_root)
        messages = payload["messages"]
        assert isinstance(messages, list) and isinstance(messages[-1], dict)
        content: list[JsonValue] = [{"type": "text", "text": messages[-1]["content"]}]
        for artifact, path in zip(artifacts, paths, strict=True):
            with path.open("rb") as stream:
                data = stream.read(artifact.size_bytes + 1)
            if (
                len(data) != artifact.size_bytes
                or hashlib.sha256(data).hexdigest() != artifact.sha256
            ):
                raise ValueError("decision image changed during loading")
            detected = (
                "image/png"
                if data.startswith(b"\x89PNG\r\n\x1a\n")
                else "image/jpeg"
                if data.startswith(b"\xff\xd8\xff")
                else "image/webp"
                if data[:4] == b"RIFF" and data[8:12] == b"WEBP"
                else None
            )
            if detected != artifact.media_type:
                raise ValueError("decision image bytes disagree with the declared media type")
            encoded = base64.b64encode(data).decode("ascii")
            content.extend(
                [
                    {"type": "text", "text": f"Evidence artifact: {artifact.artifact_id}"},
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:{artifact.media_type};base64,{encoded}",
                            "detail": "auto",
                        },
                    },
                ]
            )
        messages[-1]["content"] = content
        return payload
