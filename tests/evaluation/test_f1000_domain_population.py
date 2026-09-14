from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest
import yaml

from scitaste.evaluation.f1000_domain_population import (
    F1000DomainAcquisitionPlan,
    F1000DomainStratum,
    F1000HTTPResponse,
    acquire_f1000_domain_sources,
    load_f1000_domain_acquisition_receipt,
    materialize_f1000_taste_population,
    publish_f1000_taste_population_run,
)
from scitaste.evaluation.natural_taste_review import (
    TasteSourceReviewSession,
    load_taste_source_review_policy,
    prepare_taste_source_review_campaign,
    publish_taste_source_review_campaign_run,
)
from scitaste.generative_ui import (
    GenerativeUIApplication,
    ProjectProgressQuery,
    WorkspaceIntentResolver,
    WorkspaceSurfaceFactory,
)
from scitaste.project import ProjectManifest, ProjectRuntime
from scitaste.taste.intrinsic import TasteTask
from scitaste.taste.reference_quality import ReferenceQualityDimension


class _RecordedF1000:
    def __init__(self) -> None:
        self.urls: list[str] = []

    def get(self, url, *, headers, timeout, maximum_bytes):  # type: ignore[no-untyped-def]
        del headers, timeout
        self.urls.append(url)
        query = parse_qs(urlsplit(url).query)
        if urlsplit(url).path == "/extapi/search":
            domain = "ecology" if "Ecology" in query["q"][0] else "public-health"
            offset = 100 if domain == "ecology" else 200
            rows = "".join(
                (
                    f"<doi>10.12688/f1000research.{offset + index}.v2</doi>"
                    if domain == "ecology"
                    else f"<doi>10.12688/f1000research.{offset + index}.2</doi>"
                )
                for index in range(1, 8)
            )
            body = (
                '<?xml version="1.0"?><results numberOfResultsInPage="7" '
                f'totalNumberOfPages="1">{rows}</results>'
            ).encode()
        else:
            doi = query["doi"][0]
            version = int(doi.rsplit(".", 1)[1].removeprefix("v"))
            body = _article_xml(doi, version).encode()
        assert len(body) <= maximum_bytes
        return F1000HTTPResponse(
            status_code=200,
            url=url,
            headers={"content-type": "application/xml"},
            body=body,
        )


def _article_xml(doi: str, version: int) -> str:
    base = doi.rsplit(".", 1)[0]
    reviewed_doi = f"{base}.v1" if doi.rsplit(".", 1)[1].startswith("v") else f"{base}.1"
    report = ""
    if version == 2:
        report = f"""
        <sub-article article-type="reviewer-report" id="report-{base.rsplit('.', 1)[1]}">
          <front-stub>
            <permissions><license xlink:href="https://creativecommons.org/licenses/by/4.0/"/></permissions>
            <related-article xlink:href="{reviewed_doi}"/>
            <custom-meta-group><custom-meta>
              <meta-name>recommendation</meta-name>
              <meta-value>approve-with-reservations</meta-value>
            </custom-meta></custom-meta-group>
          </front-stub>
          <body><p>Compare the registered alternative and report uncertainty.</p></body>
          <sub-article article-type="response" id="response-1">
            <front-stub><contrib-group><contrib><name><surname>Hidden</surname></name></contrib></contrib-group></front-stub>
            <body><p>We added the requested comparator and confidence interval.</p></body>
          </sub-article>
        </sub-article>
        """
    return f"""<?xml version="1.0"?>
    <article xmlns:xlink="http://www.w3.org/1999/xlink" article-type="research-article">
      <front><article-meta>
        <article-id pub-id-type="doi">{doi}</article-id>
        <title-group><article-title>Bounded study version {version}</article-title></title-group>
        <abstract><p>We compare two interventions in a natural scientific setting.</p></abstract>
        <permissions><license xlink:href="https://creativecommons.org/licenses/by/4.0/"/></permissions>
      </article-meta></front>
      <body><p>Article body.</p></body>
      {report}
    </article>"""


def _plan() -> F1000DomainAcquisitionPlan:
    search_ceiling = 2 * 16_384
    article_ceiling = 20 * 65_536
    return F1000DomainAcquisitionPlan(
        acquisition_id="f1000-test-pilot",
        project_id="f1000-test-project",
        strata=(
            F1000DomainStratum(
                domain_id="ecology",
                subject_query="Ecology",
                expected_page_count=1,
                target_source_groups=5,
            ),
            F1000DomainStratum(
                domain_id="public-health",
                subject_query="Public Health",
                expected_page_count=1,
                target_source_groups=5,
            ),
        ),
        selection_salt="fixed-selection-salt-v1",
        per_search_response_max_bytes=16_384,
        per_article_xml_max_bytes=65_536,
        maximum_total_bytes=search_ceiling + article_ceiling,
        timeout_seconds=5,
        parallel_article_requests=4,
        user_agent="SciTaste-test-client/1.0",
        authorization_ref="test-owner-authorization",
        purpose="Exercise exact multidisciplinary acquisition.",
        claim_boundary="No source, recommendation, or revision is a quality label.",
    )


def test_f1000_acquisition_and_population_are_exact_and_non_gold(tmp_path: Path) -> None:
    runtime = ProjectRuntime(tmp_path / "outputs")
    snapshot = runtime.create(
        ProjectManifest(
            project_id="f1000-test-project",
            title="F1000 domain expansion",
            research_direction="Expand natural Scientific Taste source domains.",
            status="active",
        )
    )
    acquisition_root = (
        runtime.projects_root
        / snapshot.project_id
        / "evaluations/acquisitions/f1000-test-pilot"
    )
    transport = _RecordedF1000()
    acquired = acquire_f1000_domain_sources(
        _plan(),
        output_dir=acquisition_root,
        allow_network_download=True,
        transport=transport,
        acquired_at=datetime(2026, 9, 14, 12, 0, tzinfo=UTC),
    )

    receipt = load_f1000_domain_acquisition_receipt(acquired.receipt_path)
    assert receipt.request_count == 22
    assert receipt.distinct_source_group_count == 10
    assert receipt.domain_selected_counts == {"ecology": 5, "public-health": 5}
    assert receipt.cross_domain_overlap_count == 0
    assert receipt.source_content_read_for_quality is False
    assert receipt.model_calls_performed is False
    assert len(transport.urls) == 22

    report = materialize_f1000_taste_population(
        acquisition_receipt_path=acquired.receipt_path,
        output_directory=acquisition_root / "derived/taste-population-v1",
        compiled_at=datetime(2026, 9, 14, 12, 1, tzinfo=UTC),
    )

    assert report.candidate_count == 10
    assert report.candidate_source_group_count == 10
    assert report.response_observed_count == 10
    assert report.domain_source_group_counts == {"ecology": 5, "public-health": 5}
    assert report.recommendation_counts == {"approved-with-reservations": 10}
    assert report.observed_domain_count == 3
    assert report.added_domain_group_floor_met is False
    assert report.ready_for_taste_abstraction_review is False
    assert report.ready_for_benchmark_admission is False
    assert report.verification.route.value == "direct_path"
    assert report.standalone_preflight_performed is False

    candidates = (
        acquisition_root / "derived/taste-population-v1/CANDIDATES.jsonl"
    ).read_text()
    assert "Hidden" not in candidates
    assert "10.12688" not in candidates
    assert "added the requested comparator" in candidates

    snapshot, published = publish_f1000_taste_population_run(
        runtime,
        project_id="f1000-test-project",
        run_id="f1000-domain-population-v1",
        source_report_path=(
            acquisition_root / "derived/taste-population-v1/REPORT.json"
        ),
        expected_revision=snapshot.revision,
    )
    surface = WorkspaceSurfaceFactory(runtime).build_surface(
        ProjectProgressQuery(project_id="f1000-test-project")
    )
    board = next(
        component
        for component in surface.components
        if component.component == "ProjectProgressBoard"
    )
    expansion = board.data["taste_domain_expansions"][0]
    assert expansion["candidate_count"] == 10
    assert expansion["domain_source_group_counts"] == {
        "ecology": 5,
        "public_health": 5,
    }
    assert expansion["ready_for_benchmark_admission"] is False
    assert expansion["verification_route"] == "direct_path"
    catalog = WorkspaceIntentResolver(runtime).quick_catalog("f1000-test-project")
    curation = next(
        item
        for item in catalog.intents
        if item.quick_intent_id == "review-taste-candidate-population"
    )
    assert published.report_sha256 == report.report_sha256
    assert curation.target_ids == (
        "f1000-multidomain-review-response-v1",
    )
    assert snapshot.revision == 2

    tracked_policy = load_taste_source_review_policy(
        "configs/evaluation/human_review/f1000_multidomain_taste_source_review_v1.yaml"
    )
    test_policy = tracked_policy.model_copy(
        update={
            "project_id": "f1000-test-project",
            "population_id": report.population_id,
            "minimum_eligible_groups_per_domain": 5,
        }
    )
    policy_path = tmp_path / "review-policy.yaml"
    policy_path.write_text(
        yaml.safe_dump(
            test_policy.model_dump(mode="json", exclude={"policy_sha256"}),
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    campaign_root = acquisition_root / "derived/taste-source-review-v1"
    campaign = prepare_taste_source_review_campaign(
        population_report_path=acquisition_root / "derived/taste-population-v1/REPORT.json",
        policy_path=policy_path,
        output_dir=campaign_root,
        prepared_at=datetime(2026, 9, 14, 12, 2, tzinfo=UTC),
    )
    assert campaign.candidate_count == 10
    assert campaign.required_scientific_assessment_count == 20
    assert campaign.required_privacy_assessment_count == 10
    assert campaign.preparation_verification.route.value == "direct_path"
    assert campaign.recruitment_verification.route.value == "owner_approval"
    assert campaign.standalone_preflight_performed is False
    scientific_items = [
        json.loads(line)
        for line in (campaign_root / "SCIENTIFIC_ITEMS.jsonl").read_text().splitlines()
    ]
    assert all("author_response" not in item for item in scientific_items)
    assert all("revised_abstract" not in item for item in scientific_items)
    assert all("observed_recommendation" not in item for item in scientific_items)
    assert (campaign_root / "POLICY.yaml").read_bytes() == policy_path.read_bytes()

    snapshot, _ = publish_taste_source_review_campaign_run(
        runtime,
        project_id="f1000-test-project",
        run_id="f1000-source-review-v1",
        source_campaign_path=campaign_root / "CAMPAIGN.json",
        expected_revision=snapshot.revision,
    )
    board = next(
        component
        for component in WorkspaceSurfaceFactory(runtime)
        .build_surface(ProjectProgressQuery(project_id="f1000-test-project"))
        .components
        if component.component == "ProjectProgressBoard"
    )
    review = board.data["taste_source_review_campaigns"][0]
    assert review["scientific_assessment_count"] == 20
    assert review["privacy_assessment_count"] == 10
    assert review["preparation_verification_route"] == "direct_path"
    assert review["recruitment_verification_route"] == "owner_approval"
    assert board.data["counts"]["taste_source_review_campaigns"] == 1
    assert snapshot.revision == 4

    app = GenerativeUIApplication(runtime)
    pending = app.current_taste_source_review_control(
        "f1000-test-project",
        campaign.campaign_id,
    )
    assert pending.status == "awaiting_owner_approval"
    assert pending.owner_approval_required is True
    authorization_request = {
        "schema_version": "1.0",
        "project_id": "f1000-test-project",
        "campaign_id": campaign.campaign_id,
        "campaign_sha256": campaign.campaign_sha256,
        "expected_project_revision": snapshot.revision,
        "expected_snapshot_sha256": snapshot.snapshot_sha256,
        "owner_alias": "test-owner",
        "scientific_reviewer_aliases": ["reviewer-a", "reviewer-b"],
        "privacy_reviewer_alias": "reviewer-privacy",
        "ethics_status": "not-required",
        "ethics_determination_ref": "test-only synthetic determination",
        "maximum_reviewer_hours": 3,
        "compensation_terms_confirmed": True,
        "consent_terms_confirmed": True,
        "retention_and_withdrawal_terms_confirmed": True,
        "conflicts_screened": True,
        "confirm_prepare_local_sessions": True,
    }
    authorized = app.authorize_taste_source_review(
        "f1000-test-project",
        campaign.campaign_id,
        authorization_request,
    )
    assert authorized.status == "authorized_sessions_ready"
    assert authorized.project_revision == 5
    assert authorized.reviewer_sessions_prepared == 3
    assert authorized.human_contact_performed is False
    assert authorized.record is not None
    assert len({item.reviewer_identity_sha256 for item in authorized.record.sessions}) == 3
    control_root = (
        runtime.projects_root
        / "f1000-test-project/runs/f1000-source-review-v1"
        / "taste_source_review_campaign/review-control"
    )
    assert all(
        (control_root / name / "review.html").is_file()
        for name in ("scientific-1", "scientific-2", "privacy-1")
    )
    repeated = app.authorize_taste_source_review(
        "f1000-test-project",
        campaign.campaign_id,
        authorization_request,
    )
    assert repeated.record == authorized.record
    refreshed_board = next(
        component
        for component in WorkspaceSurfaceFactory(runtime)
        .build_surface(ProjectProgressQuery(project_id="f1000-test-project"))
        .components
        if component.component == "ProjectProgressBoard"
    )
    refreshed_review = refreshed_board.data["taste_source_review_campaigns"][0]
    assert refreshed_review["reviewer_sessions_prepared"] == 3
    assert refreshed_review["owner_approval_required"] is False
    assert refreshed_review["human_recruitment_performed"] is False

    private_rows = json.loads((campaign_root / "PRIVATE_ITEM_MAP.json").read_text())["items"]
    private_by_id = {item["review_item_id"]: item for item in private_rows}
    family_by_id = {
        review_item_id: list(TasteTask)[index % len(TasteTask)].value
        for index, review_item_id in enumerate(sorted(private_by_id))
    }
    started = datetime(2026, 9, 14, 12, 4, tzinfo=UTC)
    submitted = datetime(2026, 9, 14, 12, 5, tzinfo=UTC)
    session_paths = [
        control_root / name / "session.json"
        for name in ("scientific-1", "scientific-2", "privacy-1")
    ]
    sessions = [
        TasteSourceReviewSession.model_validate_json(path.read_bytes())
        for path in session_paths
    ]
    submission_payloads: list[dict[str, object]] = []
    for session in sessions:
        scientific = session.role.value == "scientific"
        common = {
            "schema_version": "1.0",
            "session_id": session.session_id,
            "session_sha256": session.session_sha256,
            "campaign_sha256": session.campaign_sha256,
            "role": session.role.value,
            "reviewer_identity_sha256": session.reviewer_identity_sha256,
            "review_started_at": started.isoformat(),
            "submitted_at": submitted.isoformat(),
            "conflict_cleared": True,
            "independent_review": True,
            "blinded_to_other_reviews": True,
            "blinded_to_publisher_subject": scientific,
            "blinded_to_observed_outcomes": scientific,
            "consent_terms_accepted": True,
            "explicit_lock_confirmed": True,
        }
        if scientific:
            common["scientific_responses"] = [
                {
                    "review_item_id": item.review_item_id,
                    "domain_label": private_by_id[item.review_item_id]["publisher_subject"],
                    "primary_decision_family": family_by_id[item.review_item_id],
                    "dimension_ratings": [
                        {"dimension": dimension.value, "rating": "strong"}
                        for dimension in ReferenceQualityDimension
                    ],
                    "transferable_taste_candidate": True,
                    "rationale": "Synthetic independent content-grounded test judgment.",
                    "duration_seconds": 60,
                }
                for item in session.items
            ]
            common["privacy_responses"] = []
        else:
            common["scientific_responses"] = []
            common["privacy_responses"] = [
                {
                    "review_item_id": item.review_item_id,
                    "release_safe": True,
                    "risk_codes": ["none"],
                    "rationale": "Synthetic de-identified test content.",
                    "duration_seconds": 30,
                }
                for item in session.items
            ]
        submission_payloads.append(common)

    for index, submission in enumerate(submission_payloads, 1):
        collected = app.collect_taste_source_review_submission(
            "f1000-test-project",
            campaign.campaign_id,
            {
                "schema_version": "1.0",
                "project_id": "f1000-test-project",
                "campaign_id": campaign.campaign_id,
                "campaign_sha256": campaign.campaign_sha256,
                "control_id": authorized.record.control_id,
                "control_sha256": authorized.record.control_sha256,
                "submission": submission,
            },
        )
        assert collected.reviewer_submissions_collected == index
        assert collected.standalone_preflight_performed is False
        assert collected.submission_verification_route.value == "direct_path"
    assert collected.status == "review_locked"
    assert collected.eligible_candidate_count == 10
    assert collected.adjudication_required_count == 0
    assert collected.ready_for_taste_abstraction_review is True
    assert collected.ready_for_benchmark_admission is False
    assert collected.result_locator == "review-control/RESULT.json"

    locked_board = next(
        component
        for component in WorkspaceSurfaceFactory(runtime)
        .build_surface(ProjectProgressQuery(project_id="f1000-test-project"))
        .components
        if component.component == "ProjectProgressBoard"
    )
    locked_review = locked_board.data["taste_source_review_campaigns"][0]
    assert locked_review["review_collection_status"] == "review_locked"
    assert locked_review["reviewer_submissions_collected"] == 3
    assert locked_review["eligible_candidate_count"] == 10
    assert locked_review["ready_for_taste_abstraction_review"] is True
    locked_catalog = WorkspaceIntentResolver(runtime).quick_catalog("f1000-test-project")
    assert any(
        item.quick_intent_id == "plan-reviewed-taste-abstraction"
        for item in locked_catalog.intents
    )


def test_f1000_acquisition_requires_explicit_network_switch(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="explicit network-download switch"):
        acquire_f1000_domain_sources(
            _plan(),
            output_dir=tmp_path / "acquisition",
            allow_network_download=False,
            transport=_RecordedF1000(),
        )
