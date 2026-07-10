(() => {
  const REVIEW_KEY = "thelaundry-review-overrides-v1";
  const SYNC_MARKER = "thelaundry-cloud-sync-v1";

  function notice(message, kind = "info") {
    let el = document.getElementById("cloudNotice");
    if (!el) {
      el = document.createElement("div");
      el.id = "cloudNotice";
      el.style.cssText =
        "position:fixed;right:18px;bottom:18px;z-index:9999;max-width:380px;" +
        "padding:12px 15px;border-radius:12px;color:#fff;font:700 13px/1.45 system-ui;" +
        "box-shadow:0 8px 28px rgba(17,47,70,.24)";
      document.body.appendChild(el);
    }
    el.style.background = kind === "error" ? "#c94b4b" : "#173f5f";
    el.textContent = message;
    window.clearTimeout(notice.timer);
    notice.timer = window.setTimeout(() => el.remove(), 5000);
  }

  async function api(path, options = {}) {
    const response = await fetch(path, {
      headers: { "content-type": "application/json", ...(options.headers || {}) },
      ...options,
    });
    if (!response.ok) throw new Error(`${response.status} ${await response.text()}`);
    return response.status === 204 ? null : response.json();
  }

  function localReviews() {
    try {
      return JSON.parse(localStorage.getItem(REVIEW_KEY) || "{}");
    } catch {
      return {};
    }
  }

  async function loadSharedReviews() {
    try {
      const payload = await api("/api/reviews");
      const shared = payload.reviews || {};
      const local = localReviews();
      const merged = { ...shared, ...local };
      const mergedText = JSON.stringify(merged);
      if (mergedText !== JSON.stringify(local) && sessionStorage.getItem(SYNC_MARKER) !== mergedText) {
        localStorage.setItem(REVIEW_KEY, mergedText);
        sessionStorage.setItem(SYNC_MARKER, mergedText);
        location.reload();
        return;
      }
      sessionStorage.removeItem(SYNC_MARKER);
    } catch (error) {
      console.warn("공용 검토결과 불러오기 실패", error);
    }
  }

  async function saveSharedReviews() {
    try {
      await api("/api/reviews", {
        method: "PUT",
        body: JSON.stringify({ reviews: localReviews() }),
      });
      notice("검토결과가 공용 데이터로 저장되었습니다.");
    } catch (error) {
      console.warn("공용 검토결과 저장 실패", error);
      notice("공용 저장에 실패했습니다. 잠시 후 다시 시도해 주세요.", "error");
    }
  }

  async function requestMonthlyUpdate(button) {
    const original = button.textContent;
    button.disabled = true;
    button.textContent = "업데이트 요청 중...";
    try {
      const payload = await api("/api/update", { method: "POST", body: "{}" });
      const status = payload.status || {};
      notice(`${status.month || "이번 달"} 데이터 업데이트 요청이 접수되었습니다.`);
      button.textContent = "업데이트 요청 완료";
      button.title = `요청시각 ${status.requestedAt || ""}`;
      window.setTimeout(() => {
        button.disabled = false;
        button.textContent = original;
      }, 30000);
    } catch (error) {
      const message = String(error).includes("429")
        ? "이미 업데이트 요청이 진행 중입니다. 잠시 후 다시 확인해 주세요."
        : "업데이트 요청에 실패했습니다. 잠시 후 다시 시도해 주세요.";
      notice(message, "error");
      button.disabled = false;
      button.textContent = original;
    }
  }

  async function backendAvailable() {
    try {
      const response = await fetch("/api/reviews", { method: "GET" });
      return response.ok;
    } catch {
      return false;
    }
  }

  async function addCloudControls() {
    const csv = document.getElementById("csvBtn");
    if (!csv || document.getElementById("monthlyUpdateBtn")) return;
    if (!(await backendAvailable())) return;

    const update = document.createElement("button");
    update.id = "monthlyUpdateBtn";
    update.className = "btn";
    update.type = "button";
    update.textContent = "데이터 업데이트";
    update.title = "오늘 기준 최신 자료까지 갱신 요청합니다. 매월 1일 자동 갱신도 함께 동작합니다.";
    update.addEventListener("click", () => requestMonthlyUpdate(update));
    csv.parentElement.insertBefore(update, csv);

    const history = document.createElement("a");
    history.className = "btn secondary";
    history.href = "/history.html";
    history.textContent = "개별 데이터 검토";
    history.title = "개별 후보 데이터를 열어 원본과 판정 내용을 확인합니다.";
    csv.parentElement.insertBefore(history, csv);

    const sync = document.createElement("button");
    sync.className = "btn secondary";
    sync.type = "button";
    sync.textContent = "공용데이터 새로고침";
    sync.addEventListener("click", async () => {
      sessionStorage.removeItem(SYNC_MARKER);
      await loadSharedReviews();
      location.reload();
    });
    csv.parentElement.insertBefore(sync, csv);
  }

  document.addEventListener(
    "click",
    (event) => {
      if (event.target && ["saveReview", "resetReview"].includes(event.target.id)) {
        window.setTimeout(saveSharedReviews, 80);
      }
    },
    true,
  );

  addCloudControls();
  loadSharedReviews();
})();
