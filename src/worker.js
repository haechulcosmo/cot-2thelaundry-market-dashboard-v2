import dashboardHtml from "../index.html";
import historyHtml from "../history.html";
import cloudJs from "../cloud.js";

const UPDATE_CALLBACK_TOKEN = "c7ef1d9a4b6240f69837e2ab51d2c8f4";
const UPDATE_STALE_MS = 2 * 60 * 60 * 1000;

function extractAppData(html) {
  const match = html.match(/(?:const|let)\s+APP_DATA\s*=\s*(\{[\s\S]*?\});\s*\n/);
  if (!match) return null;
  try {
    return JSON.parse(match[1]);
  } catch {
    return null;
  }
}

function kstParts(date = new Date()) {
  return Object.fromEntries(
    new Intl.DateTimeFormat("en", {
      timeZone: "Asia/Seoul",
      year: "numeric",
      month: "2-digit",
      day: "2-digit",
      hour: "2-digit",
      minute: "2-digit",
      second: "2-digit",
      hour12: false,
    })
      .formatToParts(date)
      .filter((part) => part.type !== "literal")
      .map((part) => [part.type, part.value]),
  );
}

function currentMonthKst(date = new Date()) {
  const parts = kstParts(date);
  return `${parts.year}-${parts.month}`;
}

function formatRequestedAt(date = new Date()) {
  const parts = kstParts(date);
  return `${parts.year}-${parts.month}-${parts.day} ${parts.hour}:${parts.minute} KST`;
}

function parseStatusTimestamp(value) {
  if (!value || typeof value !== "string") return null;

  const native = Date.parse(value);
  if (!Number.isNaN(native)) {
    return native;
  }

  const kstMatch = value.match(
    /^(\d{4})-(\d{2})-(\d{2})\s+(\d{2}):(\d{2})(?::(\d{2}))?\s*KST$/,
  );
  if (!kstMatch) return null;

  const [, year, month, day, hour, minute, second = "00"] = kstMatch;
  return Date.UTC(
    Number(year),
    Number(month) - 1,
    Number(day),
    Number(hour) - 9,
    Number(minute),
    Number(second),
  );
}

function isStatusStale(status) {
  if (!status || !["requested", "running"].includes(status.state)) return false;

  const timestamp =
    parseStatusTimestamp(status.startedAt) ||
    parseStatusTimestamp(status.requestedAt) ||
    parseStatusTimestamp(status.completedAt);

  if (!timestamp) return true;
  return Date.now() - timestamp > UPDATE_STALE_MS;
}

function statusSummary(status) {
  if (!status) return null;
  return {
    ...status,
    stale: isStatusStale(status),
  };
}

const dashboardAppData = extractAppData(dashboardHtml);

export default {
  async fetch(request, env) {
    const url = new URL(request.url);

    if (url.pathname === "/cloud.js") {
      return new Response(cloudJs, {
        headers: {
          "content-type": "application/javascript; charset=utf-8",
          "cache-control": "no-cache",
        },
      });
    }

    if (url.pathname === "/api/reviews") {
      if (request.method === "GET") {
        const reviews = await env.REVIEWS.get("review-overrides-v1", "json");
        return Response.json(
          { reviews: reviews || {} },
          { headers: { "cache-control": "no-store" } },
        );
      }

      if (request.method === "PUT") {
        let payload;
        try {
          payload = await request.json();
        } catch {
          return Response.json({ error: "JSON 형식이 올바르지 않습니다." }, { status: 400 });
        }

        const reviews = payload?.reviews;
        if (!reviews || Array.isArray(reviews) || typeof reviews !== "object") {
          return Response.json({ error: "reviews 객체가 필요합니다." }, { status: 400 });
        }

        const encoded = JSON.stringify(reviews);
        if (Object.keys(reviews).length > 5000 || encoded.length > 900000) {
          return Response.json({ error: "저장 가능한 검토 데이터 크기를 초과했습니다." }, { status: 413 });
        }

        await env.REVIEWS.put("review-overrides-v1", encoded);
        return Response.json({ ok: true, saved: Object.keys(reviews).length });
      }

      return new Response("Method not allowed", { status: 405 });
    }

    if (url.pathname === "/api/update") {
      if (request.method === "GET") {
        const status = await env.REVIEWS.get("monthly-update-status", "json");
        return Response.json(
          { status: statusSummary(status) },
          { headers: { "cache-control": "no-store" } },
        );
      }

      if (request.method === "POST") {
        if (request.headers.get("origin") !== url.origin) {
          return Response.json({ error: "대시보드 화면에서만 실행할 수 있습니다." }, { status: 403 });
        }

        const now = new Date();
        const month = currentMonthKst(now);
        const requestedAt = formatRequestedAt(now);
        const currentStatus = await env.REVIEWS.get("monthly-update-status", "json");
        const stale = isStatusStale(currentStatus);
        const sameMonthPending =
          currentStatus &&
          currentStatus.month === month &&
          ["requested", "running"].includes(currentStatus.state) &&
          !stale;

        if (sameMonthPending) {
          return Response.json(
            {
              error: "이미 같은 달 데이터 업데이트가 진행 중입니다. 잠시 후 다시 확인해 주세요.",
              status: statusSummary(currentStatus),
            },
            { status: 429 },
          );
        }

        const status = {
          state: "requested",
          month,
          requestedAt,
          requestedBy: "dashboard",
          supersededStatus: currentStatus && (stale || currentStatus.month !== month) ? currentStatus : null,
        };
        await env.REVIEWS.put("monthly-update-status", JSON.stringify(status));
        return Response.json({ ok: true, status: statusSummary(status) }, { status: 202 });
      }

      return new Response("Method not allowed", { status: 405 });
    }

    if (url.pathname === "/api/update/complete" && request.method === "POST") {
      if (request.headers.get("x-update-callback") !== UPDATE_CALLBACK_TOKEN) {
        return Response.json({ error: "권한이 없습니다." }, { status: 403 });
      }

      let payload = {};
      try {
        payload = await request.json();
      } catch {
        payload = {};
      }

      const rawState = String(payload.state || "").toLowerCase();
      const state = ["requested", "running", "completed", "failed"].includes(rawState)
        ? rawState
        : "completed";

      const currentStatus = await env.REVIEWS.get("monthly-update-status", "json");
      const status = {
        ...(currentStatus || {}),
        state,
        month: payload.month || currentStatus?.month || "",
        requestedAt: payload.requestedAt || currentStatus?.requestedAt || "",
        startedAt: payload.startedAt || currentStatus?.startedAt || "",
        completedAt:
          state === "completed" || state === "failed"
            ? payload.completedAt || new Date().toISOString()
            : currentStatus?.completedAt || "",
        summary: payload.summary || currentStatus?.summary || null,
        message: payload.message || "",
      };

      await env.REVIEWS.put("monthly-update-status", JSON.stringify(status));
      return Response.json({ ok: true, status: statusSummary(status) });
    }

    if (url.pathname === "/api/app-data" && request.method === "GET") {
      return Response.json(
        { data: dashboardAppData || null },
        { headers: { "cache-control": "no-store" } },
      );
    }

    if (url.pathname === "/api/source/dbland" && request.method === "GET") {
      if (request.headers.get("x-update-callback") !== UPDATE_CALLBACK_TOKEN) {
        return Response.json({ error: "권한이 없습니다." }, { status: 403 });
      }

      const page = Math.max(1, Math.min(1000, Number(url.searchParams.get("page") || 1)));
      const form = new URLSearchParams({
        type: "place",
        sch_ca_id: "021302",
        itemsPerPage: "50",
        currentPage: String(page),
      });

      const source = await fetch("https://db-land.kr/archive/proc/get_list.php", {
        method: "POST",
        headers: {
          "content-type": "application/x-www-form-urlencoded; charset=UTF-8",
          "x-requested-with": "XMLHttpRequest",
          referer: "https://db-land.kr/archive/place/021302/1",
          "user-agent": "Mozilla/5.0",
        },
        body: form.toString(),
      });

      return new Response(source.body, {
        status: source.status,
        headers: {
          "content-type": source.headers.get("content-type") || "application/json; charset=utf-8",
          "cache-control": "no-store",
        },
      });
    }

    if (url.pathname === "/" || url.pathname === "/index.html") {
      return new Response(dashboardHtml, {
        headers: {
          "content-type": "text/html; charset=utf-8",
          "cache-control": "no-cache",
          "x-content-type-options": "nosniff",
          "x-frame-options": "DENY",
          "referrer-policy": "strict-origin-when-cross-origin",
        },
      });
    }

    if (url.pathname === "/history.html") {
      return new Response(historyHtml, {
        headers: {
          "content-type": "text/html; charset=utf-8",
          "cache-control": "no-cache",
          "x-content-type-options": "nosniff",
          "x-frame-options": "DENY",
          "referrer-policy": "strict-origin-when-cross-origin",
        },
      });
    }

    return new Response("Not found", { status: 404 });
  },
};
