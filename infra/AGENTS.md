# infra

운영 배포. 서버 한 대(AWS Lightsail)에 compose로 db·redis·backend·작업자·Caddy를 올린다. 로컬 개발용 compose는 루트 `compose.yaml`이다.

- `compose.yaml`: 운영 compose. 서버의 `~/dragram`에서 실행한다.
- `Caddyfile`: 앞단. HTTPS 인증서를 자동으로 받고 `/api`·`/admin`을 backend로 넘긴다. 웹 빌드 결과(`www/web`)와 admin 정적 파일(`www/static`)을 직접 제공하고, 웹 경로는 `index.html`로 연다. 서버에는 `~/dragram/caddy/Caddyfile`로 올리고, 배포할 때마다 Caddy가 다시 읽는다.
- `deploy.sh`: 개발 PC에서 backend 이미지와 웹을 빌드해 서버로 보내고 다시 띄운다. 웹은 커밋된 `web/`과 서버 `.env`의 공개 값(`VITE_`, `GOOGLE_CLIENT_ID`)으로만 빌드한다.
- 처음 설정과 배포·되돌리기 절차: `README.md`

## 규칙
- 비밀값은 서버의 `~/dragram/.env`에만 둔다. 이 폴더에는 견본(`.env.example`)만 둔다.
- 이미지는 서버에서 빌드하지 않는다. 메모리가 2GB라 빌드가 서버를 멈출 수 있다.
- `caddy_data` 볼륨을 지우지 않는다. 인증서를 다시 받다가 Let's Encrypt 발급 횟수 제한에 걸릴 수 있다.
- 분석 API는 줄 단위 JSON 스트림이다. 앞단을 바꿀 때도 응답을 모아 두지 않고 바로 넘기고, 130초보다 먼저 끊지 않게 한다(ADR 0005).
- backend 포트는 밖에 열지 않는다. backend는 Caddy가 넘긴 `X-Forwarded-Proto`를 믿는다.
