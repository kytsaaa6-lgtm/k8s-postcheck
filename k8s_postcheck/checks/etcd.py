"""etcd 상태 체크.

1. kube-system 의 etcd Pod 실행 여부 (static pod: component=etcd)
2. etcd Pod 수 vs 컨트롤 플레인 노드 수 비교
   - 홀수 개(보통 3개)가 아니면 WARN (쿼럼 위험)
3. etcd Pod 내부에서 etcdctl endpoint health 실행 (exec 없이 로그 기반)
   - Pod 로그에서 "health check for peer" 실패 패턴 감지
"""

from __future__ import annotations

from ..auth import K8sHandle
from ..models import CheckResult, Finding, Severity
from ._util import pod_is_ready, pod_phase_ok, timed


def _control_plane_count(handle: K8sHandle) -> int:
    """node-role.kubernetes.io/control-plane 레이블이 붙은 노드 수."""
    try:
        nodes = handle.core.list_node(
            label_selector="node-role.kubernetes.io/control-plane"
        ).items
        if nodes:
            return len(nodes)
        # 구버전 레이블
        nodes = handle.core.list_node(
            label_selector="node-role.kubernetes.io/master"
        ).items
        return len(nodes)
    except Exception:
        return 0


def run(handle: K8sHandle, ctx: dict) -> CheckResult:
    with timed("etcd") as result:
        # etcd static pod 는 kube-system 에 component=etcd 로 등록됨
        try:
            pods = handle.core.list_namespaced_pod(
                namespace="kube-system",
                label_selector="component=etcd",
            ).items
        except Exception as exc:
            result.findings.append(
                Finding(
                    check="etcd",
                    severity=Severity.ERROR,
                    title="etcd Pod 조회 실패",
                    detail=str(exc),
                )
            )
            return result

        result.findings.append(
            Finding(
                check="etcd",
                severity=Severity.INFO,
                title="etcd Pod 수집",
                detail=f"{len(pods)}개",
            )
        )

        if not pods:
            result.findings.append(
                Finding(
                    check="etcd",
                    severity=Severity.CRITICAL,
                    title="etcd Pod 없음",
                    detail="component=etcd 로 조회된 Pod 가 없습니다.",
                    suggestion=(
                        "컨트롤 플레인 노드에서 "
                        "`systemctl status kubelet` / "
                        "`ls /etc/kubernetes/manifests/etcd.yaml` 을 확인하세요."
                    ),
                )
            )
            return result

        # etcd Pod 각각 상태 확인
        bad_pods = []
        for p in pods:
            if not (pod_phase_ok(p) and pod_is_ready(p)):
                bad_pods.append(p)
                phase = (p.status.phase or "?") if p.status else "?"
                result.findings.append(
                    Finding(
                        check="etcd",
                        severity=Severity.CRITICAL,
                        title=f"etcd Pod 비정상: {p.metadata.name}",
                        detail=f"phase={phase}",
                        resource=p.metadata.name,
                        suggestion=(
                            f"`kubectl describe pod {p.metadata.name} -n kube-system` 및 "
                            f"`kubectl logs {p.metadata.name} -n kube-system --tail=50` 확인."
                        ),
                    )
                )

        # etcd 멤버 수 vs 컨트롤 플레인 수 비교
        cp_count = _control_plane_count(handle)
        etcd_count = len(pods)
        if cp_count > 0 and etcd_count != cp_count:
            result.findings.append(
                Finding(
                    check="etcd",
                    severity=Severity.ERROR,
                    title="etcd 멤버 수 불일치",
                    detail=f"etcd Pod {etcd_count}개 vs 컨트롤 플레인 노드 {cp_count}개",
                    suggestion=(
                        "etcd 멤버가 누락된 경우 클러스터 쿼럼이 깨질 수 있습니다. "
                        "`etcdctl member list` 로 멤버 상태를 직접 확인하세요."
                    ),
                )
            )

        # 홀수 검사 (쿼럼 보장을 위해 홀수 권장)
        if etcd_count > 1 and etcd_count % 2 == 0:
            result.findings.append(
                Finding(
                    check="etcd",
                    severity=Severity.WARN,
                    title=f"etcd 멤버 수 짝수: {etcd_count}개",
                    detail="etcd 는 홀수 멤버(1, 3, 5…) 구성을 권장합니다.",
                    suggestion="멤버를 추가하거나 제거해서 홀수로 맞추세요.",
                )
            )

        # 최근 로그에서 에러 패턴 감지 (비관리자도 가능)
        error_keywords = [
            "failed to send out heartbeat on time",
            "lost leader",
            "raft: failed to",
            "health check for peer",
            "dial tcp",
        ]
        for p in pods:
            if p in bad_pods:
                continue
            try:
                logs = handle.core.read_namespaced_pod_log(
                    name=p.metadata.name,
                    namespace="kube-system",
                    tail_lines=100,
                    container="etcd",
                )
            except Exception:
                logs = ""
            matched = [kw for kw in error_keywords if kw.lower() in (logs or "").lower()]
            if matched:
                result.findings.append(
                    Finding(
                        check="etcd",
                        severity=Severity.WARN,
                        title=f"etcd 로그 이상 패턴: {p.metadata.name}",
                        detail=f"키워드 감지: {matched}",
                        resource=p.metadata.name,
                        suggestion=(
                            f"`kubectl logs {p.metadata.name} -n kube-system --tail=200` 로 "
                            "heartbeat timeout / leader election 이슈를 확인하세요."
                        ),
                    )
                )

    return result
