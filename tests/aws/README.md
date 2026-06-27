# AWS 수동 통합 검증

`test_aws_full.py`는 `test/service-validation` 브랜치에서 실제 AWS 리소스를 호출해 배포된 문진톡톡 환경이 끝까지 연결되어 있는지 확인하는 수동 통합 테스트입니다.

이 테스트는 단위 테스트가 아닙니다. Bedrock, DynamoDB, S3, Lambda를 실제로 호출하므로 AWS 권한, 배포 상태, 비용 영향을 확인한 뒤 실행합니다.

## 확인 범위

| 그룹 | 확인 내용 |
| --- | --- |
| 1. Bedrock LLM | Nova Lite, Nova Pro converse 호출과 Titan embedding 생성 |
| 2. DynamoDB | 세션 조회, 필수 필드, 이름/생년월일 미저장 정책 |
| 3. S3 Artifact | artifact 버킷 접근, onepaper/answers 구조, 금지 필드 미포함 |
| 4. Lambda 라우팅 | 질문셋 조회, doctor queue 인증, 404, process-answer 입력 검증 |
| 5. 전체 파이프라인 | 기존 세션을 이용한 process-answer 흐름 |
| 6. 프롬프트/schema | 증상 추출 source_quote grounding, 사투리 RAG 포함 변환 |
| 7. 보안 | 잘못된 접근 코드 거부, 세션 토큰 접근 제어 |

## 실행 전 체크리스트

- AWS CLI 또는 boto3가 사용할 credential이 설정되어 있어야 합니다.
- Bedrock Nova Lite, Nova Pro, Titan Embedding 사용 권한이 있어야 합니다.
- Lambda 함수가 최신 배포 상태여야 합니다.
- DynamoDB 세션 테이블과 S3 artifact bucket에 접근 권한이 있어야 합니다.
- 테스트에 사용할 세션이 없으면 일부 항목은 skip 메시지만 출력할 수 있습니다.
- Bedrock 호출 비용이 발생할 수 있습니다.

## 환경변수

PowerShell:

```powershell
$env:MUNJIN_REGION = "ap-northeast-2"
$env:MUNJIN_LAMBDA_NAME = "<lambda-function-name>"
$env:MUNJIN_API_URL = "https://<api-id>.execute-api.<region>.amazonaws.com"
$env:MUNJIN_TABLE = "MunjinSessions"
$env:MUNJIN_ARTIFACTS_BUCKET = "<artifacts-bucket-name>"
```

Bash:

```bash
export MUNJIN_REGION=ap-northeast-2
export MUNJIN_LAMBDA_NAME=<lambda-function-name>
export MUNJIN_API_URL=https://<api-id>.execute-api.<region>.amazonaws.com
export MUNJIN_TABLE=MunjinSessions
export MUNJIN_ARTIFACTS_BUCKET=<artifacts-bucket-name>
```

공개 저장소에는 실제 Lambda 이름, API URL, 버킷명을 커밋하지 않습니다.

## 직접 실행

```powershell
python tests\aws\test_aws_full.py
```

직접 실행하면 스크립트 내부의 `run_test()`가 각 항목을 순서대로 실행하고 마지막에 PASS/FAIL 요약을 출력합니다.

## pytest로 실행

일반 `pytest` 전체 실행에서 실수로 AWS를 호출하지 않도록 기본값은 skip입니다. 이 파일만 pytest로 실행하려면 명시적으로 플래그를 켭니다.

```powershell
$env:MUNJIN_RUN_AWS_INTEGRATION = "1"
pytest tests\aws\test_aws_full.py -s
```

`MUNJIN_RUN_AWS_INTEGRATION`이 없으면 pytest import 단계에서 skip됩니다.

## 실패 해석

| 실패 위치 | 먼저 확인할 것 |
| --- | --- |
| Bedrock | 모델 access 권한, region, Bedrock opt-in 상태 |
| DynamoDB | 테이블명, IAM 권한, 실제 세션 존재 여부 |
| S3 | bucket 이름, list/get 권한, lifecycle로 artifact가 정리됐는지 |
| Lambda | 함수명, 배포 버전, API event payload shape |
| process-answer | 세션 상태, patient token, Lambda 환경변수, Bedrock 응답 |
| 인증 테스트 | staff/doctor access code 설정, 토큰 검증 정책 |

통합 테스트 실패는 곧바로 코드 버그라고 단정하지 않습니다. AWS 권한, 배포 상태, 테스트 세션 존재 여부, 리소스 lifecycle 때문에 실패할 수 있습니다.

## 보안 주의

- 이 테스트는 실제 배포 환경의 연결 상태를 보는 수동 평가입니다.
- 테스트 실행 중 Bedrock 호출 비용이 발생할 수 있습니다.
- 운영 데이터가 얽힌 계정에서는 출력 로그에 민감정보가 남지 않도록 주의합니다.
- 실패 결과를 커밋하지 말고, 필요한 경우 민감정보를 제거한 요약만 문서화합니다.
- 테스트용 access code, session token, API URL은 `.env` 또는 로컬 환경변수에서만 관리합니다.


