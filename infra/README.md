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

## 배포 (개발 PC, 저장소 루트)

```bash
DEPLOY_HOST=ubuntu@dragram.app infra/deploy.sh
```

backend 이미지를 커밋 해시 태그로 빌드해 서버로 보내고, `dragram-backend:current`로 가리킨 뒤 마이그레이션하고 다시 띄운다. 커밋하지 않은 변경이 있으면 멈춘다.

확인:
```bash
curl -sS https://dragram.app/api/health/
```

## 되돌리기 (서버)

서버에 남아 있는 이전 이미지로 가리키고 다시 띄운다. 마이그레이션은 되돌리지 않으니, 스키마가 바뀐 배포는 DB 백업부터 확인한다.
```bash
docker images dragram-backend
```
```bash
cd ~/dragram && docker tag dragram-backend:<이전 해시> dragram-backend:current && docker compose up -d
```

## 상태 보기 (서버)

```bash
cd ~/dragram && docker compose ps
```
```bash
cd ~/dragram && docker compose logs -f --tail 100 backend worker caddy
```
