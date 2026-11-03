# 운영 배포

`https://dragram.app`. AWS Lightsail(서울) Ubuntu 24.04 한 대, 메모리 2GB, 스왑 2GB.

## 처음 한 번 (서버)

1. Docker를 설치하고 `ubuntu` 사용자를 `docker` 그룹에 넣는다.
   ```bash
   curl -fsSL https://get.docker.com | sudo sh && sudo usermod -aG docker ubuntu
   ```
2. Lightsail 방화벽은 22·80·443만 연다(IPv4·IPv6). 도메인 A 레코드가 서버 고정 IP를 가리켜야 Caddy가 인증서를 받는다.
3. `~/dragram/.env`를 `.env.example`대로 만든다. 권한은 본인만 읽게 한다.
   ```bash
   mkdir -p ~/dragram && chmod 700 ~/dragram
   ```
   ```bash
   nano ~/dragram/.env && chmod 600 ~/dragram/.env
   ```

## 자동 배포 (GitHub Actions)

`main`에 push된 커밋의 CI가 성공하면 `.github/workflows/deploy.yml`이 그 커밋으로 `infra/deploy.sh`를 돌린 뒤 `/api/health/`를 확인한다. `dev`→`main` 병합이 곧 배포 승인이다. CI가 실패·취소됐거나, 그 사이 `main`에 더 새 커밋이 올라왔으면 배포하지 않는다. 다시 돌리려면 Actions의 Deploy를 `main`에서 수동 실행한다.

처음 한 번, 배포 전용 키를 만들고 저장소 secret 세 개를 넣는다(개발 PC).

1. 배포 전용 키를 만든다. 암호 없이 만들고, 공개키를 서버에 등록한다.
   ```bash
   ssh-keygen -t ed25519 -N '' -C dragram-deploy -f ~/.ssh/dragram_deploy
   ```
   ```bash
   ssh-copy-id -i ~/.ssh/dragram_deploy.pub ubuntu@dragram.app
   ```
2. secret을 넣는다. 호스트 키는 이미 접속해 본 개발 PC의 `known_hosts`에서 꺼낸다(네트워크로 새로 받지 않는다).
   ```bash
   gh secret set DEPLOY_HOST --body ubuntu@dragram.app
   ```
   ```bash
   gh secret set DEPLOY_SSH_KEY < ~/.ssh/dragram_deploy
   ```
   ```bash
   ssh-keygen -F dragram.app | grep -v '^#' | gh secret set DEPLOY_KNOWN_HOSTS
   ```
3. 개인키 파일은 secret에 넣었으니 개발 PC에서 지워도 된다. 키를 바꾸면 서버 `~/.ssh/authorized_keys`에서 `dragram-deploy` 줄을 지운다.

## 수동 배포 (개발 PC, 저장소 루트)

운영 웹은 서버 `~/dragram/.env`의 `VITE_` 값(확장 ID, 연락 메일 등)으로 빌드한다. Google 클라이언트 ID는 backend와 같은 `GOOGLE_CLIENT_ID`를 쓰고, 비어 있으면 배포가 멈춘다. 값을 바꾸면 다시 배포해야 웹에 반영된다. 웹은 개발 PC의 Docker에서 Node 22 컨테이너로 빌드한다.

```bash
DEPLOY_HOST=ubuntu@dragram.app infra/deploy.sh
```

backend 이미지를 커밋 해시 태그로 빌드해 서버로 보내고, 웹 빌드 결과와 이미지 속 admin 정적 파일을 서버의 `~/dragram/www`에 폴더째 바꿔 넣고, `dragram-backend:current`로 가리킨 뒤 마이그레이션하고 다시 띄운 뒤 Caddy 설정을 다시 읽힌다. 이미지는 커밋된 트리로만 빌드하고, `backend/`·`infra/`·`web/`에 커밋하지 않은 변경(새 파일 포함)이 있으면 멈춘다.

확인:
```bash
curl -sS https://dragram.app/api/health/
```

## 추론 강도 변경 (서버)

모든 LLM 호출은 기본 `low`를 쓴다. 서버의 `~/dragram/.env`에서 `OPENAI_REASONING_EFFORT`를 지우거나 비워도 `low`다. 다른 강도를 쓰려면 현재 모델이 지원하는 값(예: `medium`)을 명시한 뒤 서버와 작업자를 모두 다시 만든다.

```bash
cd ~/dragram && docker compose up -d --force-recreate backend worker
```

`docker compose restart`만으로는 바뀐 환경변수를 읽지 않는다. SDK 허용 목록 밖의 값은 시작할 때 설정 오류로 거부한다. 이미 진행 중인 분석을 피해서 적용하고, 추론 강도만 변경해도 기존 분석 캐시는 재사용된다. 실제 속도·분석 품질 차이는 아직 측정하지 않았다(#217).

## 매일 정리 (서버)

탈퇴한 Google 계정의 그날 사용량 행(`usage_log.withdrawn_key`)은 한국 시간 자정이 지나면 지운다. 분석 요청·탈퇴 때도 지우지만, 요청이 없는 날에도 늦어도 다음 날 지우도록 매일 예약 실행한다(#252). 만료된 로그인 세션 행도 Django 기본 명령 `clearsessions`로 매일 지운다(처리방침 7절). 서버 시계는 UTC이므로 한국 시간 0시 5분은 UTC 15시 5분이다(`timedatectl`로 확인).

```bash
crontab -e
```
```
5 15 * * * cd ~/dragram && docker compose exec -T backend python manage.py purge_withdrawn_usage || logger -t dragram "purge_withdrawn_usage 실패"
10 15 * * * cd ~/dragram && docker compose exec -T backend python manage.py clearsessions || logger -t dragram "clearsessions 실패"
```

실패하면 syslog에 남는다(`journalctl -t dragram`).

등록됐는지 확인:
```bash
crontab -l
```

DB 백업은 crontab이 아니라 Lightsail 자동 스냅샷이다(아래 '백업과 복원').

## 되돌리기 (서버)

서버에 남아 있는 이전 이미지로 가리키고 다시 띄운다. 마이그레이션은 되돌리지 않으니, 스키마가 바뀐 배포는 최근 스냅샷이 있는지부터 확인한다(아래 '백업과 복원').
```bash
docker images dragram-backend
```
```bash
cd ~/dragram && docker tag dragram-backend:<이전 해시> dragram-backend:current && docker compose up -d
```
웹과 admin 정적 파일은 서버에 이전 버전을 남기지 않는다. 웹도 되돌려야 하면 개발 PC에서 이전 커밋을 체크아웃해 `infra/deploy.sh`로 다시 올린다.

## 백업과 복원 (Lightsail 콘솔)

백업은 Lightsail 자동 스냅샷뿐이다. 서버 디스크 전체(DB, `.env`, Caddy 인증서, crontab, 이미지)를 하루 한 번 찍고 최근 7개만 남긴다. 매일 DB 덤프는 두지 않는다(`docs/decisions.md` '백업은 Lightsail 자동 스냅샷만'). 처리방침 7·8절이 이 설정(하루 한 번, 최근 7개, 서울 리전, 최대 7일 뒤 삭제)을 약속하므로 바꾸면 처리방침도 고친다.

확인: 인스턴스 → Snapshots 탭에서 Automatic snapshots가 켜져 있고, 실행 시각과 최근 스냅샷 날짜가 맞는지 본다.

복원(서버를 통째로 바꾼다. 스냅샷 시각 뒤에 생긴 데이터는 잃는다):
1. Snapshots 탭의 자동 스냅샷에서 새 인스턴스를 만든다(서울, 같은 플랜 이상).
2. 새 인스턴스의 방화벽을 22·80·443만 열린 상태(IPv4·IPv6)로 맞춘다.
3. 새 인스턴스의 임시 공개 IP로 접속한다. 컨테이너는 `restart: unless-stopped`라 부팅하면 올라온다. 아직 고정 IP가 없어 사용자 요청은 들어오지 않는다.
   ```bash
   cd ~/dragram && docker compose ps
   ```
   ```bash
   curl -sS --resolve dragram.app:443:127.0.0.1 https://dragram.app/api/health/
   ```
4. 고정 IP를 옮기기 전에, 스냅샷 시각 뒤에 처리한 탈퇴·삭제를 다시 적용한다(처리방침 8절). 먼저 하지 않으면 지운 개인정보가 다시 서비스되고, 옮긴 뒤 새로 생긴 행까지 아래 비교에 걸린다. 옛 DB를 읽을 수 있으면 복구한 DB에만 있는 계정(`accounts_user`)·`my_item`·`my_example`·`designated_name` 행을 지운다. 읽을 수 없으면 그 사이 문의 메일로 받은 탈퇴·삭제 요청을 다시 처리한다.
5. Networking 탭에서 고정 IP를 옛 인스턴스에서 떼어 새 인스턴스에 붙인다. IP가 같아 DNS는 그대로다. 밖에서 health를 확인한다.
   ```bash
   curl -sS https://dragram.app/api/health/
   ```
6. 옛 인스턴스는 필요한 것을 다 꺼낸 뒤 지운다.

복원 연습: 고정 IP를 옮기지 않고 1~3번만 한 뒤, 운영 서버와 같은 명령으로 행 수를 비교한다(스냅샷 뒤에 생긴 행만큼은 다를 수 있다). 확인이 끝나면 연습 인스턴스를 지운다.
```bash
cd ~/dragram && docker compose exec -T db psql -U dragram -d dragram -c "select (select count(*) from accounts_user) users, (select count(*) from my_item) my_item, (select count(*) from my_example) my_example, (select count(*) from word) word, (select count(*) from sentence_analysis) analysis"
```

서버를 다른 곳으로 옮길 때는 스냅샷이 아니라 그날 한 번 `pg_dump`로 꺼내 새 서버에서 `pg_restore`한다.

## 상태 보기 (서버)

```bash
cd ~/dragram && docker compose ps
```
```bash
cd ~/dragram && docker compose logs -f --tail 100 backend worker caddy
```

접속 기록은 `docker compose logs`가 아니라 caddy 컨테이너의 `/var/log/caddy/access.log`(볼륨 `caddy_logs`)에 남는다. 통신비밀보호법 시행령 제41조에 따라 3개월 보관하므로 볼륨을 지우지 않는다(처리방침 7절).
```bash
cd ~/dragram && docker compose exec caddy tail -n 20 /var/log/caddy/access.log
```
