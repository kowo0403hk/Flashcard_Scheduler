import math
from datetime import datetime, timedelta


RATING_0_INTERVAL_SECONDS = 60
SECONDS_IN_ONE_DAY = 86400
BASE_INTERVAL_WITH_RATING_1 = 1 * SECONDS_IN_ONE_DAY
BASE_INTERVAL_WITH_RATING_2 = 4 * SECONDS_IN_ONE_DAY
INTERVAL_GROWTH = {1: 1.5, 2: 2.5}
CAP = 365 * SECONDS_IN_ONE_DAY


def schedule(
    floor: int | None, rating: int, now: datetime
) -> tuple[int, int | None, datetime]:
    if rating not in (0, 1, 2):
        raise ValueError(f"rating must be 0, 1 or 2, got {rating!r}")
    if rating == 0:
        interval = RATING_0_INTERVAL_SECONDS
    elif floor is None:
        interval = (
            BASE_INTERVAL_WITH_RATING_2
            if rating == 2
            else BASE_INTERVAL_WITH_RATING_1
        )
    else:
        interval = max(
            min(math.ceil(floor * INTERVAL_GROWTH[rating]), CAP), floor
        )

    # a 0 keeps the floor, so the next correct interval can't shrink
    new_floor = interval if rating > 0 else floor

    return interval, new_floor, now + timedelta(seconds=interval)
