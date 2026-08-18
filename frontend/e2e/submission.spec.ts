import { expect, test, type Page, type Route } from "@playwright/test";

const config = {
  min_top_k: 1,
  max_top_k: 100,
  default_top_k: 20,
  max_trake_events: 4,
  max_query_length: 4_000,
  max_answer_length: 4_000,
  model_choices: ["siglip", "beit3"],
};

interface SubmissionPayload {
  query_type: "KIS" | "VQA" | "TRAKE";
  filename: string;
  rows: Array<{
    video_id: string;
    frame_id?: number;
    frame_ids?: number[];
    answer?: string;
  }>;
}

function csvField(value: string | number): string {
  const text = String(value);
  return /[",\r\n]/.test(text) ? `"${text.replaceAll('"', '""')}"` : text;
}

function renderCsv(payload: SubmissionPayload): string {
  return payload.rows
    .map((row) => {
      if (payload.query_type === "TRAKE") {
        return [row.video_id, ...(row.frame_ids ?? [])].map(csvField).join(",");
      }
      if (payload.query_type === "VQA") {
        return [row.video_id, row.frame_id ?? 0, row.answer ?? ""].map(csvField).join(",");
      }
      return [row.video_id, row.frame_id ?? 0].map(csvField).join(",");
    })
    .join("\r\n") + "\r\n";
}

function sanitizedFilename(filename: string, queryType: string): string {
  const basename = filename.replaceAll("\\", "/").split("/").at(-1) || `${queryType}_submission`;
  const stem = basename.includes(".") ? basename.slice(0, basename.lastIndexOf(".")) : basename;
  return `${stem || `${queryType}_submission`}.csv`;
}

function singleResults(queryType: "KIS" | "VQA") {
  return {
    query_type: queryType,
    original_query: "fixture query",
    enhanced_query: null,
    model_choices: ["siglip", "beit3"],
    results: [
      {
        result_id: `${queryType.toLowerCase()}-a`,
        rank: 1,
        video_id: "L01_V001",
        frame_id: 101,
        keyframe_url: "/media/keyframes/a.jpg",
        segment_id: "segment-a",
        asr_text: "First transcript",
        ocr_text: "",
        objects: [],
        similarity_score: 0.95,
        answer: "",
      },
      {
        result_id: `${queryType.toLowerCase()}-b`,
        rank: 2,
        video_id: "L02_V002",
        frame_id: 202,
        keyframe_url: "/media/keyframes/b.jpg",
        segment_id: "segment-b",
        asr_text: "Second transcript",
        ocr_text: "",
        objects: [],
        similarity_score: 0.9,
        answer: "",
      },
    ],
  };
}

function trakeResults() {
  const event = (eventIndex: number, frameId: number) => ({
    event_index: eventIndex,
    frame_id: frameId,
    keyframe_url: `/media/keyframes/${frameId}.jpg`,
    segment_id: `segment-${frameId}`,
    asr_text: `Transcript ${frameId}`,
    ocr_text: "",
    objects: [],
    similarity_score: 0.9,
  });
  return {
    query_type: "TRAKE",
    original_query: "fixture sequence",
    enhanced_query: null,
    model_choices: ["siglip", "beit3"],
    results: [
      {
        result_id: "trake-a",
        rank: 1,
        video_id: "L01_V001",
        similarity_score: 0.94,
        events: [event(1, 101), event(2, 151)],
      },
      {
        result_id: "trake-b",
        rank: 2,
        video_id: "L02_V002",
        similarity_score: 0.9,
        events: [event(1, 305), event(2, 390)],
      },
    ],
  };
}

async function fulfillJson(route: Route, body: unknown) {
  await route.fulfill({
    status: 200,
    contentType: "application/json",
    body: JSON.stringify(body),
  });
}

async function installApiServer(page: Page) {
  await page.route(
    /\/api\/(?:health|config|search|submissions\/(?:render|download))(?:\?.*)?$/,
    async (route) => {
      const path = new URL(route.request().url()).pathname;
      if (path === "/api/health") return fulfillJson(route, { status: "ok" });
      if (path === "/api/config") return fulfillJson(route, config);
      if (path === "/api/search") {
        const payload = route.request().postDataJSON() as {
          query_type: "KIS" | "VQA" | "TRAKE";
        };
        return fulfillJson(
          route,
          payload.query_type === "TRAKE" ? trakeResults() : singleResults(payload.query_type),
        );
      }
      if (path.startsWith("/api/submissions/")) {
        const payload = route.request().postDataJSON() as SubmissionPayload;
        const content = renderCsv(payload);
        const filename = sanitizedFilename(payload.filename, payload.query_type.toLowerCase());
        if (path.endsWith("/download")) {
          return route.fulfill({
            status: 200,
            body: content,
            headers: {
              "Content-Type": "text/csv; charset=utf-8",
              "Content-Disposition": `attachment; filename="${filename}"; filename*=UTF-8''${encodeURIComponent(filename)}`,
            },
          });
        }
        return fulfillJson(route, {
          content,
          filename,
          row_count: payload.rows.length,
          warnings:
            payload.query_type === "VQA" && payload.rows.some((row) => !row.answer?.trim())
              ? ["1 VQA row(s) have an empty answer"]
              : [],
        });
      }
      await route.fulfill({ status: 404, body: "Not found" });
    },
  );
}

test.beforeEach(async ({ page }) => {
  await installApiServer(page);
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "AIC Retrieval Inspector" })).toBeVisible();
  await expect(page.getByText("Backend connected: ok")).toBeVisible({ timeout: 15_000 });
});

test("KIS reorder drives preview and backend attachment download", async ({ page }) => {
  await page.getByLabel(/^Query KIS/).fill("person opens a laptop");
  await page.getByRole("button", { name: "Search KIS" }).click();
  await page.getByRole("button", { name: "Move L02_V002 up" }).click();
  await page.getByRole("button", { name: "Preview submission" }).click();

  await expect(page.getByTestId("submission-preview-content")).toContainText(
    "L02_V002,202\nL01_V001,101",
  );
  await page.getByRole("button", { name: "Close submission preview" }).click();

  const downloadPromise = page.waitForEvent("download");
  await page.getByRole("button", { name: "Download submission" }).click();
  await expect((await downloadPromise).suggestedFilename()).toBe("kis_submission.csv");
});

test("VQA Unicode answer stays with its candidate after reorder", async ({ page }) => {
  await page.getByRole("tab", { name: /VQA/ }).click();
  await page.getByLabel(/^Câu hỏi VQA/).fill("What color is the cup?");
  await page.getByRole("button", { name: "Search VQA" }).click();
  const answer = "màu xanh, đậm — Việt Nam";
  await page.getByLabel("VQA answer").first().fill(answer);
  await page.getByRole("button", { name: "Move L01_V001 down" }).click();
  await page.getByRole("button", { name: "Preview submission" }).click();

  const preview = page.getByTestId("submission-preview-content");
  await expect(preview).toContainText("L02_V002,202,");
  await expect(preview).toContainText(`L01_V001,101,"${answer}"`);
});

test("TRAKE exports reordered rows with fixed event frame order", async ({ page }) => {
  await page.getByRole("tab", { name: /TRAKE/ }).click();
  await page.getByLabel(/^Main query TRAKE/).fill("two temporal events");
  await page.getByLabel("Event 1").fill("first event");
  await page.getByLabel("Event 2").fill("second event");
  await page.getByRole("button", { name: "Search TRAKE" }).click();
  await page.getByRole("button", { name: "Move result trake-b up" }).click();
  await page.getByRole("button", { name: "Preview submission" }).click();

  await expect(page.getByTestId("submission-preview-content")).toContainText(
    "L02_V002,305,390\nL01_V001,101,151",
  );
});
