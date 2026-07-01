"""시스템 Pod 헬스 체크.

kube-system 네임스페이스 전체 Pod 를 점검하고,
ctx["required_components"] 에 선언된 컴포넌트(label selector 또는 이름 prefix 기준)가
모두 Running 상태인지 확인합니다.

기본 required_components:
  - coredns        (k8s-app=kube-dns)
  - metrics-server (k8s-app=metrics-server)
  - cilium         (k8s-app=cilium)  ← Cilium CNI 사용 시
  - kube-proxy     (k8s-app=kube-proxy) ← kube-proxy 사용 시
"""

from __future__ import annotations

from ..auth import K8sHandle
from ..models import CheckResult, Finding, Severity
from ._util import pod_is_ready, pod_phase_ok, timed

# 기본 점검 대상 컴포넌트: {표시명: label selector}
DEFAULT_COMPONENTS: dict[str, str] = {
    "coredns": "k8s-app=kube-dns",
    "metrics-server": "k8s-app=metrics-server",
}


def _check_component(
    pods: list,
    name: str,
    label_selector: str | None,
    name_prefix: str | None,
    namespace: str,
    result: CheckResult,
) -> None:
    if label_selector:
        matched = [
            p for p in pods
            if _labels_match(p.metadata.labels or {}, label_selector)
        ]
    elif name_prefix:
        matched = [p for p in pods if (p.metadata.name or "").startswith(name_prefix)]
    else:
        matched = []

    if not matched:
        result.findings.append(
            Finding(
                check="system_pods",
                severity=Severity.ERROR,
                title=f"컴포넌트 Pod 없음: {name}",
                detail=f"namespace={namespace}, selector={label_selector or name_prefix}",
                suggestion=(
                    f"`kubectl get pods -n {namespace} -l {label_selector}` 로 확인하세요. "
                    "Helm/Kubespray 배포가 완료되지 않았거나 이미지 풀 실패 가능성이 있습니다."
                ),
            )
        )
        return

    not_ready = [p for p in matched if not (pod_phase_ok(p) and pod_is_ready(p))]
    result.findings.append(
        Finding(
            check="system_pods",
            severity=Severity.INFO if not not_ready else Severity.WARN,
            title=f"컴포넌트 확인: {name}",
            detail=f"전체 {len(matched)}개 / 비정상 {len(not_ready)}개",
        )
    )
    for p in not_ready:
        phase = (p.status.phase or "?") if p.status else "?"
        reason = ""
        if p.status and p.status.container_statuses:
            for cs in p.status.container_statuses:
                waiting = cs.state.waiting if cs.state else None
                if waiting:
                    reason = f"{waiting.reason}: {waiting.message or ''}"
                    break
        result.findings.append(
            Finding(
                check="system_pods",
                severity=Severity.ERROR,
                title=f"Pod 비정상: {p.metadata.name}",
                detail=f"phase={phase}" + (f", {reason}" if reason else ""),
                resource=p.metadata.name,
                suggestion=(
                    f"`kubectl describe pod {p.metadata.name} -n {namespace}` 로 "
                    "Events 와 container state 를 확인하세요."
                ),
            )
        )


def _labels_match(labels: dict, selector: str) -> bool:
    for part in selector.split(","):
        part = part.strip()
        # "!=" 는 "=" 를 포함하므로 반드시 먼저 검사해야 한다.
        if "!=" in part:
            k, v = part.split("!=", 1)
            if labels.get(k.strip()) == v.strip():
                return False
        elif "=" in part:
            k, v = part.split("=", 1)
            if labels.get(k.strip()) != v.strip():
                return False
    return True


def run(handle: K8sHandle, ctx: dict) -> CheckResult:
    namespace = ctx.get("system_namespace", "kube-system")
    extra_components: dict = ctx.get("required_components", {})
    skip_components: list = ctx.get("skip_components", [])

    with timed("system_pods") as result:
        pods = handle.core.list_namespaced_pod(namespace=namespace).items
        total = len(pods)
        bad = [p for p in pods if not (pod_phase_ok(p) and pod_is_ready(p))]

        result.findings.append(
            Finding(
                check="system_pods",
                severity=Severity.INFO,
                title=f"Pod 수집 ({namespace})",
                detail=f"전체 {total}개 / 비정상 {len(bad)}개",
            )
        )

        # 전체 비정상 Pod 목록 (required 여부 무관)
        for p in bad:
            phase = (p.status.phase or "?") if p.status else "?"
            # Completed(Job) 는 정상으로 이미 pod_phase_ok 에서 통과시킴
            # 여기 오는 건 진짜 문제 있는 것
            if phase.lower() == "succeeded":
                continue
            result.findings.append(
                Finding(
                    check="system_pods",
                    severity=Severity.WARN,
                    title=f"Pod 비정상 ({namespace}): {p.metadata.name}",
                    detail=f"phase={phase}",
                    resource=p.metadata.name,
                    suggestion=f"`kubectl describe pod {p.metadata.name} -n {namespace}`",
                )
            )

        # 필수 컴포넌트 개별 점검
        components = {**DEFAULT_COMPONENTS, **extra_components}
        for comp_name, selector in components.items():
            if comp_name in skip_components:
                continue
            _check_component(pods, comp_name, selector, None, namespace, result)

    return result
