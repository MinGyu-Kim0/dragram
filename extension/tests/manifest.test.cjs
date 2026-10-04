const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const vm = require("node:vm");

const root = path.resolve(__dirname, "..");
const manifest = JSON.parse(fs.readFileSync(path.join(root, "manifest.json"), "utf8"));

test("Chrome can load the registered scripts and popup", () => {
  const scripts = [
    manifest.background.service_worker,
    ...manifest.content_scripts.flatMap((entry) => entry.js),
  ];
  const popup = path.join(root, manifest.action.default_popup);
  const html = fs.readFileSync(popup, "utf8");

  for (const script of scripts) {
    new vm.Script(fs.readFileSync(path.join(root, script), "utf8"), { filename: script });
  }
  const popupScripts = [...html.matchAll(/<script\b[^>]*src="([^"]+)"/g)];
  assert.ok(popupScripts.length > 0);
  for (const [, script] of popupScripts) {
    new vm.Script(fs.readFileSync(path.resolve(path.dirname(popup), script), "utf8"));
  }
});

test("sentence splitting is available before the content script runs", () => {
  const scripts = manifest.content_scripts[0].js;
  const context = vm.createContext({});
  for (const script of scripts.slice(0, -1)) {
    vm.runInContext(fs.readFileSync(path.join(root, script), "utf8"), context);
  }
  const result = context.Dragram.splitSentences(" 行きます。帰ります。 ");
  assert.deepEqual(Array.from(result), ["行きます。", "帰ります。"]);
});
