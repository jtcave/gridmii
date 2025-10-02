# back end for the tty emulation

def make_row(columns, fill=' '):
    return [fill for c in range(columns)]

def make_plane(rows, columns, fill=' '):
    return [make_row(columns, fill) for r in range(rows)]

class TtyModel:
    def __init__(self, columns=40, lines=20, implicit_cr=False):
        self.columns = columns
        self.lines = lines
        self.char_plane = make_plane(lines, columns)
        self.cursor_line = 0
        self.cursor_column = 0
        self.implicit_cr = implicit_cr

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
        if self.implicit_cr:
            self.carriage_return()

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

    def write(self, chars: bytes):
        """Write a sequence of characters"""
        # TODO: proper UTF-8 processing
        for b in chars:
            match b:
                case 0: pass    # NUL (explicitly do nothing)
                case 1|2|3|4|5|6:
                    # SOH | STX | ETX | EOT | ENQ | ACK
                    pass
                case 7: self.bell()
                case 8: self.backspace()
                case 9: self.horizontal_tab()
                case 10: self.line_feed()
                case 11: self.vertical_tab()
                case 12: self.form_feed()
                case 13: self.carriage_return()
                case 14|15:
                    # SO | SI
                    pass

                case 16: pass   # DLE
                case 17: pass   # DC1 (XON)
                case 18: pass   # DC2
                case 19: pass   # DC3 (XOFF)
                case 20: pass   # DC4
                case 21|22|23|24|25|26:
                    # NAK | SYN | ETB | CAN | EM | SUB
                    pass
                case 27: pass   # ESC (TODO)
                case 28|29|30|31:
                    # IS4 | IS3 | IS2 | IS1
                    # FS | GS | RS | US
                    pass

                case _:
                    self.put_one_char(chr(b))