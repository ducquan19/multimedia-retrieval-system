import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { VideoLookup } from "./VideoLookup";

afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

describe("VideoLookup", () => {
  it("opens a video-only modal by ID and keeps frame navigation below the player", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(
        JSON.stringify({
          video_id: "L09_V009",
          url: "/media/videos/L09_V009.mp4",
          source: "local",
          fps: 25,
        }),
        { status: 200, headers: { "Content-Type": "application/json" } },
      ),
    );
    vi.stubGlobal("fetch", fetchMock);
    vi.spyOn(HTMLMediaElement.prototype, "pause").mockImplementation(() => undefined);
    const user = userEvent.setup();
    render(<VideoLookup />);

    const input = screen.getByRole("textbox", { name: "Video ID" });
    await user.type(input, "  L09_V009  ");
    const openButton = screen.getByRole("button", { name: "Open" });
    await user.click(openButton);

    const dialog = screen.getByRole("dialog", { name: "L09_V009" });
    expect(within(dialog).getByRole("heading", { name: "L09_V009" })).toBeInTheDocument();
    expect(dialog).not.toHaveTextContent("ASR transcript");
    expect(dialog).not.toHaveTextContent("frame 0");
    expect(screen.getByRole("button", { name: "Close video player" })).toHaveFocus();

    const fallbackText = await screen.findByText("Your browser does not support video playback.");
    const video = fallbackText.closest("video");
    if (!(video instanceof HTMLVideoElement)) throw new Error("Expected video player");
    Object.defineProperty(video, "duration", { configurable: true, value: 100 });

    expect(fetchMock).toHaveBeenCalledWith(
      "/api/videos/L09_V009/source",
      expect.objectContaining({ signal: expect.any(AbortSignal) }),
    );
    const frameInput = screen.getByRole("spinbutton", { name: "Current frame ID" });
    expect(frameInput).toHaveValue(0);

    video.currentTime = 2;
    fireEvent.timeUpdate(video);
    expect(frameInput).toHaveValue(50);
    await user.click(screen.getByRole("button", { name: "Next frame" }));
    expect(frameInput).toHaveValue(51);
    expect(video.currentTime).toBeCloseTo(51 / 25);

    await user.click(screen.getByRole("button", { name: "Close video player" }));
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    await waitFor(() => expect(openButton).toHaveFocus());
  });
});
