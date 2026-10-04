# 실행 환경과 운영 구성

현재 `compose.dev.yaml`은 기존 로컬 개발 서비스 정의를 옮긴 파일이다.
저장소 루트의 `compose.yaml`이 이를 포함하므로 기존 명령을 그대로 사용한다.

```bash
docker compose up --build
```

루트 진입점의 `project_directory: .`가 빌드 경로·마운트·`.env`의 기준을
저장소 루트로 고정한다. 서비스 이름과 볼륨 이름은 유지한다.
Compose 2.24.0 이상을 사용한다.
[Compose include 문서](https://docs.docker.com/compose/how-tos/multiple-compose-files/include/)

## 운영 서버 준비 후 추가할 구성

| 위치 | 책임 |
| --- | --- |
| `compose.prod.yaml` | 개발 설정과 독립된 운영 구성; 이미지 digest 고정 |
| `nginx/` | 정적 파일·TLS·API 프록시·점검 화면 설정 |
| `systemd/` | 서버 외부 DB 백업용 service와 timer |
| `scripts/deploy.sh` | 정상 종료·백업·마이그레이션·검증·재개 |
| `scripts/migrate.sh` | 새 backend 이미지에서 한 번만 마이그레이션 |
| `scripts/backup-db.sh` | DB dump·암호화·외부 업로드·무결성 검증 |
| `scripts/restore-db.sh` | 운영자가 선택한 백업 복원 |
| `scripts/verify-restore.sh` | 격리된 DB에서 복원 검증 |
| `terraform/` | 제공자 결정 후 서버·네트워크 등 인프라 정의 |

이 표의 운영 파일과 서비스는 아직 구현하지 않았다. 개발용 Compose는 운영 배포 구성이 아니다.
실제 필요한 시점에 파일을 추가하며 빈 스크립트나 실행되는 척하는 구성을 두지 않는다.

## 배포·복원 시 지켜야 할 경계

- API·worker·Beat는 같은 backend 이미지의 서로 다른 실행 명령을 사용한다.
- 백업은 호스트 timer가 실행해 Redis나 Celery 장애와 분리한다.
- 외부 백업 검증 후 마이그레이션을 한 번 실행한다. 프로세스 시작마다 자동 실행하지 않는다.
- 이전 이미지 복귀는 변경된 DB 스키마와 호환될 때만 수행한다.
- 복원 후 미완료 작업의 실행을 보류하고, 삭제 기록·토큰 해제 및 비용을 대조한 뒤 재개한다.
- 현재 CI는 검사만 실행한다. GHCR 이미지 게시와 서버 준비 후 수동 배포는 별도 후속 작업이다.
