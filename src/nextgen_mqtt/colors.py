"""ANSI color constants for terminal output (Gruvbox dark palette)."""

RST = "\033[0m"
BOLD = "\033[1m"

# Gruvbox dark palette (truecolor RGB)
GRAY = "\033[38;2;168;153;132m"     # fg4 (#a89984)
WHITE = "\033[38;2;235;219;178m"    # fg1 (#ebdbb2)

# Topic code → color mapping
TOPIC_COLORS = {
    "r":  "\033[38;2;184;187;38m",  # bright green (#b8bb26)
    "s":  "\033[38;2;131;165;152m", # bright aqua (#83a598)
    "i":  "\033[38;2;211;134;155m", # bright purple (#d3869b)
    "cf": "\033[38;2;250;189;47m",  # bright yellow (#fabd2f)
    "cd": "\033[38;2;254;128;25m",  # bright orange (#fe8019)
    "e":  "\033[38;2;251;73;52m",   # bright red (#fb4934)
    "c":  "\033[38;2;142;192;124m", # bright green (#8ec07c)
}


def topic_color(code: str) -> str:
    """Get the ANSI color for a topic code, falling back to GRAY."""
    return TOPIC_COLORS.get(code, GRAY)
