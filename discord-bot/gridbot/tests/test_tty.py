import unittest
from ..tty_model import TtyModel

class BasicTtyTests(unittest.TestCase):
    def test_initial_char_plane(self):
        tty = TtyModel(columns=5, lines=5)
        expected = '\n'.join([' ' * 5] * 5)
        actual = tty.render()
        self.assertEqual(expected, actual)

    def test_basic_print(self):
        SHORT_SEQ = b"abc"
        tty = TtyModel(columns=5, lines=5)
        tty.write(SHORT_SEQ)
        expected = SHORT_SEQ.decode()
        actual = tty.render().strip()
        self.assertEqual(expected, actual)
        self.assertEqual(tty.cursor_column, 3)

    def test_wrapping_print(self):
        LONG_SEQ = b"abc123"
        tty = TtyModel(columns=5, lines=5)
        tty.write(LONG_SEQ)
        expected = "abc12\n3"
        actual = tty.render().strip()
        self.assertEqual(expected, actual)

    def test_carriage_return(self):
        CR_SEQ = b"Hello world\rBye"
        tty = TtyModel(columns=12)
        tty.write(CR_SEQ)
        expected = "Byelo world"
        actual = tty.render().strip()
        self.assertEqual(expected, actual)

    def test_line_feed(self):
        LF_SEQ = b"Hello\nworld"
        tty = TtyModel(columns=11, lines=2)
        tty.write(LF_SEQ)
        expected = "Hello\n     world"
        rendered_lines = tty.render().split('\n')
        actual = '\n'.join(line.rstrip() for line in rendered_lines)
        self.assertEqual(expected, actual)

    def test_multi_line(self):
        TALL_STR = "one\ntwo\noatmeal"
        TALL_SEQ = b"one\r\ntwo\r\noatmeal"
        tty = TtyModel(columns=10, lines=3)
        tty.write(TALL_SEQ)
        expected = TALL_STR
        rendered_lines = tty.render().split('\n')
        actual = '\n'.join(line.strip() for line in rendered_lines)
        self.assertEqual(expected, actual)

    def test_scrolling(self):
        TALL_SEQ = b"one\r\ntwo\r\noatmeal"
        tty = TtyModel(columns=10, lines=2)
        tty.write(TALL_SEQ)
        expected = "two\noatmeal"
        rendered_lines = tty.render().split('\n')
        actual = '\n'.join(line.strip() for line in rendered_lines)
        self.assertEqual(expected, actual)

    @unittest.expectedFailure
    def test_unicode_print(self):
        TEST_STR = "think🤔ing"
        tty = TtyModel(columns=9)
        tty.write(TEST_STR.encode())
        actual = tty.render().strip()
        self.assertEqual(TEST_STR, actual)

class ControlC0Tests(unittest.TestCase):
    def test_backspace(self):
        BS_SEQ = b"ono\x08e"
        tty = TtyModel(columns=5)
        tty.write(BS_SEQ)
        expected = "one"
        actual = tty.render().strip()
        self.assertEqual(expected, actual)

    def test_backspace_wrapped(self):
        BS_SEQ = b"123446\x08\x0856"
        tty = TtyModel(columns=5)
        tty.write(BS_SEQ)
        expected = "12345\n6"
        actual = tty.render().strip()
        self.assertEqual(expected, actual)

    def test_tab(self):
        TAB_SEQ = b'1\t9'
        tty = TtyModel(columns=20)
        tty.write(TAB_SEQ)
        expected = "1       9"
        actual = tty.render().strip()
        self.assertEqual(expected, actual)

    def test_tab_close(self):
        TAB_SEQ = b'1234567\t9'
        tty = TtyModel(columns=20)
        tty.write(TAB_SEQ)
        expected = "1234567 9"
        actual = tty.render().strip()
        self.assertEqual(expected, actual)

class ControlC1Tests(unittest.TestCase):
    @unittest.expectedFailure
    def test_xon_xoff(self):
        raise NotImplementedError

class ControlSequenceTests(unittest.TestCase):
    pass