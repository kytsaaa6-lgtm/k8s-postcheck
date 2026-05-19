"""Velero 백업 스토리지 및 MinIO 연결 체크.

1. velero Pod 실행 여부
2. BackupStorageLocation CRD status.phase = Available
3. MinIO health endpoint (/minio/health/live) 접근 가능 여부
"""

from __future__ import annotations

import urllib.request
import urllib.error

from ..auth import K8sHandle
from ..models import CheckResult, Finding, Severity
from ._util import pod_is_ready, pod_phase_ok, timed

VELERO_NAMESPACE = "velero"
BSL_GROUP = "velero.io"
BSL_VERSION = "v1"
BSL_PLURAL = "backupstoragelocations"


def _check_minio(url: str, timeout: float = 10.0) -> tuple[bool, str]:
    """MinIO health endpoint 에 HTTP GET 을 보냅니다."""
    health_url = url.rstrip("/") + "/minio/health/live"
    try:
        req = urllib.request.Request(health_url, method="GET")
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status < 400, f"HTTP {resp.status}"
    except urllib.error.HTTPError as e:
        return e.code < 400, f"HTTP {e.code}"
    except Exception as exc:
        return False, str(exc)


def run(handle: K8sHandle, ctx: dict) -> CheckResult:
    velero_ns: str = ctx.get("velero_namespace", VELERO_NAMESPACE)
    minio_url: str | None = ctx.get("minio_url")

    with timed("velero") as result:
        # velero Pod 확인
        try:
            pods = handle.core.list_namespaced_pod(
                namespace=velero_ns,
                label_selector="name=velero",
            ).items
            if not pods:
                # label 이 다를 수 있으므로 앱 이름으로 재시도
                pods = handle.core.list_namespaced_pod(
                    namespace=velero_ns,
                    label_selector="app.kubernetes.io/name=velero",
                ).items
        except Exception as exc:
            result.findings.append(
                Finding(
                    check="velero",
                    severity=Severity.WARN,
                    title=f"Velero Pod 조회 실패 (namespace={velero_ns})",
                    detail=str(exc),
                    suggestion=f"네임스페이스 '{velero_ns}' 가 존재하는지 확인하세요.",
                )
            )
            pods = []

        if not pods:
            result.findings.append(
                Finding(
                    check="velero",
                    severity=Severity.ERROR,
                    title=f"Velero Pod 없음 (namespace={velero_ns})",
                    detail="label name=velero / app.kubernetes.io/name=velero 로 조회 결과 없음",
                    suggestion=(
                        "viola_helm role 의 Velero 차트 배포가 완료됐는지, "
                        f"`kubectl get pods -n {velero_ns}` 로 확인하세요."
                    ),
                )
            )
        else:
            bad_pods = [p for p in pods if not (pod_phase_ok(p) and pod_is_ready(p))]
            result.findings.append(
                Finding(
                    check="velero",
                    severity=Severity.INFO if not bad_pods else Severity.ERROR,
                    title="Velero Pod 확인",
                    detail=f"전체 {len(pods)}개 / 비정상 {len(bad_pods)}개",
                )
            )
            for p in bad_pods:
                phase = (p.status.phase or "?") if p.status else "?"
                result.findings.append(
                    Finding(
                        check="velero",
                        severity=Severity.ERROR,
                        title=f"Velero Pod 비정상: {p.metadata.name}",
                        detail=f"phase={phase}",
                        resource=p.metadata.name,
                        suggestion=(
                            f"`kubectl describe pod {p.metadata.name} -n {velero_ns}` 로 확인."
                        ),
                    )
                )

        # BackupStorageLocation 확인
        try:
            bsl_list = handle.custom.list_namespaced_custom_object(
                group=BSL_GROUP,
                version=BSL_VERSION,
                namespace=velero_ns,
                plural=BSL_PLURAL,
            )
            bsls = bsl_list.get("items", [])
        except Exception as exc:
            result.findings.append(
                Finding(
                    check="velero",
                    severity=Severity.WARN,
                    title="BackupStorageLocation CRD 조회 실패",
                    detail=str(exc),
                    suggestion="Velero CRD 가 설치됐는지 확인하세요.",
                )
            )
            bsls = []

        if not bsls:
            result.findings.append(
                Finding(
                    check="velero",
                    severity=Severity.WARN,
                    title="BackupStorageLocation 없음",
                    detail=f"namespace={velero_ns} 에 BSL 이 하나도 없습니다.",
                    suggestion=(
                        "viola_helm role 에서 BSL manifest 가 적용됐는지, "
                        "`kubectl get backupstoragelocations -n velero` 로 확인하세요."
                    ),
                )
            )
        else:
            for bsl in bsls:
                name = bsl.get("metadata", {}).get("name", "?")
                phase = (bsl.get("status") or {}).get("phase", "")
                message = (bsl.get("status") or {}).get("message", "")
                if phase == "Available":
                    result.findings.append(
                        Finding(
                            check="velero",
                            severity=Severity.INFO,
                            title=f"BackupStorageLocation 정상: {name}",
                            detail=f"phase=Available",
                        )
                    )
                else:
                    result.findings.append(
                        Finding(
                            check="velero",
                            severity=Severity.ERROR,
                            title=f"BackupStorageLocation 비정상: {name}",
                            detail=f"phase={phase or '?'}" + (f", {message}" if message else ""),
                            resource=name,
                            suggestion=(
                                "MinIO 접근 가능 여부, minio_url / accessKey / secretKey 설정을 "
                                "확인하세요. `kubectl describe backupstoragelocations -n velero`"
                            ),
                        )
                    )

        # MinIO 헬스 체크
        if minio_url:
            ok, detail = _check_minio(minio_url)
            result.findings.append(
                Finding(
                    check="velero",
                    severity=Severity.INFO if ok else Severity.ERROR,
                    title="MinIO health" + (" 정상" if ok else " 실패"),
                    detail=f"{minio_url}/minio/health/live → {detail}",
                    suggestion=(
                        None if ok else
                        "MinIO 서비스가 기동 중인지, 방화벽/네트워크 경로를 확인하세요."
                    ),
                )
            )
        else:
            result.findings.append(
                Finding(
                    check="velero",
                    severity=Severity.INFO,
                    title="MinIO URL 미지정 — health 체크 건너뜀",
                    detail="config 의 minio_url 을 설정하면 직접 연결을 확인합니다.",
                )
            )

    return result
