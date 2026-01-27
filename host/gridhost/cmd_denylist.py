import re

# This denylist is by no means a perfect defense against malicious commands.
# It is meant to stop low effort system-trashing commands.

DENY_PATTERNS = (
    r'rm -[rf][rf] /\*?$',
    r'--no-preserve-root',
    # matches the famous one-liner fork bomb
    r'(.+?)\s*\(\)\s*\{\s+\1\s*|\s*\1\s*\&\s+\}\s*;\s*\1',
)

DENY_REGEX = tuple(re.compile(p) for p in DENY_PATTERNS)

def permit_command(command: str, deny_patterns=DENY_REGEX) -> bool:
    """Returns False if the command is forbidden by the deny_patterns iterable of regexes"""
    for pat in deny_patterns:
        if re.search(pat, command) is not None:
            return False
    return True