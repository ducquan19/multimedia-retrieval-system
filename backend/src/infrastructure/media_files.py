import re
from collections.abc import Iterable

from starlette.exceptions import HTTPException
from starlette.responses import Response
from starlette.staticfiles import StaticFiles
from starlette.types import Scope

_SEPARATORS = re.compile(r"[\\/]")


class MediaFiles(StaticFiles):
    """Static files of data_root restricted to an allow-list of top-level folders.

    data_root also holds indexes, metadata and the DRES submission log, which must not be
    downloadable, so only media folders (keyframes, videos, ...) are served.
    """

    def __init__(self, *, directory: str, allowed_dirs: Iterable[str]) -> None:
        # check_dir=False: the app can start (e.g. in tests) before the data folder exists.
        super().__init__(directory=directory, check_dir=False)
        self._allowed_dirs = frozenset(allowed_dirs)

    async def get_response(self, path: str, scope: Scope) -> Response:
        top_level = _SEPARATORS.split(path, maxsplit=1)[0]
        if top_level not in self._allowed_dirs:
            raise HTTPException(status_code=404)
        return await super().get_response(path, scope)
