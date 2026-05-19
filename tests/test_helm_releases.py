"""helm_releases 체크 유닛 테스트."""

from __future__ import annotations

import base64
import gzip
import json
from unittest.mock import MagicMock

from k8s_postcheck.checks.helm_releases import run
from k8s_postcheck.models import Severity


def _make_helm_secret(name: str, status: str, namespace: str = "default") -> MagicMock:
    """Helm 3 형식의 Secret mock 을 생성합니다."""
    payload = json.dumps({
        "name": name,
        "info": {"status": status},
        "chart": {"metadata": {"name": name, "version": "1.0.0"}},
    }).encode()
    compressed = gzip.compress(payload)
    encoded = base64.b64encode(base64.b64encode(compressed)).decode()

    secret = MagicMock()
    secret.metadata.name = f"sh.helm.release.v1.{name}.v1"
    secret.metadata.namespace = namespace
    secret.metadata.labels = {"owner": "helm", "status": status}
    secret.data = {"release": encoded}
    return secret


def test_all_deployed(mock_handle):
    mock_handle.core.list_namespaced_secret.return_value.items = [
        _make_helm_secret("cilium", "deployed"),
        _make_helm_secret("velero", "deployed", namespace="velero"),
    ]
    result = run(mock_handle, {
        "helm_namespaces": ["default", "velero"],
        "expected_releases": ["cilium", "velero"],
    })
    assert result.worst_severity in (Severity.OK, Severity.INFO)


def test_failed_release(mock_handle):
    mock_handle.core.list_namespaced_secret.return_value.items = [
        _make_helm_secret("my-app", "failed"),
    ]
    result = run(mock_handle, {"helm_namespaces": ["default"]})
    assert any("실패" in f.title for f in result.findings)
    assert result.worst_severity == Severity.ERROR


def test_missing_expected_release(mock_handle):
    mock_handle.core.list_namespaced_secret.return_value.items = []
    result = run(mock_handle, {
        "helm_namespaces": ["default"],
        "expected_releases": ["cilium"],
    })
    assert any("없음" in f.title for f in result.findings)
    assert result.worst_severity == Severity.ERROR
