# k8s-postcheck

Kubespray + Viola 로 구성한 쿠버네티스 클러스터가 **프로비저닝 완료 후 제대로 동작하는지** 검증하는 도구입니다.

```
[kubespray-preflight] → Kubespray 실행 → [k8s-postcheck]
       사전 점검                              사후 검증
```

## 무엇을 잡아내나

| 체크 | 확인 항목 |
|---|---|
| **nodes** | 전체 노드 Ready 여부, MemoryPressure/DiskPressure/PIDPressure, 기대 노드 수 대비, kubelet 버전 일관성 |
| **system_pods** | kube-system Pod 전체 이상 감지, coredns/metrics-server/cilium 등 필수 컴포넌트 Running 확인 |
| **helm_releases** | Helm 3 릴리스 상태(failed/pending 고착), 기대 릴리스 누락 감지 (kubectl 없이 Secret 직접 파싱) |
| **certs** | kube-apiserver TLS 인증서 만료 임박 (TLS 직접 연결), kube-system TLS Secret 인증서 만료 스캔 |
| **velero** | Velero Pod 실행 여부, BackupStorageLocation phase=Available, MinIO health endpoint |
| **etcd** | etcd Pod 상태, 멤버 수 vs 컨트롤 플레인 노드 수, 짝수 구성(쿼럼 위험), 로그 에러 패턴 감지 |

## 설치

```bash
cd k8s-postcheck
python -m venv .venv
source .venv/bin/activate
pip install -e .

# 인증서 Secret 상세 점검 원할 때
pip install cryptography
```

## 빠른 시작

```bash
# kubeconfig 기본값 사용
k8s-postcheck verify --expected-nodes 6

# 설정 파일로 한 번에
k8s-postcheck verify --config ./examples/config.example.yaml \
  --markdown report.md --json report.json

# 특정 체크만
k8s-postcheck verify --only nodes,etcd,certs

# Viola 배포 포함 전체 검증
k8s-postcheck verify \
  --config ./my-cluster.yaml \
  --expected-nodes 6 \
  --expected-releases cilium,metrics-server,velero \
  --helm-namespaces default,kube-system,velero \
  --minio-url http://minio.internal:9000 \
  --cert-warn-days 30 \
  --markdown report.md
```

## 설정 파일

```yaml
# my-cluster.yaml
cluster:
  expected_nodes: 6
  minio_url: http://minio.example.com:9000
  velero_namespace: velero
  helm_namespaces:
    - default
    - kube-system
    - velero
  expected_releases:
    - cilium
    - metrics-server
    - velero

required_components:
  cilium: k8s-app=cilium
  cilium-operator: name=cilium-operator
```

`examples/config.example.yaml` 을 복사해서 사용하세요.

## CI 게이팅

```bash
# ERROR 이상이면 비정상 종료 (기본)
k8s-postcheck verify --config cluster.yaml
echo $?  # 0=정상, 2=임계 이상

# WARN 이상도 실패로 처리
k8s-postcheck verify --fail-on warn
```

## 체크 목록

```bash
k8s-postcheck list-checks
```

## 개발 / 테스트

```bash
pip install -e ".[dev]"
ruff check .        # 린트
mypy                # 타입 체크 (k8s_postcheck 패키지)
pytest -ra          # 유닛 테스트
```

테스트는 실제 클러스터 없이 Kubernetes API 를 Mock 으로 대체해 실행됩니다.
6개 체크 모듈(`nodes`, `system_pods`, `helm_releases`, `certs`, `velero`,
`etcd`)과 report/CLI 헬퍼를 회귀로 고정합니다. GitHub Actions
(`.github/workflows/ci.yml`) 에서 ruff / mypy / pytest 를 `python 3.10/3.11/3.12`
매트릭스로 게이팅합니다.
