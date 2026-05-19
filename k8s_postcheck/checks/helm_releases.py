"""Helm 릴리스 상태 체크.

Helm 3 는 릴리스 정보를 쿠버네티스 Secret 으로 저장합니다:
  label: owner=helm, status=deployed  (최신 revision)
  데이터: release 키 = base64(gzip(JSON))

Secret 을 직접 디코딩해서 helm CLI 없이도 릴리스 상태를 확인합니다.
"""

from __future__ import annotations

import base64
import gzip
import json

from ..auth import K8sHandle
from ..models import CheckResult, Finding, Severity
from ._util import timed

HEALTHY_STATUSES = {"deployed", "superseded"}
FAILED_STATUSES = {"failed", "uninstalling"}
PENDING_STATUSES = {"pending-install", "pending-upgrade", "pending-rollback"}


def _decode_release(data: bytes) -> dict:
    """Helm Secret 의 release 필드를 디코딩합니다."""
    # Helm 3: base64 → base64 → gzip → JSON (이중 인코딩)
    try:
        first = base64.b64decode(data)
        second = base64.b64decode(first)
        return json.loads(gzip.decompress(second))
    except Exception:
        pass
    # 단순 base64 → gzip → JSON
    try:
        return json.loads(gzip.decompress(base64.b64decode(data)))
    except Exception:
        pass
    return {}


def _list_releases(handle: K8sHandle, namespaces: list[str]) -> list[dict]:
    """지정 네임스페이스에서 모든 Helm 릴리스를 수집합니다."""
    releases: list[dict] = []
    for ns in namespaces:
        try:
            secrets = handle.core.list_namespaced_secret(
                namespace=ns,
                label_selector="owner=helm",
            ).items
        except Exception:
            continue
        for secret in secrets:
            raw = (secret.data or {}).get("release")
            if not raw:
                continue
            try:
                rel = _decode_release(raw.encode() if isinstance(raw, str) else raw)
            except Exception:
                rel = {}
            name = (rel.get("name") or secret.metadata.name or "?")
            chart = rel.get("chart", {})
            chart_name = chart.get("metadata", {}).get("name", "") if isinstance(chart, dict) else ""
            chart_version = chart.get("metadata", {}).get("version", "") if isinstance(chart, dict) else ""
            info = rel.get("info", {}) if isinstance(rel.get("info"), dict) else {}
            status = info.get("status", secret.metadata.labels.get("status", "?"))
            releases.append({
                "name": name,
                "namespace": ns,
                "chart": f"{chart_name}-{chart_version}" if chart_version else chart_name,
                "status": status,
                "secret": secret.metadata.name,
            })
    return releases


def run(handle: K8sHandle, ctx: dict) -> CheckResult:
    helm_namespaces: list[str] = ctx.get("helm_namespaces", ["default", "kube-system"])
    expected_releases: list[str] = ctx.get("expected_releases", [])

    with timed("helm_releases") as result:
        releases = _list_releases(handle, helm_namespaces)

        result.findings.append(
            Finding(
                check="helm_releases",
                severity=Severity.INFO,
                title="Helm 릴리스 수집",
                detail=(
                    f"전체 {len(releases)}개 "
                    f"({', '.join(helm_namespaces)} 네임스페이스)"
                ),
            )
        )

        release_names = {r["name"] for r in releases}

        for rel in releases:
            status = rel["status"].lower()
            name = rel["name"]
            ns = rel["namespace"]
            chart = rel["chart"]

            if status in FAILED_STATUSES:
                result.findings.append(
                    Finding(
                        check="helm_releases",
                        severity=Severity.ERROR,
                        title=f"Helm 릴리스 실패: {name}",
                        detail=f"status={status}, chart={chart}, namespace={ns}",
                        resource=f"{ns}/{name}",
                        suggestion=(
                            f"`helm status {name} -n {ns}` 및 "
                            f"`helm history {name} -n {ns}` 로 실패 원인을 확인하세요."
                        ),
                    )
                )
            elif status in PENDING_STATUSES:
                result.findings.append(
                    Finding(
                        check="helm_releases",
                        severity=Severity.WARN,
                        title=f"Helm 릴리스 진행중 고착 의심: {name}",
                        detail=f"status={status}, chart={chart}, namespace={ns}",
                        resource=f"{ns}/{name}",
                        suggestion=(
                            f"`helm status {name} -n {ns}` 확인. "
                            "배포 타임아웃이 났거나 Pod CrashLoop 가능성이 있습니다."
                        ),
                    )
                )
            elif status not in HEALTHY_STATUSES:
                result.findings.append(
                    Finding(
                        check="helm_releases",
                        severity=Severity.WARN,
                        title=f"Helm 릴리스 비정상 상태: {name}",
                        detail=f"status={status}, chart={chart}, namespace={ns}",
                        resource=f"{ns}/{name}",
                    )
                )

        # 기대 릴리스 중 누락 확인
        for expected in expected_releases:
            if expected not in release_names:
                result.findings.append(
                    Finding(
                        check="helm_releases",
                        severity=Severity.ERROR,
                        title=f"기대 릴리스 없음: {expected}",
                        detail=f"검색 네임스페이스: {helm_namespaces}",
                        suggestion=(
                            f"`helm list -A | grep {expected}` 로 확인하세요. "
                            "viola_helm role 이 실행됐는지 Ansible 로그를 확인하세요."
                        ),
                    )
                )

    return result
