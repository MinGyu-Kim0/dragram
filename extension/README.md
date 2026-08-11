# Dragram Chrome 확장 프로그램

1. Chrome의 `chrome://extensions`에서 개발자 모드를 켜고 이 `extension` 폴더를 **압축해제된 확장 프로그램**으로 로드합니다.
2. 표시된 확장 프로그램 ID를 `.env`의 `EXTENSION_ORIGIN=chrome-extension://<ID>`에 넣습니다.
3. `.env`에 `OPENAI_API_KEY`를 설정하고 Docker 서비스를 시작합니다.
4. 확장 아이콘의 메뉴에서 분석을 켜고 Luna 또는 Terra를 선택합니다.
5. 웹 페이지의 일본어 문장을 선택하면 `。` 단위로 페이지가 나뉘어 분석됩니다. 분석한 내용은 `http://localhost:5173`에서 복습할 수 있습니다.

운영 서버를 사용할 때는 `manifest.json`의 `host_permissions`와 `background.js`의 `API_ROOT`를 함께 변경하세요.
