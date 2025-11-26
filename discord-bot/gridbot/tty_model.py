# back end for the tty emulation
import enum


def make_row(columns, fill=' '):
    return [fill for _ in range(columns)]

def make_plane(rows, columns, fill=' '):
    return [make_row(columns, fill) for _ in range(rows)]

class TtyState(enum.Enum):
    NORMAL = 0,         # normal ASCII processing
    UTF8_THREE = 1,     # three bytes remaining in the UTF-8 character
    UTF8_TWO = 2,       # two bytes remaining in the UTF-8 character
    UTF8_ONE = 3,       # one byte remaining in the UTF-8 character
    #ESC = 4,           # ESC mode
    #CSI = 5            # CSI mode

class TtyModel:
    def __init__(self, columns=40, lines=20):
        self.columns = columns
        self.lines = lines
        self.char_plane = make_plane(lines, columns)
        self.cursor_line = 0
        self.cursor_column = 0
        self.state = TtyState.NORMAL
        self.utf8_buffer: list[int] = []

    def render(self) -> str:
        """Convert the character plane to a single string"""
        return '\n'.join(''.join(c for c in line) for line in self.char_plane)

    def put_one_char(self, char: str):
        self.char_plane[self.cursor_line][self.cursor_column] = char
        self.cursor_column += 1
        if self.cursor_column >= self.columns:
            # wrap
            self.carriage_return()
            self.line_feed()

    def carriage_return(self):
        self.cursor_column = 0

    def line_feed(self):
        self.cursor_line += 1
        if self.cursor_line >= self.lines:
            self.scroll()

    def scroll(self):
        new_row = make_row(self.columns)
        del self.char_plane[0]
        self.char_plane.append(new_row)
        self.cursor_line -= 1

    def vertical_tab(self):
        self.line_feed()

    def bell(self):
        """You can override this in a subclass to actually ring a bell"""
        pass

    def backspace(self):
        if self.cursor_column > 0:
            self.cursor_column -= 1
        elif self.cursor_line > 0:
            self.cursor_column = self.columns - 1
            self.cursor_line -= 1

    def horizontal_tab(self):
        TAB_WIDTH = 8
        last_tab = self.cursor_column // TAB_WIDTH
        next_tab = last_tab + 1
        self.cursor_column = next_tab * TAB_WIDTH
        if self.cursor_column >= self.columns:
            self.cursor_column = self.columns - 1

    def form_feed(self):
        self.line_feed()

    def write_one_char(self, code: int):
        """Write one character by byte value"""
        match self.state:
            case TtyState.NORMAL:
                self.write_normal(code)
            case TtyState.UTF8_THREE | TtyState.UTF8_TWO | TtyState.UTF8_ONE:
                self.write_utf8(code)
            case _:
                raise RuntimeError("unknown tty state")

    def write_normal(self, code: int):
        if code < 32:
            # ASCII control code
            match code:
                case 0:
                    pass  # NUL (explicitly do nothing)
                case 1 | 2 | 3 | 4 | 5 | 6:
                    # SOH | STX | ETX | EOT | ENQ | ACK
                    pass
                case 7:
                    self.bell()
                case 8:
                    self.backspace()
                case 9:
                    self.horizontal_tab()
                case 10:
                    self.line_feed()
                case 11:
                    self.vertical_tab()
                case 12:
                    self.form_feed()
                case 13:
                    self.carriage_return()
                case 14 | 15:
                    # SO | SI
                    pass

                case 16:
                    pass  # DLE
                case 17:
                    pass  # DC1 (XON)
                case 18:
                    pass  # DC2
                case 19:
                    pass  # DC3 (XOFF)
                case 20:
                    pass  # DC4
                case 21 | 22 | 23 | 24 | 25 | 26:
                    # NAK | SYN | ETB | CAN | EM | SUB
                    pass
                case 27:
                    # ESC
                    pass
                case 28 | 29 | 30 | 31:
                    # IS4 | IS3 | IS2 | IS1
                    # FS | GS | RS | US
                    pass
        elif code < 0x80:
            # ASCII character
            self.put_one_char(chr(code))
        else:
            # UTF-8 character
            self.utf8_buffer.append(code)
            # determine how many more code points to expect
            if code & 0xF8 == 0xF0:
                self.state = TtyState.UTF8_THREE
            elif code & 0xF0 == 0xE0:
                self.state = TtyState.UTF8_TWO
            elif code & 0xE0 == 0xC0:
                self.state = TtyState.UTF8_ONE
            else:
                self.utf8_error()

    def utf8_error(self):
        """Called when a bad UTF-8 octet has been read.
        Flushes the buffer and writes a replacement character to indicate shenanigans"""
        self.utf8_buffer.clear()
        self.put_one_char("�")

    def write_utf8(self, code: int):
        # for simplicity, we assume this is valid utf-8 until it's time to decode
        match self.state:
            case TtyState.UTF8_THREE:
                self.utf8_buffer.append(code)
                self.state = TtyState.UTF8_TWO
            case TtyState.UTF8_TWO:
                self.utf8_buffer.append(code)
                self.state = TtyState.UTF8_ONE
            case TtyState.UTF8_ONE:
                self.utf8_buffer.append(code)
                # last character, so let's encode
                try:
                    buf = bytes(self.utf8_buffer)
                    char = buf.decode()
                    self.put_one_char(char)
                    self.utf8_buffer.clear()
                except UnicodeDecodeError:
                    self.utf8_error()
                self.state = TtyState.NORMAL

    def write(self, chars: bytes):
        """Write a sequence of characters"""
        for code in chars:
            self.write_one_char(code)