"""report 렌더러(JSON/Markdown) 및 모델 집계 테스트."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from k8s_postcheck.models import CheckResult, Finding, PostCheckReport, Severity
from k8s_postcheck.report import to_json, to_markdown


def _report() -> PostCheckReport:
    rep = PostCheckReport(cluster="test-cluster")
    rep.context = {"tool_version": "9.9.9"}

    nodes = CheckResult(name="nodes")
    nodes.findings.append(Finding(check="nodes", severity=Severity.INFO, title="노드 3개"))

    etcd = CheckResult(name="etcd")
    etcd.findings.append(
        Finding(
            check="etcd",
            severity=Severity.CRITICAL,
            title="etcd Pod 없음",
            detail="component=etcd 조회 결과 없음",
            suggestion="kubelet 상태 확인",
        )
    )
    rep.results.extend([nodes, etcd])
    rep.finished_at = datetime.now(timezone.utc)
    return rep


def test_worst_severity_aggregation():
    rep = _report()
    assert rep.results[0].worst_severity == Severity.INFO
    assert rep.results[1].worst_severity == Severity.CRITICAL
    assert rep.worst_severity == Severity.CRITICAL


def test_empty_result_is_ok():
    assert CheckResult(name="x").worst_severity == Severity.OK
    assert PostCheckReport(cluster="c").worst_severity == Severity.OK


def test_to_json_roundtrip(tmp_path: Path):
    rep = _report()
    out = tmp_path / "r.json"
    to_json(rep, out)
    payload = json.loads(out.read_text(encoding="utf-8"))
    assert payload["cluster"] == "test-cluster"
    assert payload["worst_severity"] == "critical"
    names = {r["name"] for r in payload["results"]}
    assert names == {"nodes", "etcd"}


def test_to_markdown_lists_notable_only(tmp_path: Path):
    rep = _report()
    out = tmp_path / "r.md"
    to_markdown(rep, out)
    text = out.read_text(encoding="utf-8")
    assert "# k8s-postcheck Report" in text
    # WARN 이상만 상세에 노출 → CRITICAL etcd 는 있고, INFO nodes 상세는 없음
    assert "etcd Pod 없음" in text
    assert "노드 3개" not in text
    # 요약 표에는 두 체크가 모두 있어야 함
    assert "| nodes |" in text
    assert "| etcd |" in text
