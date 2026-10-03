# Dragram

## 로컬 개발

```bash
docker compose up --build
```

## CI

GitHub Actions는 브랜치 push와 Pull Request에서 다음을 검사합니다.

- 백엔드: Docker 이미지 빌드, PostgreSQL 준비, Django 설정 검사·마이그레이션 누락 검사·`core` 테스트.
- 프론트엔드: Node.js 22에서 `npm ci` 후 TypeScript 검사와 Vite 빌드.

Actions의 **CI** 워크플로에서 수동 실행할 수도 있습니다. 별도 Secrets나 서버 설정은 필요하지 않습니다.

## PR·Issue 작성

PR과 Issue는 저장소 템플릿에 맞춰 작성합니다. [작성 안내](.github/CONTRIBUTING.md)를 참고하세요.
