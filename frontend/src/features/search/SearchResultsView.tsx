import { useEffect, useState } from "react";

import { friendlySearchError } from "../../api/client";
import type { SearchResponse, SingleFrameResponse } from "../../api/types";
import { SingleResultInspector } from "../results/SingleResultInspector";
import { TrakeResultInspector } from "../results/TrakeResultInspector";
import { matchesProgram, type ProgramFilter } from "./programFilter";

export type GroupSort = "score" | "time";

interface SearchResultsViewProps {
  isPending: boolean;
  error: unknown;
  /** The response on screen, or null before the first search. */
  response: SearchResponse | SingleFrameResponse | null;
  /** EVENT count the TRAKE request asked for, to check its sequences. */
  trakeEventCount: number | null;
  maxAnswerLength: number;
  groupByVideo: boolean;
  groupSort: GroupSort;
  programFilter: ProgramFilter;
  collapseShots: boolean;
  onFindSimilar?: (videoId: string, frameId: number) => void;
}

const SKELETON_FRAMES = 12;

/** The result sheet: loading, error, empty states, or the inspector of the response shown. */
export function SearchResultsView({
  isPending,
  error,
  response,
  trakeEventCount,
  maxAnswerLength,
  groupByVideo,
  groupSort,
  programFilter,
  collapseShots,
  onFindSimilar,
}: SearchResultsViewProps) {
  if (isPending) return <SearchPending />;

  if (error !== undefined) {
    return (
      <section className="sheet-state sheet-state--error" role="alert">
        <strong>Tìm kiếm không thành công</strong>
        <p>{friendlySearchError(error)}</p>
      </section>
    );
  }

  if (!response) {
    return (
      <section className="sheet-state">
        <strong>Chưa có kết quả</strong>
        <p>Nhập truy vấn ở cột trái rồi nhấn Enter. Kết quả hiện ở đây theo thứ hạng.</p>
        <p className="sheet-state__hint">
          Nhấn <kbd>?</kbd> để xem phím tắt.
        </p>
      </section>
    );
  }

  if (response.results.length === 0) {
    return (
      <section className="sheet-state" role="status">
        <strong>Không tìm thấy kết quả</strong>
        <p>Thử mô tả theo cách khác hoặc bật thêm nguồn tìm kiếm.</p>
      </section>
    );
  }

  const displayedResults = response.results.filter((result) =>
    matchesProgram(result.video_id, programFilter),
  );

  if (displayedResults.length === 0) {
    return (
      <section className="sheet-state" role="status">
        <strong>Không có kết quả thuộc chương trình đã chọn</strong>
        <p>Chọn Mọi chương trình để xem lại toàn bộ kết quả.</p>
      </section>
    );
  }

  const displayedResponse = { ...response, results: displayedResults } as
    | SearchResponse
    | SingleFrameResponse;

  return (
    <section className="result-preview" aria-live="polite">
      {displayedResponse.query_type === "TRAKE" ? (
        trakeEventCount === null ? (
          <section className="sheet-state sheet-state--error" role="alert">
            <strong>Không hiển thị được kết quả TRAKE</strong>
            <p>Thiếu số EVENT đã gửi để kiểm tra phản hồi.</p>
          </section>
        ) : (
          <TrakeResultInspector
            response={displayedResponse}
            expectedEventCount={trakeEventCount}
          />
        )
      ) : (
        <SingleResultInspector
          response={displayedResponse}
          maxAnswerLength={maxAnswerLength}
          groupByVideo={groupByVideo}
          groupSort={groupSort}
          collapseShots={collapseShots}
          onFindSimilar={onFindSimilar}
        />
      )}
    </section>
  );
}

/** A sheet of empty frames where the results will land, and how long the search has run. */
function SearchPending() {
  const [seconds, setSeconds] = useState(0);
  useEffect(() => {
    const started = Date.now();
    const timer = window.setInterval(
      () => setSeconds(Math.floor((Date.now() - started) / 1000)),
      1000,
    );
    return () => window.clearInterval(timer);
  }, []);

  return (
    <section className="search-pending" aria-busy="true">
      <p className="search-pending__status" aria-live="polite">
        <span className="spinner" aria-hidden="true" />
        <strong>Đang tìm kiếm…</strong>
        {/* Not live: a screen reader would announce every second. */}
        {seconds >= 2 && <span aria-hidden="true">{seconds} giây</span>}
      </p>
      <ol className="contact-sheet" aria-hidden="true">
        {Array.from({ length: SKELETON_FRAMES }, (_, index) => (
          <li className="frame frame--skeleton" key={index}>
            <span className="frame__image" />
            <span className="frame__edge" />
          </li>
        ))}
      </ol>
    </section>
  );
}
