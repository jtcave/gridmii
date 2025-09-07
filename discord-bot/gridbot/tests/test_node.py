import unittest
from ..entity import Node, NodeTable
from .simulacra import *

# Please do not import node_table
class PleaseDoNotImportNodeUnderscoreTable(unittest.TestCase):
    def test_busted_import(self):
        self.assertNotIn("node_table", globals())

class NodeTableTests(unittest.TestCase):
    def test_node_seen_and_gone(self):
        NAME = "hal"
        table = NodeTable()

        self.assertFalse(table.has_nodes())
        self.assertFalse(table.node_present(NAME))

        table.node_seen(NAME, None)
        self.assertTrue(table.has_nodes())
        self.assertTrue(table.node_present(NAME))

        table.node_gone(NAME)
        self.assertFalse(table.has_nodes())
        self.assertFalse(table.node_present(NAME))

    def test_iter(self):
        NAMES = ("hal", "AM", "Wintermute")
        VER = "test"
        table = NodeTable()
        nodes = set()
        for name in NAMES:
            node = table.node_seen(name, VER)
            nodes.add(node)
        self.assertEqual(len(nodes), len(NAMES))

        for node in table:
            self.assertIn(node, nodes)
            nodes.remove(node)
        self.assertEqual(len(nodes), 0)

    def test_fuzzy_lookup(self):
        NAMES = ("hal", "HAL", "Wintermute")
        VER = "test"
        table = NodeTable()
        nodes = set()
        for name in NAMES:
            node = table.node_seen(name, VER)
            nodes.add(node)
        self.assertEqual(len(nodes), len(NAMES))

        # no match
        result = table.nodes_by_name("Jane")
        self.assertFalse(result)
        # exact
        result = table.nodes_by_name("Wintermute")
        self.assertEqual(len(result), 1)
        self.assertIs(result[0], table.get_node("Wintermute"))
        # exact, with an inexact candidate
        result = table.nodes_by_name("HAL")
        self.assertEqual(len(result), 1)
        self.assertIs(result[0], table.get_node("HAL"))
        # single inexact
        result = table.nodes_by_name("WINTERMUTE")
        self.assertEqual(len(result), 1)
        self.assertIs(result[0], table.get_node("Wintermute"))
        # multiple inexact
        result = table.nodes_by_name("Hal")
        self.assertEqual(len(result), 2)
        self.assertIn(table.get_node("hal"), result)
        self.assertIn(table.get_node("HAL"), result)

    @unittest.expectedFailure
    def test_pick(self):
        self.fail("The pick logic can't be tested because it hasn't been finalized")