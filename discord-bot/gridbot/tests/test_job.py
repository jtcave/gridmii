import unittest

import time

from ..entity import Job, JobTable
from .simulacra import *

# Please do not import job_table
class PleaseDoNotImportJobUnderscoreTable(unittest.TestCase):
    def test_busted_import(self):
        self.assertNotIn("job_table", globals())

class JobTableTests(unittest.TestCase):
    TARGET = "test-node"
    def test_crud(self):
        # Yes, this is a big chunky test. If this starts failing, I'll break it down to isolate the problem.
        table = JobTable()
        NUM = 10
        jobs = []
        for i in range(NUM):
            message = mock_message()
            job = table.new_job(message, self.TARGET)
            jobs.append(job)

        self.assertGreater(len(table._table), 0)

        self.assertEqual(jobs[-1].jid, table._last_jid)

        self.assertEqual(len(table._table), NUM)

        for job in jobs:
            self.assertIsInstance(job, Job)
            self.assertEqual(job.target_node, self.TARGET)
            # jid_present
            jid = job.jid
            self.assertTrue(table.jid_present(jid))
            self.assertFalse(table.jid_present(jid + NUM))
            # by_jid
            self.assertIs(job, table.by_jid(jid))

    def test_iterator(self):
        table = JobTable()
        NUM = 5
        all_jobs = set()
        for i in range(NUM):
            message = mock_message()
            job = table.new_job(message, self.TARGET)
            all_jobs.add(job)
        self.assertTrue(table.has_jobs())

        # use the iterator to put all the jobs in a second set
        self.assertGreater(len(table._table), 0)
        seen_jobs = set()
        for job in table:
            seen_jobs.add(job)
        self.assertEqual(seen_jobs, all_jobs)


    def test_has_jobs(self):
        table = JobTable()
        self.assertFalse(table.has_jobs())
        table.new_job(mock_message(), self.TARGET)
        self.assertTrue(table.has_jobs())

class JobTests(unittest.IsolatedAsyncioTestCase):
    async def test_startup(self):
        table = JobTable()
        message = mock_message()

        job = table.new_job(message, "test-node")
        moment = time.monotonic()  # moment just after job creation
        self.assertFalse(job.started)
        self.assertLessEqual(job.start_time, moment)    # job object created before the moment
        await job.startup()
        self.assertTrue(job.started)
        self.assertGreaterEqual(job.start_time, moment) # job started after the moment


if __name__ == '__main__':
    unittest.main()
