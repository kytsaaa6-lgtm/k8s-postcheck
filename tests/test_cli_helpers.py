"""CLI 헬퍼(_build_context, severity 파싱, 레지스트리) 테스트."""

from __future__ import annotations

from k8s_postcheck.checks import REGISTRY, available_checks
from k8s_postcheck.cli import SEVERITY_FROM_STR, _build_context
from k8s_postcheck.models import Severity


def _ctx(**over):
    base = dict(
        expected_nodes=None,
        expected_releases=None,
        helm_namespaces=None,
        required_components=None,
        skip_components=None,
        cert_warn_days=30,
        cert_error_days=7,
        minio_url=None,
        velero_namespace="velero",
    )
    base.update(over)
    return _build_context(**base)


def test_build_context_defaults():
    ctx = _ctx()
    assert ctx["helm_namespaces"] == ["default", "kube-system"]
    assert ctx["expected_releases"] == []
    assert ctx["required_components"] == {}
    assert ctx["velero_namespace"] == "velero"


def test_build_context_extra_does_not_override_reserved():
    ctx = _ctx(
        velero_namespace="velero",
        extra={"velero_namespace": "HACKED", "custom_key": "kept"},
    )
    # 이미 존재하는 키는 extra 가 덮어쓰지 않는다.
    assert ctx["velero_namespace"] == "velero"
    # 새로운 키는 추가된다.
    assert ctx["custom_key"] == "kept"


def test_severity_from_str_mapping():
    assert SEVERITY_FROM_STR["critical"] == Severity.CRITICAL
    assert SEVERITY_FROM_STR["ok"] == Severity.OK
    assert set(SEVERITY_FROM_STR) == {"ok", "info", "warn", "error", "critical"}


def test_registry_has_all_six_checks():
    names = available_checks()
    assert set(names) == {"nodes", "system_pods", "helm_releases", "certs", "velero", "etcd"}
    for fn in REGISTRY.values():
        assert callable(fn)
