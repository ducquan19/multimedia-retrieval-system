import type { TRAKESearchResult } from "../../api/types";

export function validateTrakeResults(
  results: TRAKESearchResult[],
  expectedEventCount: number,
): string[] {
  const errors: string[] = [];
  const resultIds = new Set<string>();

  for (const result of results) {
    if (resultIds.has(result.result_id)) {
      errors.push(`Duplicate result_id: ${result.result_id}.`);
    }
    resultIds.add(result.result_id);

    if (result.events.length !== expectedEventCount) {
      errors.push(
        `${result.result_id} has ${result.events.length} events; expected ${expectedEventCount}.`,
      );
      continue;
    }

    result.events.forEach((event, index) => {
      const expectedIndex = index + 1;
      if (event.event_index !== expectedIndex) {
        errors.push(
          `${result.result_id} has Event ${event.event_index} at position ${expectedIndex}; event_index must be continuous from 1.`,
        );
      }
      const eventVideoId =
        "video_id" in event && typeof event.video_id === "string"
          ? event.video_id
          : undefined;
      if (eventVideoId !== undefined && eventVideoId !== result.video_id) {
        errors.push(
          `${result.result_id} Event ${event.event_index} belongs to ${eventVideoId}, not ${result.video_id}.`,
        );
      }
    });
  }

  return errors;
}
