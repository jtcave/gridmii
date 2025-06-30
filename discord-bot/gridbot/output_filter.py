import re
from itertools import zip_longest

# these backticks have a zero width space between them
# so they look like triple backticks, but won't end a code block
BACKTICKS_ZWS = '`​`​`'

def filter_backticks(s: str) -> str:
    """Ensure backticks in output don't end a code block"""
    return s.replace('```', BACKTICKS_ZWS)

def fastfetch_filter(s: str) -> str:
    """Massage fastfetch output into something Discord likes"""
    # nasty meze of regexes
    # big thanks to Techflash for making a prototype of this

    # split logo and info
    SEP = "===snip==="
    if SEP in s:
        logo, info = s.split(SEP)
    else:
        logo = s
        info = ""

    # clean logo
    # Remove all non-color codes at the start and end
    logo = re.sub(r'^\x1B\[\?\d+[hl]+', '', logo)
    logo = re.sub(r'\x1B\[19A\x1B\[9999999D.*$', '', logo, flags=re.DOTALL)
    # Remove all non-color ANSI escape sequences except color codes
    logo = re.sub(r'\x1B\[[0-9;]*[A-HJKST]', '', logo)
    logo = logo.rstrip()

    # clean info
    if info:
        # Remove all non-color codes at the start
        info = re.sub(r'^\x1B\[\?\d+[hl]+', '', info)
        # Remove trailing non-color codes and blank lines
        info = re.sub(r'\x1B\[\?\d+[hl]+$', '', info, flags=re.DOTALL)
        info = info.rstrip()
        # Remove all non-color ANSI escape sequences except color codes
        info = re.sub(r'\x1B\[[0-9;]*[A-HJKST]', '', info)

    # combine horizontally
    if not info:
        return logo
    else:
        logo_lines = logo.splitlines()
        info_lines = info.splitlines()
        # Determine the maximum width of the logo without ANSI codes
        max_logo_width = max(len(re.sub(r'\x1B\[[0-9;]*m', '', line)) for line in logo_lines)
        ansi_color_re = re.compile(r'(\x1B\[[0-9;]*m)')
        def _combine():
            last_color = ""
            first_line = False
            for logo_part, info_part in zip_longest(logo_lines, info_lines, fillvalue=""):
                # XXX: some lines to this effect were in the original code Techflash sent me
                # if not logo_part: break
                # Extract last color code in the logo line
                color_codes = ansi_color_re.findall(logo_part)
                if color_codes:
                    # XXX: Don't apply if reset
                    if color_codes[0] != "\x1b[0m" or len(color_codes) != 1:
                        last_color = ''.join(color_codes)

                # Reapply last_color to the current line
                if first_line:
                    first_line = False
                elif not re.match(r'^\s*\x1B\[[0-9;]*m', logo_part):
                    logo_part = last_color + logo_part

                # Put info line to the right of the logo line, padding as needed
                combined_line = f"{logo_part}{' ' * (max_logo_width - len(re.sub(r'\x1B\[[0-9;]*m', '', logo_part)) + 4)}{info_part}"
                # XXX: last minute cleanup
                combined_line = combined_line.replace("\x1b[?25l", "")
                combined_line = combined_line.replace("\x1b[?25h", "")
                combined_line = combined_line.replace("\x1b[?7l", "")
                combined_line = combined_line.replace("\x1b[m", "\x1b[0m")
                combined_line = combined_line.replace("\x1b[0m\x1b[0m", "\x1b[0m")
                for i in range(1, 9):
                    combined_line = combined_line.replace(f"\x1b[9{i}m", f"\x1b[1m\x1b[3{i}m")
                combined_line = re.sub(r'\x1B]8;;.*\x1B\\/', '/', combined_line)
                combined_line = combined_line.replace("\x1b]8;;\x1b\\", "")

                # XXX: if we hit triple backticks we lose our codeblock
                combined_line = combined_line.replace("```", BACKTICKS_ZWS)

                # XXX: combined_line.rstrip() doesn't work to remove whitespace :(
                while combined_line[-1] == ' ':
                    combined_line = combined_line[:-1]

                if combined_line.endswith("\x1b[0m"):
                    combined_line = combined_line[:-len("\x1b[0m")]

                yield combined_line
        # end def _combine
        return '\n'.join(_combine())