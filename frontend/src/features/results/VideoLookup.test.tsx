import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { VideoLookup } from "./VideoLookup";

afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

describe("VideoLookup", () => {
  it("pastes adjacent sheet cells and opens the video paused at the pasted frame", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(
        JSON.stringify({
          video_id: "L21_V003",
          url: "/media/videos/L21_V003.mp4",
          source: "local",
          fps: 25,
        }),
        { status: 200, headers: { "Content-Type": "application/json" } },
      ),
    );
    vi.stubGlobal("fetch", fetchMock);
    const pauseMock = vi
      .spyOn(HTMLMediaElement.prototype, "pause")
      .mockImplementation(() => undefined);
    const user = userEvent.setup();
    render(<VideoLookup />);

    const videoIdInput = screen.getByRole("textbox", { name: "Mã video" });
    const frameIdInput = screen.getByRole("spinbutton", { name: "Frame" });
    fireEvent.paste(videoIdInput, {
      clipboardData: { getData: () => "L21_V003\t125\r\n" },
    });

    expect(videoIdInput).toHaveValue("L21_V003");
    expect(frameIdInput).toHaveValue(125);

    videoIdInput.focus();
    await user.keyboard("{Enter}");

    const fallbackText = await screen.findByText("Trình duyệt không phát được video này.");
    const video = fallbackText.closest("video");
    if (!(video instanceof HTMLVideoElement)) throw new Error("Expected video player");
    Object.defineProperty(video, "duration", { configurable: true, value: 100 });
    fireEvent.loadedMetadata(video);

    expect(screen.getByRole("dialog", { name: "L21_V003" })).toBeInTheDocument();
    expect(screen.getByRole("spinbutton", { name: "Frame hiện tại" })).toHaveValue(125);
    expect(video.currentTime).toBeCloseTo(125 / 25);
    expect(video).not.toHaveAttribute("autoplay");
    expect(pauseMock).toHaveBeenCalled();
  });

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

    const input = screen.getByRole("textbox", { name: "Mã video" });
    await user.type(input, "  L09_V009  ");
    const openButton = screen.getByRole("button", { name: "Mở video" });
    await user.click(openButton);

    const dialog = screen.getByRole("dialog", { name: "L09_V009" });
    expect(within(dialog).getByRole("heading", { name: "L09_V009" })).toBeInTheDocument();
    expect(dialog).not.toHaveTextContent("Lời thoại (ASR)");
    expect(dialog).not.toHaveTextContent("frame 0");
    expect(screen.getByRole("button", { name: "Đóng" })).toHaveFocus();

    const fallbackText = await screen.findByText("Trình duyệt không phát được video này.");
    const video = fallbackText.closest("video");
    if (!(video instanceof HTMLVideoElement)) throw new Error("Expected video player");
    Object.defineProperty(video, "duration", { configurable: true, value: 100 });

    expect(fetchMock).toHaveBeenCalledWith(
      "/api/videos/L09_V009/source",
      expect.objectContaining({ signal: expect.any(AbortSignal) }),
    );
    const frameInput = screen.getByRole("spinbutton", { name: "Frame hiện tại" });
    expect(frameInput).toHaveValue(0);

    video.currentTime = 2;
    fireEvent.timeUpdate(video);
    expect(frameInput).toHaveValue(50);
    await user.click(screen.getByRole("button", { name: "Frame sau" }));
    expect(frameInput).toHaveValue(51);
    expect(video.currentTime).toBeCloseTo(51 / 25);

    await user.click(screen.getByRole("button", { name: "Đóng" }));
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    await waitFor(() => expect(openButton).toHaveFocus());
  });
});
