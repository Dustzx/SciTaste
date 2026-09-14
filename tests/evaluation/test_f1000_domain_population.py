from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest

from scitaste.evaluation.f1000_domain_population import (
    F1000DomainAcquisitionPlan,
    F1000DomainStratum,
    F1000HTTPResponse,
    acquire_f1000_domain_sources,
    load_f1000_domain_acquisition_receipt,
    materialize_f1000_taste_population,
    publish_f1000_taste_population_run,
)
from scitaste.generative_ui import (
    ProjectProgressQuery,
    WorkspaceIntentResolver,
    WorkspaceSurfaceFactory,
)
from scitaste.project import ProjectManifest, ProjectRuntime


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


def test_f1000_acquisition_requires_explicit_network_switch(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="explicit network-download switch"):
        acquire_f1000_domain_sources(
            _plan(),
            output_dir=tmp_path / "acquisition",
            allow_network_download=False,
            transport=_RecordedF1000(),
        )
