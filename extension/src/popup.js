const MODELS = ["gpt-5.6-luna", "gpt-5.6-terra"];
const enabledInput = document.querySelector("#enabled");
const modelSelect = document.querySelector("#model");
const status = document.querySelector("#status");

let settings;

function render() {
  enabledInput.checked = settings.enabled;
  modelSelect.value = settings.model;
  modelSelect.disabled = !settings.enabled;
  status.textContent = settings.enabled ? `분석 사용 중 · ${settings.model.replace("gpt-5.6-", "")}` : "분석이 꺼져 있습니다.";
}

chrome.storage.local.get({ enabled: true, model: MODELS[0] }, (stored) => {
  settings = {
    enabled: stored.enabled !== false,
    model: MODELS.includes(stored.model) ? stored.model : MODELS[0],
  };
  render();

  enabledInput.addEventListener("change", () => {
    settings.enabled = enabledInput.checked;
    chrome.storage.local.set({ enabled: settings.enabled });
    render();
  });

  modelSelect.addEventListener("change", () => {
    settings.model = modelSelect.value;
    chrome.storage.local.set({ model: settings.model });
    render();
  });
});
