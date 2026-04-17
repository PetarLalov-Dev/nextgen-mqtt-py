"""Topic field-number ranges extracted from main.proto. Do not edit manually."""

TOPIC_RANGES: list[tuple[int, int, str]] = [
    (6, 6, "e"),
    (7, 199, "s"),
    (7, 199, "i"),
    (200, 599, "cf"),
    (600, 999, "c"),
    (600, 999, "cd"),
    (1600, 1999, "r"),
    (1600, 1999, "cdr"),
]
