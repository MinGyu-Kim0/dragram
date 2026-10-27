import { defineConfig } from "wxt";

// utils/api.ts와 같은 기본값. 바꾸려면 빌드할 때 WXT_API_BASE_URL을 준다.
const apiBaseUrl = process.env.WXT_API_BASE_URL ?? "http://localhost:8000";
// utils/external-messages.ts와 같은 기본값. 바꾸려면 빌드할 때 WXT_WEB_ORIGIN을 준다.
const webOrigin = process.env.WXT_WEB_ORIGIN ?? "http://localhost:5173";

// 스토어 빌드(npm run zip:store). 확장 ID는 스토어가 정하므로 개발용 key를 넣지 않는다.
// 실수로 로컬 주소가 담긴 zip을 올리지 않게, 주소가 https가 아니면 빌드를 멈춘다.
const store = process.env.DRAGRAM_STORE === "true";
if (store && ![apiBaseUrl, webOrigin].every((u) => u.startsWith("https://"))) {
  throw new Error(
    "스토어 빌드는 WXT_API_BASE_URL과 WXT_WEB_ORIGIN이 https:// 주소여야 한다.",
  );
}

// 개발용 확장 ID(ilhnmbeleinmgfcigakmfobgngiillah)를 고정하는 공개 키. 웹은 이 ID로 연결
// 메시지를 보낸다(VITE_EXTENSION_ID). 비밀 키는 저장소에 두지 않는다.
const DEV_PUBLIC_KEY =
  "MIIBIjANBgkqhkiG9w0BAQEFAAOCAQ8AMIIBCgKCAQEAx0jPd1Et4oiBC7QAxrgSpzZl8u9gLAcXxX3uKIuc/teqeMZzmhbhsNB2EgQNs1PhwZjVHD3r2i/jKix8Qpy5z2TVmLxeEGmNJ0lO0HMlB73La7y5Gb1EM5NnVJCgWi4Yr4LsYtBIOfuIRPAmi6jYxaqRnv3DONKhtAG+Cw9nfrUgIWP/7QSCirJ9P54cHbAPrYQKXj16nNbmwg2PM67bMscpeWuNwX3uYoOl8DJn8qkQzcMeaY7ThzXIHQja6bv3WjLeX3IhVZmqLqGTZ1XSuPN1dveMgDuMLTrB9yFnCHPcF4i5HtD1TT8pWJeNTaKyfDg1ZAWqT2eQ20MAtNOhLQIDAQAB";

// See https://wxt.dev/api/reference/wxt/interfaces/inlineconfig.html
export default defineConfig({
  modules: ["@wxt-dev/module-react"],
  // 개발 빌드(.output/chrome-mv3)를 압축해제로 불러 쓰는 중이어도 덮어쓰지 않는다.
  ...(store ? { outDir: ".output/store" } : {}),
  manifest: {
    name: "Dragram",
    // scripting·activeTab: 우클릭한 탭에만, 메뉴를 누른 그때 문장 추출 스크립트를 주입한다.
    permissions: [
      "sidePanel",
      "contextMenus",
      "storage",
      "scripting",
      "activeTab",
    ],
    host_permissions: [`${new URL(apiBaseUrl).origin}/*`],
    // 웹 '로그인·확장 연결' 화면만 확장에 연결 메시지를 보낼 수 있다(#109).
    externally_connectable: { matches: [`${new URL(webOrigin).origin}/*`] },
    ...(store ? {} : { key: DEV_PUBLIC_KEY }),
    action: {},
  },
});
