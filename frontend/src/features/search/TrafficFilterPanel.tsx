import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";

import { getTrafficOptions } from "../../api/client";
import type { Daypart, TrafficCamera, TrafficFilters, Weather } from "../../api/types";

export const EMPTY_TRAFFIC_FILTERS: TrafficFilters = {
  camera_ids: [],
  dates: [],
  dayparts: [],
  weathers: [],
};

const DAYPART_LABELS: Record<Daypart, string> = {
  morning: "Sáng",
  midday: "Trưa",
  night: "Tối",
};

const WEATHER_LABELS: Record<Weather, string> = {
  dry: "Khô ráo",
  wet: "Mưa / đường ướt",
};

/** Case- and accent-insensitive key, so "le hong phong" matches "Lê Hồng Phong". */
export function foldText(text: string): string {
  return text
    .replace(/đ/g, "d")
    .replace(/Đ/g, "D")
    .normalize("NFD")
    .replace(/[̀-ͯ]/g, "")
    .toLowerCase();
}

function toggle<T>(values: T[], value: T): T[] {
  return values.includes(value) ? values.filter((item) => item !== value) : [...values, value];
}

function formatDate(date: string): string {
  const [, month, day] = date.split("-");
  return `${day}/${month}`;
}

interface TrafficFilterPanelProps {
  filters: TrafficFilters;
  onChange: (filters: TrafficFilters) => void;
}

export function TrafficFilterPanel({ filters, onChange }: TrafficFilterPanelProps) {
  const [streetQuery, setStreetQuery] = useState("");
  const optionsQuery = useQuery({
    queryKey: ["traffic-options"],
    queryFn: ({ signal }) => getTrafficOptions(signal),
    retry: false,
    staleTime: Infinity,
  });
  const options = optionsQuery.data;

  const cameraById = useMemo(
    () => new Map((options?.cameras ?? []).map((camera) => [camera.camera_id, camera])),
    [options],
  );
  const visibleCameras = useMemo(() => {
    const key = foldText(streetQuery.trim());
    const cameras = options?.cameras ?? [];
    if (!key) return cameras;
    return cameras.filter(
      (camera) =>
        foldText(camera.name).includes(key) ||
        camera.streets.some((street) => foldText(street).includes(key)),
    );
  }, [options, streetQuery]);

  const update = (patch: Partial<TrafficFilters>) => onChange({ ...filters, ...patch });
  const selectedCameras = filters.camera_ids
    .map((id) => cameraById.get(id))
    .filter((camera): camera is TrafficCamera => camera !== undefined);
  const hasFilters =
    filters.camera_ids.length > 0 ||
    filters.dates.length > 0 ||
    filters.dayparts.length > 0 ||
    filters.weathers.length > 0 ||
    Boolean(filters.clock_from) ||
    Boolean(filters.clock_to);

  if (optionsQuery.isPending) {
    return <p className="traffic-filters__status">Đang tải metadata camera…</p>;
  }
  if (optionsQuery.isError || !options?.available) {
    return (
      <p className="traffic-filters__status traffic-filters__status--error" role="alert">
        Không tải được metadata camera giao thông.
      </p>
    );
  }

  return (
    <section className="traffic-filters" aria-label="Traffic filters">
      <header className="traffic-filters__header">
        <strong>Bộ lọc metadata</strong>
        <button
          type="button"
          className="traffic-filters__clear"
          disabled={!hasFilters}
          onClick={() => {
            onChange(EMPTY_TRAFFIC_FILTERS);
            setStreetQuery("");
          }}
        >
          Xóa bộ lọc
        </button>
      </header>

      <div className="traffic-filters__group">
        <label className="traffic-filters__label" htmlFor="traffic-street">
          Tên đường / camera
          <small>
            {filters.camera_ids.length
              ? `${filters.camera_ids.length} camera đã chọn`
              : `Tất cả ${options.cameras.length} camera`}
          </small>
        </label>
        <input
          id="traffic-street"
          className="traffic-filters__input"
          type="search"
          value={streetQuery}
          placeholder="Gõ tên đường, không cần dấu…"
          autoComplete="off"
          onChange={(event) => setStreetQuery(event.target.value)}
        />
        {selectedCameras.length > 0 && (
          <ul className="traffic-filters__chips" aria-label="Selected cameras">
            {selectedCameras.map((camera) => (
              <li key={camera.camera_id}>
                <span>{camera.name}</span>
                <button
                  type="button"
                  aria-label={`Bỏ ${camera.name}`}
                  onClick={() =>
                    update({ camera_ids: filters.camera_ids.filter((id) => id !== camera.camera_id) })
                  }
                >
                  ×
                </button>
              </li>
            ))}
          </ul>
        )}
        <ul className="traffic-filters__cameras" aria-label="Cameras">
          {visibleCameras.map((camera) => (
            <li key={camera.camera_id}>
              <label>
                <input
                  type="checkbox"
                  checked={filters.camera_ids.includes(camera.camera_id)}
                  onChange={() =>
                    update({ camera_ids: toggle(filters.camera_ids, camera.camera_id) })
                  }
                />
                <span>{camera.name}</span>
                <small>{camera.video_ids.length} video</small>
              </label>
            </li>
          ))}
          {visibleCameras.length === 0 && (
            <li className="traffic-filters__empty">Không có camera khớp.</li>
          )}
        </ul>
        {streetQuery.trim() && visibleCameras.length > 0 && (
          <button
            type="button"
            className="traffic-filters__select-all"
            onClick={() =>
              update({
                camera_ids: Array.from(
                  new Set([...filters.camera_ids, ...visibleCameras.map((c) => c.camera_id)]),
                ),
              })
            }
          >
            Chọn {visibleCameras.length} camera đang hiện
          </button>
        )}
      </div>

      <fieldset className="traffic-filters__group traffic-filters__options">
        <legend>Ngày</legend>
        {options.dates.map((date) => (
          <label key={date}>
            <input
              type="checkbox"
              checked={filters.dates.includes(date)}
              onChange={() => update({ dates: toggle(filters.dates, date) })}
            />
            {formatDate(date)}
          </label>
        ))}
      </fieldset>

      <fieldset className="traffic-filters__group traffic-filters__options">
        <legend>Buổi</legend>
        {options.dayparts.map((daypart) => (
          <label key={daypart}>
            <input
              type="checkbox"
              checked={filters.dayparts.includes(daypart)}
              onChange={() => update({ dayparts: toggle(filters.dayparts, daypart) })}
            />
            {DAYPART_LABELS[daypart]}
          </label>
        ))}
      </fieldset>

      <fieldset className="traffic-filters__group traffic-filters__options">
        <legend>
          Thời tiết <small>(nhãn tự động)</small>
        </legend>
        {options.weathers.length === 0 && <small>Chưa có nhãn thời tiết.</small>}
        {options.weathers.map((weather) => (
          <label key={weather}>
            <input
              type="checkbox"
              checked={filters.weathers.includes(weather)}
              onChange={() => update({ weathers: toggle(filters.weathers, weather) })}
            />
            {WEATHER_LABELS[weather] ?? weather}
          </label>
        ))}
      </fieldset>

      <div className="traffic-filters__group">
        <span className="traffic-filters__label">Giờ trên đồng hồ camera</span>
        <div className="traffic-filters__clock">
          <input
            type="time"
            aria-label="Từ giờ"
            value={filters.clock_from ?? ""}
            onChange={(event) => update({ clock_from: event.target.value || undefined })}
          />
          <span aria-hidden="true">–</span>
          <input
            type="time"
            aria-label="Đến giờ"
            value={filters.clock_to ?? ""}
            onChange={(event) => update({ clock_to: event.target.value || undefined })}
          />
        </div>
      </div>
    </section>
  );
}
