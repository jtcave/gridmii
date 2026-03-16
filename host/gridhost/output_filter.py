# these backticks have a zero width space between them
# so they look like triple backticks, but won't end a code block
BACKTICKS_ZWS = '`​`​`'

def filter_backticks(s: str) -> str:
    """Ensure backticks in output don't end a code block"""
    return s.replace('```', BACKTICKS_ZWS)

