const API_ROOT = "http://localhost:8000/api";

async function analyze(payload) {
  const response = await fetch(`${API_ROOT}/sentences/analyze/`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  const body = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(body.detail || "백엔드 요청을 처리할 수 없습니다.");
  return body;
}

chrome.runtime.onMessage.addListener((message, _sender, respond) => {
  if (message.type !== "DRAGRAM_ANALYZE") return;
  analyze(message.payload).then(
    (result) => respond({ ok: true, result }),
    (error) => respond({ ok: false, error: error.message }),
  );
  return true;
});
