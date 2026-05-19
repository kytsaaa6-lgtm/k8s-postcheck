"""k8s-postcheck CLI."""

from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Annotated

import typer
import yaml
from rich.console import Console

from . import __version__, auth
from .checks import REGISTRY, available_checks
from .models import SEVERITY_ORDER, PostCheckReport, Severity
from .report import to_console, to_json, to_markdown

app = typer.Typer(
    add_completion=False,
    help=(
        "Kubespray + Viola 로 구성된 쿠버네티스 클러스터가 제대로 올라왔는지 "
        "프로비저닝 완료 후 검증합니다."
    ),
    no_args_is_help=True,
)
console = Console()

SEVERITY_FROM_STR = {s.value: s for s in Severity}


def _build_context(
    *,
    expected_nodes: int | None,
    expected_releases: list[str] | None,
    helm_namespaces: list[str] | None,
    required_components: dict | None,
    skip_components: list[str] | None,
    cert_warn_days: int,
    cert_error_days: int,
    minio_url: str | None,
    velero_namespace: str,
    extra: dict | None = None,
) -> dict:
    ctx: dict = {
        "expected_nodes": expected_nodes,
        "expected_releases": expected_releases or [],
        "helm_namespaces": helm_namespaces or ["default", "kube-system"],
        "required_components": required_components or {},
        "skip_components": skip_components or [],
        "cert_warn_days": cert_warn_days,
        "cert_error_days": cert_error_days,
        "minio_url": minio_url,
        "velero_namespace": velero_namespace,
    }
    if extra:
        for k, v in extra.items():
            if k not in ctx:
                ctx[k] = v
    return ctx


@app.command()
def list_checks() -> None:
    """사용 가능한 체크 목록을 출력합니다."""
    for name in available_checks():
        console.print(f"- {name}")


@app.command()
def verify(
    kubeconfig: Annotated[
        Path | None, typer.Option("--kubeconfig", help="kubeconfig 파일 경로")
    ] = None,
    context: Annotated[
        str | None, typer.Option("--context", help="kubeconfig context 이름")
    ] = None,
    config: Annotated[
        Path | None, typer.Option("--config", help="체크 설정 YAML 파일")
    ] = None,
    only: Annotated[
        str | None, typer.Option(help="콤마로 구분된 체크만 실행")
    ] = None,
    skip: Annotated[
        str | None, typer.Option(help="콤마로 구분된 체크 제외")
    ] = None,
    expected_nodes: Annotated[
        int | None, typer.Option(help="기대 노드 수")
    ] = None,
    expected_releases: Annotated[
        str | None, typer.Option(help="콤마로 구분된 기대 Helm 릴리스 이름")
    ] = None,
    helm_namespaces: Annotated[
        str | None, typer.Option(help="Helm 릴리스를 검색할 네임스페이스 (콤마 구분)")
    ] = None,
    cert_warn_days: Annotated[
        int, typer.Option(help="인증서 만료 경고 기준 (일)")
    ] = 30,
    cert_error_days: Annotated[
        int, typer.Option(help="인증서 만료 ERROR 기준 (일)")
    ] = 7,
    minio_url: Annotated[
        str | None, typer.Option(help="MinIO URL (예: http://minio.example.com:9000)")
    ] = None,
    velero_namespace: Annotated[
        str, typer.Option(help="Velero 네임스페이스")
    ] = "velero",
    skip_components: Annotated[
        str | None, typer.Option(help="system_pods 에서 제외할 컴포넌트 (콤마 구분)")
    ] = None,
    fail_on: Annotated[
        str, typer.Option(help="이 심각도 이상이면 비정상 종료")
    ] = "error",
    json_out: Annotated[Path | None, typer.Option("--json")] = None,
    md_out: Annotated[Path | None, typer.Option("--markdown")] = None,
    no_console: Annotated[bool, typer.Option(help="콘솔 출력 끄기")] = False,
) -> None:
    """클러스터 프로비저닝 후 상태를 검증합니다."""

    if fail_on.lower() not in SEVERITY_FROM_STR:
        console.print(
            f"[red]오류:[/red] --fail-on='{fail_on}' 는 알 수 없는 값입니다. "
            f"허용값: {sorted(SEVERITY_FROM_STR)}"
        )
        raise typer.Exit(code=64)

    # YAML 설정 로드
    file_data: dict = {}
    extra_ctx: dict = {}
    if config:
        file_data = yaml.safe_load(config.read_text(encoding="utf-8")) or {}
        cluster_ctx = file_data.get("cluster", {}) or {}
        if cluster_ctx:
            extra_ctx.update(cluster_ctx)
            expected_nodes = expected_nodes or cluster_ctx.get("expected_nodes")
            minio_url = minio_url or cluster_ctx.get("minio_url")
            velero_namespace = cluster_ctx.get("velero_namespace", velero_namespace)
            if not expected_releases and cluster_ctx.get("expected_releases"):
                expected_releases = ",".join(cluster_ctx["expected_releases"])
            if not helm_namespaces and cluster_ctx.get("helm_namespaces"):
                helm_namespaces = ",".join(cluster_ctx["helm_namespaces"])

    # 파싱
    releases_list = (
        [x.strip() for x in expected_releases.split(",") if x.strip()]
        if expected_releases else None
    )
    ns_list = (
        [x.strip() for x in helm_namespaces.split(",") if x.strip()]
        if helm_namespaces else None
    )
    skip_comp_list = (
        [x.strip() for x in skip_components.split(",") if x.strip()]
        if skip_components else None
    )
    required_components = file_data.get("required_components") or {}

    handle = auth.connect(kubeconfig=kubeconfig, context=context)

    cluster_label = handle.cluster_label
    report = PostCheckReport(cluster=cluster_label)
    report.context = {
        "tool_version": __version__,
        "expected_nodes": expected_nodes,
        "expected_releases": releases_list,
    }

    ctx = _build_context(
        expected_nodes=expected_nodes,
        expected_releases=releases_list,
        helm_namespaces=ns_list,
        required_components=required_components,
        skip_components=skip_comp_list,
        cert_warn_days=cert_warn_days,
        cert_error_days=cert_error_days,
        minio_url=minio_url,
        velero_namespace=velero_namespace,
        extra=extra_ctx,
    )

    selected = available_checks()
    if only:
        wanted = {x.strip() for x in only.split(",") if x.strip()}
        selected = [c for c in selected if c in wanted]
    if skip:
        unwanted = {x.strip() for x in skip.split(",") if x.strip()}
        selected = [c for c in selected if c not in unwanted]

    for name in selected:
        console.log(f"running check: {name}")
        report.results.append(REGISTRY[name](handle, ctx))

    report.finished_at = datetime.now(timezone.utc)

    if not no_console:
        to_console(report, console)
    if json_out:
        to_json(report, json_out)
        console.log(f"JSON 리포트 저장: {json_out}")
    if md_out:
        to_markdown(report, md_out)
        console.log(f"Markdown 리포트 저장: {md_out}")

    fail_threshold = SEVERITY_FROM_STR[fail_on.lower()]
    if SEVERITY_ORDER[report.worst_severity] >= SEVERITY_ORDER[fail_threshold]:
        raise typer.Exit(code=2)


if __name__ == "__main__":
    app()
