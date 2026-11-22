# Flashcard Scheduler

A spaced-repetition scheduler API with three ratings:

- 0 = "分からない" (don’t remember)
- 1 = "分かる"       (remembered with effort)
- 2 = "簡単"         (knew instantly)

## Contents

1. [How to Run](#how-to-run)
2. [Functional Requirements (Rules)](#functional-requirements-rules)
3. [Assumptions](#assumptions)
4. [Data model](#data-model)
5. [Algorithm](#algorithm)
6. [Concurrency and idempotency](#concurrency-and-idempotency)
7. [Why the Rules hold](#why-the-rules-hold)
8. [Performance notes](#performance-notes)
9. [API spec](#api-spec)
10. [Tests](#tests)
11. [Trade-offs](#trade-offs)

## How to run

Requirements:

- Python 3.13.9
- Django 5.2
- Django REST Framework 3.16
- Docker for PostgreSQL
- PostgreSQL 15
- uv

### Option A: venv + `runserver`

```bash
docker compose up -d db

uv sync
# or
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# If you installed without uv, drop the `uv run` prefix for the below commands
uv run python manage.py migrate
uv run python manage.py init_data

uv run python manage.py runserver
```

### Option B: everything in Docker

```bash
docker compose up --build
```

### Seed data

`init_data` is idempotent. It loads:

- 5 cards from `assignment/management/commands/MOCK_DATA.json`
- Superuser `testuser` and users `testuser1` to `testuser5`. Passwords are set to
    `testpassword`.

### Environment variables

- `FLASHCARDS_DB_NAME`. Default: `flashcards`
- `FLASHCARDS_DB_USER`. Default: `flashcards`
- `FLASHCARDS_DB_PASSWORD`. Default: `flashcards`
- `FLASHCARDS_DB_HOST`. Default: `localhost` (`db` inside Compose)
- `FLASHCARDS_DB_PORT`. Default: `5432`

The defaults are for local development only.

### Linting

```bash
uv run ruff format --check .
uv run ruff check .
```

### Manual check if the API is working

```bash
curl -s -X POST localhost:8000/reviews \
  -H 'Content-Type: application/json' \
  -d '{"user_id": 1, "card_id": 1, "rating": 2, "idempotency_key": "demo-1"}'

curl -s 'localhost:8000/users/1/due-cards?until=2030-01-01T00:00:00%2B09:00'
```

## Functional Requirements (Rules)

1. A rating of `0` always returns an interval of 60 seconds, so that the card is
due again within a minute.

2. Spacing on ratings: 2 > 1 > 0. On the first-ever review of a card, a 2 gives
the longest interval, a 1 a modest one, and a 0 will be the shortest.

3. Monotonic intervals. Subsequent correct answer/review must not shorten the
previously scheduled interval for the same (user, card) pair.

4. Idempotency. Identical requests (same `idempotency_key`) must be processed only once.

## Assumptions

- **Idempotency key.** The client generates it and re-sends the same key on retry.
- **Users and cards.** They are seeded with `init_data` as creating cards and authentication
    are not in scope of this API design.
- **Intervals.** A rating 1 gets 1 day, and a rating 2 gets 4 days to satisfy Rule 2
    in functional requirements.
- **First review.** The first-review intervals apply until the first correct answer
    (the floor is `None`). So a `0` then `2` gives 60 seconds, then 4 days.
- **Subsequent 0 after a correct answer will not reset the interval.** A lapse does not
    shrink the correct intervals, hence we need the floor.

## Data Model

Defined in `assignment/models.py`.

**`User`**: the `AbstractUser` from the template.

**`Card`**: `front` and `back`. `front` is unique, so seeding can use it as a natural key.

**`CardState`**: the current schedule of a card, one row per (user, card) pair.

| Column | Purpose |
| --- | --- |
| `user_id`, `card_id` | Unique constraint (`card_state_user_card_uniq`) |
| `interval_seconds` | Last scheduled interval |
| `last_correct_interval` | The floor for a monotonic interval |
| `reps` | Number of reviews |
| `last_rating` | Last rating given |
| `next_review` | When the card is due. Indexed with `user_id` (`card_state_due`) |
| `updated_at` | Set on every save |

**`Review`**: an append-only log. One row per accepted request.

| Column | Purpose |
| --- | --- |
| `idempotency_key` | Unique. |
| `user_id`, `card_id`, `rating` | The request. `rating` has a check constraint for `0/1/2` |
| `reviewed_at` | Server time of the review |
| `interval_seconds`, `next_review` | The result. It is stored so a replay returns the same body |

Foreign keys: `CardState` uses `CASCADE` because it is derived data.
`Review` uses `PROTECT` because it is history and should not disappear silently.

## Algorithm

### Ratings, interval and floor

Each (user, card) pair stores two numbers in `CardState`:

- **interval**: how long until the card is due again.
- **floor**: the last **correct** interval, stored as `last_correct_interval`. This value
    is empty until the first correct answer/review.

The rating decides the next interval:

- **0**: an immediate retry within a minute
- **1 or 2, first time**: a fixed starting interval (1 day or 4 days)
- **1 or 2, subsequent reviews**: the floor multiplied by a growth factor

#### Constants

```Python
# All intervals are whole seconds
RATING_0_INTERVAL_SECONDS = 60
SECONDS_IN_ONE_DAY = 86400
BASE_INTERVAL_WITH_RATING_1 = 1 * SECONDS_IN_ONE_DAY
BASE_INTERVAL_WITH_RATING_2 = 4 * SECONDS_IN_ONE_DAY
INTERVAL_GROWTH = {1: 1.5, 2: 2.5}
CAP = 365 * SECONDS_IN_ONE_DAY
```

#### Pseudocode

```Text
if rating not in valid rating (0, 1, 2):
    raise a ValueError

if rating is 0:
    interval = 60 seconds
elif floor does not exist yet:
    interval = 4 days if rating is 2, else 1 day
else:
    grown = ceil(floor * growth[rating])
    interval = max(min(grown, CAP), floor)     # to make sure monotonic

new_floor = interval if rating > 0 else floor   # a 0 keeps the floor
next_review = now + interval
```

#### Example

One card reviewed with ratings `2, 1, 0, 1, 2`:

| Rating | Floor before | Interval | Floor after |
| --- | --- | --- | --- |
| 2 | none | 4 d | 4 d |
| 1 | 4 d | 6 d (4 × 1.5) | 6 d |
| 0 | 6 d | 60 s | 6 d |
| 1 | 6 d | 9 d (6 × 1.5) | 9 d |
| 2 | 9 d | 22.5 d (9 × 2.5) | 22.5 d |

A wrong answer brings the card back after a minute but does not erase progress.

### Recording a review (`POST /reviews`)

`record_review` in `assignment/services.py` handles each request in three steps:

1. **Idempotency key check.** Look up the key:
    - Not found: continue to step 2.
    - Found, with the same `user_id`, `card_id` and `rating`. Return a stored
        review with `200`, nothing is written.
    - Found, with a different body. It is possibly a client side bug. Return `409`.
2. **Locked write.** Inside one `transaction.atomic()` block. It:
    - locks the `CardState` row for (user, card) with `SELECT ... FOR UPDATE`
    - compute the new interval and floor with `schedule()`
    - save the `CardState`
    - insert the `Review`
3. **Race fallback.** Two requests can both pass step 1 before either commits.
    The DB's unique constraints reject the second one with `IntegrityError`.
    `record_review` then repeats step 1 (a duplicate key returns the committed review)
    or retries step 2 once (a first-review race).

### The `schedule()` function

The functional requirements live in this function in `assignment/scheduler.py`:

```Text
schedule(floor, rating, now) -> (interval, new_floor, next_review)
```

The function has no database or clock access. The API doesn't need this separation.
It exists because a pure function can be tested over every rating sequence. In
the service layer, `schedule()` is called once per review, inside the locked transaction.

### Listing due cards (`GET /users/{id}/due-cards`)

The endpoint returns the user's `CardState` rows where
`next_review <= until`:

- **Order.** Sorted by `next_review`, then `card_id`, so the most
  overdue card comes first.
- **Size.** Capped by `limit`: default 50, maximum 200.
- **`until`.** Optional; it defaults to the current time. A value with no
  offset is read as JST.
- **Card text.** `select_related("card")` joins in `front` and `back` in
  the same query.
- **Speed.** The composite index on (`user_id`, `next_review`) means
  Postgres reads only that user's due rows, already in order.

Cards the user has never reviewed have no `CardState` row yet, so they
aren't listed. Creating cards and assigning them to users is out of
scope.

## Concurrency and Idempotency

The write path is described in
[Recording a review](#recording-a-review-post-reviews). This section
covers why the lock matters and how the tests prove it.

What the row lock protects against: two different reviews of the same
card at once would otherwise both read the same floor and one update would
be lost. `test_concurrent_different_keys_serialised` runs 10 concurrent
reviews and checks the result matches 10 sequential reviews. With
`select_for_update()` removed, this test fails with a lost update
(`129600 != 194400`).

`test_concurrent_same_key_processed_once` sends the same key from 10
threads and checks that exactly one `Review` row is created.

The database is the final safeguard. Even if application code were wrong,
the unique key, the unique (user, card) pair and the rating check
constraint would reject bad writes.

## Why the rules hold

**Rule 1: Immediate retry.** A rating of `0` always returns an interval of
60 s, so the card is due again within one minute. This applies to new and
existing cards.

**Rule 2: Spacing on the first review.** With no floor, the intervals are:

- rating 0 → 60 s
- rating 1 → 1 day
- rating 2 → 4 days

So `0 < 1 < 2`: a `2` gives the longest first interval and a `1` sits
between the retry and the `2`.

**Rule 3: Monotonic intervals.** Let `F` be the floor.

- On a correct answer, `interval = max(min(ceil(F × g), CAP), F)`. The
  outer `max(…, F)` means the result is never below `F`. Because
  `g ≥ 1.5`, it normally grows; at the cap it stays at `CAP`.
- The new floor is that interval, so the floor never decreases.
- A `0` returns 60 s but leaves the floor unchanged, so it cannot pull the
  next correct interval down.

So the sequence of correct intervals for one user and card never
decreases. This also holds under the stricter reading "never shorter than
the previously scheduled interval": the only shorter interval is the 60 s
retry, and every correct interval is at least 1 day.

**Rule 4: Idempotency.** See
[Recording a review](#recording-a-review-post-reviews) for the flow and
[Concurrency and idempotency](#concurrency-and-idempotency) for the tests.

Test evidence, in `assignment/tests/test_scheduler.py`:

| Rule | Test |
| --- | --- |
| 1 | `test_wrong_answer_returns_within_one_minute` |
| 2 | `test_first_review_ordering` |
| 3 | `test_monotonic_interval_pattern` (all 3⁶ = 729 sequences) |
| 3 | `test_first_review_wrong_then_correct_gets_first_interval` |
| 3 | `test_interval_is_capped` |
| Input | `test_invalid_rating_raises_exception` |

Six reviews is the shortest length that reaches the 365-day cap
(`4 d × 2.5⁵ ≈ 390 d`), so the exhaustive test covers growth, lapses and
the cap together.

## Performance notes

**Indexes**

| Query | Index |
| --- | --- |
| Due cards: `user_id = ? AND next_review <= ? ORDER BY next_review` | Composite `card_state_due (user_id, next_review)`: a range scan already in order |
| Lock the state row: `user_id = ? AND card_id = ?` | Unique `(user_id, card_id)` |
| Replay lookup by key | Unique `idempotency_key` |

**Queries per request**

| Request | Queries |
| --- | --- |
| `POST /reviews`, new | About 6: user exists, card exists, key lookup, locked select, state upsert, review insert |
| `POST /reviews`, replay | 3: user exists, card exists, key lookup |
| `GET /due-cards` | 2: user exists, one `SELECT … JOIN card` (`select_related`, no N+1) |

**Lock scope.** The lock covers one (user, card) row, and only for the
length of a short transaction with no network calls. Reviews of different
cards, or by different users, never wait on each other.

**Bounded responses.** `limit` defaults to 50 and is capped at 200, so a
user with a large backlog can't produce an unbounded response.

## API spec

No authentication. All request and response bodies are JSON. All
timestamps are ISO-8601. They are stored in UTC and returned with the JST
offset (`+09:00`).

### `POST /reviews`

Records one review and returns the next due time.

**Request body**

| Field | Type | Rules |
| --- | --- | --- |
| `user_id` | integer | ≥ 1, user must exist |
| `card_id` | integer | ≥ 1, card must exist |
| `rating` | integer | `0`, `1` or `2` |
| `idempotency_key` | string | Required, at most 64 chars, client-generated (e.g. a UUID) |

```json
{
  "user_id": 1,
  "card_id": 1,
  "rating": 2,
  "idempotency_key": "6f1c2a9e-0d1b-4c55-9a43-2b7f0e5d8c11"
}
```

**Response body**

```json
{
  "review_id": 1,
  "user_id": 1,
  "card_id": 1,
  "rating": 2,
  "interval_seconds": 345600,
  "next_review": "2026-11-26T10:00:00+09:00"
}
```

**Status codes**

| Code | When |
| --- | --- |
| `201 Created` | New review recorded |
| `200 OK` | Replay: same key and same body as an earlier request. The body is identical to the first response, and nothing is written. |
| `400 Bad Request` | Validation failed, e.g. missing field or rating not in `0/1/2` |
| `404 Not Found` | `user_id` or `card_id` does not exist |
| `409 Conflict` | Key was already used with a different `user_id`, `card_id` or `rating` |

Error examples:

```json
{"rating": ["\"3\" is not a valid choice."]}
{"detail": "User not found."}
{"detail": "idempotency_key was used for another request."}
```

### `GET /users/{id}/due-cards`

Lists the user's cards whose `next_review <= until`, earliest first.

**Query parameters**

| Name | Type | Default | Rules |
| --- | --- | --- | --- |
| `until` | ISO-8601 datetime | now | A value with no offset is read as JST. Encode `+` as `%2B` in URLs. |
| `limit` | integer | 50 | 1 to 200 |

```
GET /users/1/due-cards?until=2030-01-01T00:00:00%2B09:00&limit=50
```

**Response body**

```json
{
  "user_id": 1,
  "until": "2030-01-01T00:00:00+09:00",
  "cards": [
    {
      "card_id": 1,
      "front": "木",
      "back": "Tree",
      "interval_seconds": 345600,
      "next_review": "2026-11-26T10:00:00+09:00"
    }
  ]
}
```

Cards are ordered by `next_review`, then `card_id`. Cards the user has
never reviewed have no schedule yet, so they are not listed.

**Status codes**

| Code | When |
| --- | --- |
| `200 OK` | Success; `cards` may be empty |
| `400 Bad Request` | `until` is not a valid datetime, or `limit` is out of range |
| `404 Not Found` | User does not exist |

## Tests

The tests need the database running (`docker compose up -d db`).

```bash
uv run pytest -q
```

750 tests in total: 736 scheduler cases and 14 API cases.

- `assignment/tests/test_scheduler.py`: pure function tests for Rules 1–3,
  the cap and input validation. This includes the exhaustive 729-sequence
  monotonicity test.
- `assignment/tests/test_api.py`: endpoint tests through DRF's
  `APIClient`:
  - 201 then 200 with an identical body;
  - 409;
  - 400 and 404 cases;
  - JST offset;
  - the `until` filter;
  - per-user isolation.

  It also has the two threaded concurrency tests described above. These
  use `django_db(transaction=True)` so each thread commits for real.

## Trade-offs

- **Floor instead of reset after a lapse.** SM-2 style schedulers shrink
  the interval after a lapse, and it breaks the strict requirement of Rule 3,
  so this design keeps the floor. The cost is that a forgotten card
  returns to a long interval once answered correctly. The 60 second retry
  makes sure it is seen again first.
- **Fixed growth factors, not a per-card ease factor.** A per-card ease could be
    added to `CardState` without changing the API if needed.
- **365-day cap.** Keeps intervals meaningful and bounded in a
  `BigIntegerField`.
- **Pessimistic row lock, not optimistic versioning.** Conflicts on the
  same (user, card) are rare, but when they happen the lock gives the
  correct answer without a retry loop. Its scope is a single row.
- **Lookup before insert, plus the unique constraint.** The common replay
  path is a cheap read. The constraint catches the rare race.
- **Explicit existence checks for user and card.** These cost 2 extra
  queries but give clear `404`s instead of mapping foreign-key errors.
- **`limit` without cursor pagination.** Enough for a review queue. A
  `next_review` cursor would be the next step.
- **Redundant index.** Django adds an index on `CardState.user_id`. This
  is redundant with the composite indexes, but it was kept for
  simplicity.
