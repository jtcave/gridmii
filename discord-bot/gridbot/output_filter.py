
def filter_backticks(s: str) -> str:
    # these backticks have a zero width space between them
    # so they look like triple backticks, but won't end the block
    BACKTICKS_ZWS = '`​`​`'
    return s.replace('```', BACKTICKS_ZWS)