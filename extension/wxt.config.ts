import { defineConfig } from "wxt";

// utils/api.ts와 같은 기본값. 바꾸려면 빌드할 때 WXT_API_BASE_URL을 준다.
const apiBaseUrl = process.env.WXT_API_BASE_URL ?? "http://localhost:8000";

// See https://wxt.dev/api/reference/wxt/interfaces/inlineconfig.html
export default defineConfig({
  modules: ["@wxt-dev/module-react"],
  manifest: {
    name: "Dragram",
    permissions: ["sidePanel", "contextMenus", "storage"],
    host_permissions: [`${new URL(apiBaseUrl).origin}/*`],
    action: {},
  },
});
