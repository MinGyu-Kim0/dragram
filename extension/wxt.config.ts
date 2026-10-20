import { defineConfig } from "wxt";

// utils/api.ts와 같은 기본값. 바꾸려면 빌드할 때 WXT_API_BASE_URL을 준다.
const apiBaseUrl = process.env.WXT_API_BASE_URL ?? "http://localhost:8000";

// See https://wxt.dev/api/reference/wxt/interfaces/inlineconfig.html
export default defineConfig({
  modules: ["@wxt-dev/module-react"],
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
    action: {},
  },
});
