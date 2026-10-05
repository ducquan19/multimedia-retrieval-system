import pytest
from fastapi.testclient import TestClient


def test_media_serves_files_of_allowed_folders(client: TestClient) -> None:
    response = client.get("/media/keyframes/mock-frame.svg")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("image/svg+xml")


@pytest.mark.parametrize(
    "path",
    [
        # Files that live in data_root but are not media must never be downloadable.
        "/media/keyframes.json",
        "/media/dres_submissions.jsonl",
        "/media/video_sources.json",
        "/media/indexing/siglip.index",
        # Traversal attempts
        "/media/keyframes/../keyframes.json",
        "/media/keyframes/..%2Fdres_submissions.jsonl",
        "/media/keyframes%5C..%5Ckeyframes.json",
        # Missing file inside an allowed folder
        "/media/keyframes/missing.jpg",
    ],
)
def test_media_hides_everything_else(client: TestClient, path: str) -> None:
    assert client.get(path).status_code == 404
