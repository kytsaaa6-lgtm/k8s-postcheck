"""Kubernetes 클라이언트 인증 헬퍼."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from kubernetes import client, config
from kubernetes.client import ApiClient


@dataclass
class K8sHandle:
    """체크 모듈에서 공유하는 API 클라이언트 번들."""

    api_client: ApiClient
    core: client.CoreV1Api
    apps: client.AppsV1Api
    custom: client.CustomObjectsApi
    cluster_label: str = "(kubeconfig)"


def connect(
    kubeconfig: Path | None = None,
    context: str | None = None,
) -> K8sHandle:
    """kubeconfig 를 로드하고 API 클라이언트를 초기화합니다.

    우선순위:
    1. --kubeconfig 로 지정한 파일
    2. KUBECONFIG 환경변수 / ~/.kube/config
    3. 클러스터 내부 실행(in-cluster) ServiceAccount
    """
    if kubeconfig:
        config.load_kube_config(config_file=str(kubeconfig), context=context)
    else:
        try:
            config.load_kube_config(context=context)
        except config.ConfigException:
            config.load_incluster_config()

    api_client = ApiClient()
    label = context or (str(kubeconfig) if kubeconfig else "(default context)")

    return K8sHandle(
        api_client=api_client,
        core=client.CoreV1Api(api_client),
        apps=client.AppsV1Api(api_client),
        custom=client.CustomObjectsApi(api_client),
        cluster_label=label,
    )
