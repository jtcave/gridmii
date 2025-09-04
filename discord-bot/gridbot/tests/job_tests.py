import unittest

from ..entity import Job, JobTable
from .simulacra import *

class JobTableTests(unittest.IsolatedAsyncioTestCase):
    def test_new_job(self):
        table = JobTable()
        message = mock_message()
        TARGET = "test-node"
        job = table.new_job(message, TARGET)

        self.assertEqual(job.jid, table._last_jid)
        self.assertEqual(job.target_node, TARGET)



if __name__ == '__main__':
    unittest.main()
