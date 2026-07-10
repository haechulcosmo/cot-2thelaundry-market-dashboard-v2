import dashboardHtml from "../index.html";
import historyHtml from "../history.html";
import cloudJs from "../cloud.js";

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
          { status: status || null },
          { headers: { "cache-control": "no-store" } },
        );
      }

      if (request.method === "POST") {
        if (request.headers.get("origin") !== url.origin) {
          return Response.json({ error: "대시보드에서만 실행할 수 있습니다." }, { status: 403 });
        }

        const currentStatus = await env.REVIEWS.get("monthly-update-status", "json");
        if (currentStatus?.state === "requested" || currentStatus?.state === "running") {
          return Response.json(
            { error: "이미 갱신 작업이 요청되었습니다. 잠시 후 다시 확인해 주세요." },
            { status: 429 },
          );
        }

        const parts = Object.fromEntries(
          new Intl.DateTimeFormat("en", {
            timeZone: "Asia/Seoul",
            year: "numeric",
            month: "2-digit",
            day: "2-digit",
            hour: "2-digit",
            minute: "2-digit",
            hour12: false,
          })
            .formatToParts(new Date())
            .filter((part) => part.type !== "literal")
            .map((part) => [part.type, part.value]),
        );
        const month = `${parts.year}-${parts.month}`;
        const requestedAt = `${parts.year}-${parts.month}-${parts.day} ${parts.hour}:${parts.minute} KST`;

        const status = { state: "requested", month, requestedAt };
        await env.REVIEWS.put("monthly-update-status", JSON.stringify(status));
        return Response.json({ ok: true, status }, { status: 202 });
      }

      return new Response("Method not allowed", { status: 405 });
    }

    if (url.pathname === "/api/update/complete" && request.method === "POST") {
      if (request.headers.get("x-update-callback") !== "c7ef1d9a4b6240f69837e2ab51d2c8f4") {
        return Response.json({ error: "권한이 없습니다." }, { status: 403 });
      }
      let payload = {};
      try {
        payload = await request.json();
      } catch {
        // 완료 신호에는 본문이 없어도 됩니다.
      }
      const status = {
        state: payload.state === "running" ? "running" : "completed",
        month: payload.month || "",
        requestedAt: payload.requestedAt || "",
        completedAt: payload.completedAt || new Date().toISOString(),
        summary: payload.summary || null,
      };
      await env.REVIEWS.put("monthly-update-status", JSON.stringify(status));
      return Response.json({ ok: true, status });
    }

    if (url.pathname === "/api/source/dbland" && request.method === "GET") {
      if (request.headers.get("x-update-callback") !== "c7ef1d9a4b6240f69837e2ab51d2c8f4") {
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
