"""Topic field-number ranges extracted from main.proto. Do not edit manually."""

TOPIC_RANGES: list[tuple[int, int, str]] = [
    (5, 5, "e"),
    (6, 199, "s/i"),
    (200, 399, "cf"),
    (400, 599, "cd"),
    (600, 999, "r"),
    (1000, 1399, "c"),
]
