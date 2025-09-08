import unittest
import unittest.mock as mock

from ..config import Config
from ..grid_cmd import UserCommandCog, GridMiiCogBase
from ..entity import NodeTable, JobTable
from .simulacra import *



class UserCommandTest(unittest.IsolatedAsyncioTestCase):

    @staticmethod
    def cog():
        return UserCommandCog(mock_bot())

    def setUp(self):
        Config.load_config("data/config.toml")

    def test_smoke_test(self):
        cog = self.cog()
        self.assertIsInstance(cog, GridMiiCogBase)

    async def test_yougood(self):
        cog = self.cog()
        ctx = mock_context()
        await cog.ping(cog, ctx)
        ctx.reply.assert_called_with(":+1:")

    @mock.patch("gridbot.grid_cmd.node_table", NodeTable())
    async def test_nodes_empty(self):
        cog = self.cog()
        ctx = mock_context()
        await cog.nodes(cog, ctx)
        ctx.reply.assert_called_with("No nodes are online")

    async def test_nodes_nonempty(self):
        NAMES = ("node1", "node2", "node3")
        VERSION = "unit-test"
        EXPECTED = '\n'.join(f"* {n} (version {VERSION})" for n in NAMES)
        table = NodeTable()
        for name in NAMES:
            table.node_seen(name, VERSION)
        cog = self.cog()
        ctx = mock_context()
        with mock.patch("gridbot.grid_cmd.node_table", table):
            await cog.nodes(cog, ctx)
            ctx.reply.assert_called_with(EXPECTED)

    @unittest.expectedFailure
    async def test_locus_read_unset(self):
        self.assertTrue(None, "need to rewrite UserPrefs to support easier injection")

    @unittest.expectedFailure
    async def test_locus_read_set(self):
        self.assertTrue(None, "need to rewrite UserPrefs to support easier injection")

    @unittest.expectedFailure
    async def test_locus_set_success(self):
        self.assertTrue(None, "need to rewrite UserPrefs to support easier injection")

    @unittest.expectedFailure
    async def test_locus_set_failure(self):
        self.assertTrue(None, "need to rewrite UserPrefs to support easier injection")

    @unittest.expectedFailure
    async def test_locus_set_ambiguous(self):
        self.assertTrue(None, "need to rewrite UserPrefs to support easier injection")

    async def test_jobs_empty(self):
        cog = self.cog()
        ctx = mock_context()
        with mock.patch("gridbot.grid_cmd.job_table", JobTable()):
            await cog.jobs(cog, ctx)
            ctx.reply.assert_called_with("No jobs running")

    @unittest.expectedFailure
    async def test_jobs_nonempty(self):
        self.assertTrue(None, "TODO")

    @unittest.expectedFailure
    async def test_rules(self):
        self.assertTrue(None, "TODO")




if __name__ == '__main__':
    unittest.main()
