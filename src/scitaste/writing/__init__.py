"""Evidence-grounded narrative, writing contracts, drafting, and critics."""

from scitaste.writing.argument import (
    ClaimPresentationContract,
    EvidenceCarrierContract,
    MaterialLimitationContract,
    PaperArgumentAssessment,
    PaperArgumentContract,
    PaperArgumentGap,
    PaperEntryPointContract,
    SectionDeliveryContract,
    assess_paper_argument,
)
from scitaste.writing.critics import WritingCriticSuite
from scitaste.writing.drafter import ContractDrafter
from scitaste.writing.narrative import NarrativeTasteReview, review_narrative
from scitaste.writing.semantic import WritingTasteNode, writing_node_types
from scitaste.writing.semantic_models import (
    MaterialWritingLimitation,
    SemanticWritingTasteFinding,
    WritingRevisionAction,
    WritingTasteReviewProposal,
    WritingTasteSectionInput,
    WritingTasteSemanticInput,
)
from scitaste.writing.taste import (
    WritingTasteAssessment,
    WritingTasteDimension,
    WritingTasteFinding,
    assess_writing_taste,
)

__all__ = [
    "ClaimPresentationContract",
    "ContractDrafter",
    "EvidenceCarrierContract",
    "MaterialLimitationContract",
    "MaterialWritingLimitation",
    "NarrativeTasteReview",
    "PaperArgumentAssessment",
    "PaperArgumentContract",
    "PaperArgumentGap",
    "PaperEntryPointContract",
    "SectionDeliveryContract",
    "SemanticWritingTasteFinding",
    "WritingCriticSuite",
    "WritingRevisionAction",
    "WritingTasteAssessment",
    "WritingTasteDimension",
    "WritingTasteFinding",
    "WritingTasteNode",
    "WritingTasteReviewProposal",
    "WritingTasteSectionInput",
    "WritingTasteSemanticInput",
    "assess_paper_argument",
    "assess_writing_taste",
    "review_narrative",
    "writing_node_types",
]
