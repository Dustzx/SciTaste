"""Completeness planning must not silently turn into an efficacy study."""

from scitaste.model_nodes.research_design import (
    ResearchDesignInput,
    ResearchDesignNode,
    ResearchDesignProposal,
    WorkflowCompletionStep,
)


def test_completion_requires_known_work_item():
    inputs = ResearchDesignInput(
        idea_sha256="a" * 64,
        idea={},
        capabilities={},
        evidence={},
        objective="Complete the workflow",
        planning_priority="completeness-first",
        workflow_gaps={"task-provisioning": "Connect real CPU/API execution"},
    )
    # Isolate priority admission from unrelated study-schema requirements.
    proposal = ResearchDesignProposal.model_construct(
        idea_sha256="a" * 64,
        hypotheses=(),
        comparisons=(),
        studies=(),
        next_study_id="future-study",
        evidence_ids=(),
    )

    def reject(candidate):
        return ResearchDesignNode()._proposal_rejections(
            candidate,
            input_data=inputs,
            context=None,
            policy=None,
        )

    assert "Completeness-first requires an explicit supplied workflow gap" in reject(proposal)
    step = WorkflowCompletionStep(
        workflow_gap_id="task-provisioning",
        implementation_action="Connect the executor",
        completion_evidence="Real terminal artifacts, including failed outcomes",
    )
    connected = proposal.model_copy(update={"next_work_item": step})
    assert reject(connected) == ["Next study is absent from design"]
    unknown = step.model_copy(update={"workflow_gap_id": "invented-efficacy-gate"})
    assert "Next work item references an unknown workflow gap" in reject(
        proposal.model_copy(update={"next_work_item": unknown})
    )


def test_completion_can_bind_declared_native_validation_without_authorizing_it():
    from scitaste.model_nodes.research_design import (
        DesignTaskSelection,
        PlannedComparison,
        PlannedStudy,
        StudyHypothesis,
        WorkflowValidation,
    )

    inputs = ResearchDesignInput(
        idea_sha256="a" * 64,
        idea={},
        capabilities={"scitaste-native-workspace": "bounded"},
        evidence={},
        objective="Finish integration",
        planning_priority="completeness-first",
        workflow_gaps={"integration": "Join retained stages"},
        task_options={"declared": {"executor_id": "scitaste-native-workspace"}},
    )
    proposal = ResearchDesignProposal(
        idea_sha256="a" * 64,
        central_question="Can the integration deliver?",
        hypotheses=(
            StudyHypothesis(
                hypothesis_id="h", prediction="Bound outputs", falsification="Missing links"
            ),
        ),
        comparisons=(
            PlannedComparison(
                comparison_id="c",
                role="validity-control",
                treatment="Delivered stage",
                comparator="Declared input contract",
                matched_information_and_budget="Retained assets only",
                availability="available",
            ),
        ),
        studies=(
            PlannedStudy(
                study_id="s",
                question="Does delivery bind the selected task?",
                hypothesis_ids=("h",),
                comparison_ids=("c",),
                research_paradigm="training-free",
                task_sampling_and_split="One declared development task",
                primary_outcome="Artifact linkage",
                analysis_and_uncertainty="No efficacy inference",
                success_and_null_interpretation="No superiority needed",
                stopping_rule="One bounded delivery",
                required_models_data_and_compute="Declared assets",
                executor_id="scitaste-native-workspace",
                execution_gaps=(),
                leakage_and_confounds=("Not scientific evidence",),
            ),
        ),
        next_study_id="s",
        selection_reason="Complete integration",
        evidence_ids=(),
        unresolved_questions=(),
        next_work_item=WorkflowCompletionStep(
            workflow_gap_id="integration",
            implementation_action="Deliver selected task",
            completion_evidence="Bound artifacts",
            validation=WorkflowValidation(study_id="s", completion_observations=("Bound outputs",)),
        ),
        task_selection=DesignTaskSelection(
            task_option_id="declared", study_id="s", comparison_id="c", comparison_arm="treatment"
        ),
    )
    node = ResearchDesignNode()
    assert node._proposal_rejections(proposal, input_data=inputs, context=None, policy=None) == []
    assert proposal.execution_authorized is False
    missing = proposal.model_copy(
        update={"next_work_item": proposal.next_work_item.model_copy(update={"validation": None})}
    )
    assert (
        "Deferred scientific study cannot replace workflow completion"
        in node._proposal_rejections(missing, input_data=inputs, context=None, policy=None)
    )
