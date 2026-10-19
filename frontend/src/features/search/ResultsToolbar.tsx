import type { SearchResponse, SingleFrameResponse } from "../../api/types";
import { VideoLookup } from "../results/VideoLookup";
import { shownResults } from "../results/resultBrowsing";
import type { FrameSize } from "../results/useResultViewPreferences";
import { SubmissionLogButton } from "../submission/SubmissionLogButton";
import { matchesProgram, type ProgramFilter, programOptions } from "./programFilter";
import type { GroupSort } from "./SearchResultsView";

const FRAME_SIZES: { value: FrameSize; label: string; title: string }[] = [
  { value: "S", label: "S", title: "Ảnh nhỏ: nhiều kết quả trên một màn hình" },
  { value: "M", label: "M", title: "Ảnh vừa" },
  { value: "L", label: "L", title: "Ảnh lớn: dễ xem chi tiết" },
];

interface ResultsToolbarProps {
  /** The response on screen; undefined while a search runs or after it failed. */
  response: SearchResponse | SingleFrameResponse | undefined;
  /** How long the search on screen took, when it was just run. */
  elapsedMs: number | null;
  /** When the response on screen was saved earlier: its time, and how to search again. */
  saved: { at: number; onSearchAgain: () => void } | null;
  /** When similar keyframes are on screen: the example, and how to return to the search. */
  similarTo: { videoId: string; frameId: number; onBack: (() => void) | null } | null;
  frameSize: FrameSize;
  onFrameSizeChange: (value: FrameSize) => void;
  collapseShots: boolean;
  onCollapseShotsChange: (value: boolean) => void;
  groupByVideo: boolean;
  onGroupByVideoChange: (value: boolean) => void;
  groupSort: GroupSort;
  onGroupSortChange: (value: GroupSort) => void;
  programFilter: ProgramFilter;
  onProgramFilterChange: (value: ProgramFilter) => void;
}

export function ResultsToolbar({
  response,
  elapsedMs,
  saved,
  similarTo,
  frameSize,
  onFrameSizeChange,
  collapseShots,
  onCollapseShotsChange,
  groupByVideo,
  onGroupByVideoChange,
  groupSort,
  onGroupSortChange,
  programFilter,
  onProgramFilterChange,
}: ResultsToolbarProps) {
  const hasResults = Boolean(response?.results.length);
  const programResults =
    response?.results.filter((result) => matchesProgram(result.video_id, programFilter)) ?? [];
  const resultProgramOptions = programOptions(
    response?.results.map((result) => result.video_id) ?? [],
    programFilter,
  );
  const singleFrames = response !== undefined && response.query_type !== "TRAKE";
  const showProgramFilter = hasResults && response?.query_type !== "TRAFFIC";
  const shotCount =
    singleFrames && collapseShots
      ? shownResults(programResults as SingleFrameResponse["results"], {
          collapse: true,
          hiddenVideos: new Set(),
        }).length
      : null;

  const showViewRow = hasResults;

  return (
    <header className="toolbar" aria-label="Công cụ kết quả">
      {/* What is on screen, and the tools that do not depend on it. */}
      <div className="toolbar__row">
        <div className="toolbar__summary">
          {similarTo && (
            <p className="toolbar__similar" role="status">
              Ảnh giống <strong>{similarTo.videoId}</strong> frame {similarTo.frameId}
              {similarTo.onBack && (
                <button type="button" className="button button--text" onClick={similarTo.onBack}>
                  ← Về kết quả tìm
                </button>
              )}
            </p>
          )}
          {response && hasResults ? (
            <p className="toolbar__count">
              <strong>{programResults.length}</strong>{" "}
              {response.query_type === "TRAKE" ? "chuỗi ứng viên" : "kết quả"}
              {shotCount !== null && <span> · {shotCount} shot</span>}
              {response.query_type === "TRAFFIC" && (
                <span>
                  {" "}
                  trong {response.filtered_keyframes.toLocaleString("vi-VN")} keyframe qua bộ lọc
                </span>
              )}
              {elapsedMs !== null && (
                <span title="Thời gian từ lúc gửi tới lúc nhận kết quả">
                  {" "}
                  · {(elapsedMs / 1000).toLocaleString("vi-VN", { maximumFractionDigits: 2 })} s
                </span>
              )}
            </p>
          ) : null}
          {saved && response ? (
            <p className="toolbar__saved" role="status">
              Kết quả đã lưu lúc {new Date(saved.at).toLocaleTimeString("vi-VN")}
              <button type="button" className="button button--text" onClick={saved.onSearchAgain}>
                Tìm lại
              </button>
            </p>
          ) : null}
        </div>
        <div className="toolbar__tools">
          <VideoLookup />
          <SubmissionLogButton />
        </div>
      </div>

      {/* How the results are laid out; only once there are results. */}
      {showViewRow && (
        <div className="toolbar__row toolbar__row--view">
          {singleFrames && (
            <div className="toolbar__set" role="group" aria-label="Hiển thị">
              <span className="toolbar__caption" aria-hidden="true">
                Hiển thị
              </span>
              <label className="toggle" title="Mỗi shot chỉ giữ ảnh có hạng cao nhất">
                <input
                  type="checkbox"
                  checked={collapseShots}
                  onChange={(event) => onCollapseShotsChange(event.target.checked)}
                />
                <span>1 ảnh mỗi shot</span>
              </label>
              <label className="toggle">
                <input
                  type="checkbox"
                  checked={groupByVideo}
                  onChange={(event) => onGroupByVideoChange(event.target.checked)}
                />
                <span>Gộp theo video</span>
              </label>
              {groupByVideo && (
                <select
                  className="toolbar__select"
                  aria-label="Sắp xếp trong nhóm"
                  value={groupSort}
                  onChange={(event) => onGroupSortChange(event.target.value as GroupSort)}
                >
                  <option value="score">Theo điểm</option>
                  <option value="time">Theo thời gian</option>
                </select>
              )}
            </div>
          )}
          {showProgramFilter && (
            <div className="toolbar__set">
              <span className="toolbar__caption" aria-hidden="true">
                Lọc
              </span>
              <select
                className="toolbar__select"
                aria-label="Chương trình"
                value={programFilter}
                onChange={(event) => onProgramFilterChange(event.target.value)}
              >
                <option value="ALL">Mọi chương trình</option>
                {resultProgramOptions.map(({ key, label }) => (
                  <option key={key} value={key}>
                    {label}
                  </option>
                ))}
              </select>
            </div>
          )}
          {singleFrames && (
            <div className="toolbar__set toolbar__set--end">
              <span className="toolbar__caption" aria-hidden="true">
                Cỡ ảnh
              </span>
              <div className="size-switch" role="radiogroup" aria-label="Cỡ ảnh">
                {FRAME_SIZES.map(({ value, label, title }) => (
                  <label key={value} title={title}>
                    <input
                      type="radio"
                      name="frame-size"
                      value={value}
                      aria-label={title}
                      checked={frameSize === value}
                      onChange={() => onFrameSizeChange(value)}
                    />
                    <span>{label}</span>
                  </label>
                ))}
              </div>
            </div>
          )}
        </div>
      )}
    </header>
  );
}
