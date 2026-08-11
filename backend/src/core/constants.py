from typing import Final, Literal, get_args

TopK = Literal[1, 5, 20, 50, 100]
TOP_K_OPTIONS: Final[tuple[int, ...]] = get_args(TopK)
