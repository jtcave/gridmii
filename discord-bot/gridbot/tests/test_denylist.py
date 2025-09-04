import unittest

from ..cmd_denylist import permit_command

class MyTestCase(unittest.TestCase):
    def test_good_commands(self):
        goods = (
            "ls -l",
            "uptime",
            "whoami",
            "curl https://wttr.in"
        )
        self.assertTrue(all(permit_command(c) for c in goods))

    def test_no_rm_root(self):
        self.assertFalse(permit_command("rm -rf /"))
        self.assertFalse(permit_command("rm -fr /"))
        self.assertFalse(permit_command("rm -rf /*"))

    def test_almost_rm_root(self):
        self.assertTrue(permit_command("rm -rf /tmp/deletemii"))

    def test_no_permit_root(self):
        self.assertFalse(permit_command("echo --no-preserve-root"))
        self.assertFalse(permit_command("rm -rf --no-preserve-root /"))
        self.assertFalse(permit_command("rm --no-preserve-root -fr /"))

    def test_no_fork_bomb(self):
        self.assertFalse(permit_command(':(){ :|:& };:'))
        self.assertFalse(permit_command('bomb(){ bomb|bomb& };bomb'))
        self.assertFalse(permit_command('bomb () { bomb | bomb & }; bomb'))
        self.assertFalse(permit_command("echo ':(){ :|:& };:' > /tmp/pwn && sh /tmp/pwn"))

    def test_not_a_bomb(self):
        self.assertTrue(permit_command('bloop()'))
        self.assertTrue(permit_command('bloop() { }'))
        self.assertTrue(permit_command('bloop () { sleep 5 }'))
        self.assertTrue(permit_command('bloop () { sleep 5; echo bloop }; bloop'))

if __name__ == '__main__':
    unittest.main()
