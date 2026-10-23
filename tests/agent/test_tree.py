# SPDX-License-Identifier: GPL-3.0-or-later
import shutil
import tempfile
import unittest
from pathlib import Path

from whittle import formats, tree
from whittle.tree import SessionPlan, Tree, TreeError, session_plan


def build(*edges, **finished) -> Tree:
    """A tree from (node, parent) pairs; keyword arguments finish nodes with
    (session id, message uuid)."""
    t = Tree.new()
    for node_id, parent in edges:
        t.add(node_id, parent, prompt=f"prompt {node_id}\nmore")
    for node_id, (session, uuid) in finished.items():
        t.finish(node_id, status="complete", agent_session_id=session, agent_message_uuid=uuid)
    return t


class TreeOpsTest(unittest.TestCase):
    def test_new(self):
        t = Tree.new()
        self.assertEqual((t.root, t.current), ("n0000", "n0000"))
        root = t.node("n0000")
        self.assertEqual((root.status, root.label, root.parent), ("complete", "Start", None))

    def test_add_walk_and_depth(self):
        t = build(("n0001", "n0000"), ("n0002", "n0001"), ("n0003", "n0001"), ("n0004", "n0000"),
                  ("n0005", "n0002"))
        self.assertEqual([(n.id, d) for n, d in t.walk()],
                         [("n0000", 0), ("n0001", 1), ("n0002", 2), ("n0005", 3), ("n0003", 2),
                          ("n0004", 1)])
        self.assertEqual(t.node("n0001").children, ["n0002", "n0003"])
        self.assertEqual(t.node("n0003").label, "prompt n0003")
        self.assertEqual(t.node("n0003").status, "running")

    def test_add_is_idempotent_and_checked(self):
        t = build(("n0001", "n0000"))
        again = t.add("n0001", "n0000", prompt="other")
        self.assertIs(again, t.node("n0001"))
        self.assertEqual(t.node("n0000").children, ["n0001"])
        with self.assertRaises(TreeError):
            t.add("n0001", "n0001", prompt="x")
        with self.assertRaises(TreeError):
            t.add("n0009", "n0042", prompt="x")

    def test_labels(self):
        t = Tree.new()
        self.assertEqual(t.add("n0001", "n0000", prompt="").label, "(sketch only)")
        long = t.add("n0002", "n0000", prompt="\n  " + "x" * 100).label
        self.assertEqual(len(long), tree.LABEL_CHARS)
        self.assertTrue(long.endswith("…"))

    def test_path_leaf_uids_and_sessions(self):
        t = build(("n0001", "n0000"), ("n0002", "n0001"), ("n0003", "n0001"),
                  n0001=("S", "u1"), n0002=("S", "u2"), n0003=("T", "u3"))
        self.assertEqual(t.path("n0002"), ["n0000", "n0001", "n0002"])
        self.assertTrue(t.is_leaf("n0002"))
        self.assertFalse(t.is_leaf("n0001"))
        t.finish("n0001", created_uids=["a", "b"])
        t.finish("n0003", created_uids=["c"])
        self.assertEqual(t.all_created_uids(), {"a", "b", "c"})
        self.assertEqual(t.latest_in_session("S"), "n0002")
        self.assertEqual(t.latest_in_session("T"), "n0003")
        self.assertIsNone(t.latest_in_session("U"))

    def test_folded_failures_are_hidden(self):
        """A failed turn that changed nothing folds into its parent: the tree
        shows its siblings and the parent stays a leaf, but its session still
        counts, so the parent forks before the failure."""
        t = build(("n0001", "n0000"), ("n0002", "n0001"), ("n0003", "n0001"),
                  n0001=("S", "u1"), n0003=("S", "u3"))
        t.finish("n0002", status="failed", folded=True, agent_session_id="S", agent_message_uuid="u2")
        self.assertEqual([n.id for n, _d in t.walk()], ["n0000", "n0001", "n0003"])
        self.assertEqual([n.id for n, _d in t.walk(folded=True)], ["n0000", "n0001", "n0002", "n0003"])
        self.assertEqual(t.visible_children("n0001"), ["n0003"])
        t2 = build(("n0001", "n0000"), ("n0002", "n0001"), n0001=("S", "u1"))
        t2.finish("n0002", status="failed", folded=True, agent_session_id="S", agent_message_uuid="u2")
        self.assertTrue(t2.is_leaf("n0001"))
        self.assertEqual(session_plan(t2, "n0001", None),
                         SessionPlan(restart=True, resume="S", fork=True, resume_at="u1",
                                     notes=session_plan(t2, "n0001", None).notes))

    def test_siblings_and_newest_leaf(self):
        """What a branch switcher steps through, and where each branch ends."""
        t = build(("n0001", "n0000"), ("n0002", "n0001"), ("n0003", "n0001"), ("n0004", "n0002"),
                  ("n0005", "n0002"), ("n0006", "n0003"), ("n0007", "n0001"))
        t.finish("n0007", status="failed", folded=True)
        self.assertEqual(t.siblings("n0002"), ["n0002", "n0003"], "folded failures are not branches")
        self.assertEqual(t.siblings("n0000"), ["n0000"])
        self.assertEqual(t.siblings("n0001"), ["n0001"])
        self.assertEqual(t.leaves_under("n0002"), ["n0005", "n0004"])
        self.assertEqual(t.newest_leaf("n0002"), "n0005")
        self.assertEqual(t.newest_leaf("n0001"), "n0006")
        self.assertEqual(t.newest_leaf("n0006"), "n0006", "a leaf ends its own branch")

    def test_finish_checks(self):
        t = build(("n0001", "n0000"))
        with self.assertRaises(TreeError):
            t.finish("n0001", status="weird")
        with self.assertRaises(TreeError):
            t.finish("n0001", colour="red")
        with self.assertRaises(TreeError):
            t.finish("n0099", status="complete")

    def test_discard(self):
        t = build(("n0001", "n0000"), ("n0002", "n0001"))
        with self.assertRaises(TreeError):
            t.discard("n0001")
        t.discard("n0002")
        self.assertNotIn("n0002", t.nodes)
        self.assertEqual(t.node("n0001").children, [])
        t.discard("n0002")

    def test_recover(self):
        t = build(("n0001", "n0000"), ("n0002", "n0001"), n0001=("S", "u1"))
        self.assertEqual(t.recover(), ["n0002"])
        self.assertEqual(t.node("n0002").status, "failed")
        self.assertEqual(t.recover(), [])


class SessionFileTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="whittle-tree-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.path = self.tmp / "session.json"

    def test_round_trip(self):
        t = build(("n0001", "n0000"), ("n0002", "n0001"), n0001=("S", "u1"), n0002=("S", "u2"))
        t.finish("n0001", cost_usd=0.01, num_turns=3, duration_ms=1200, created_uids=["a"],
                 snapshot=True)
        t.current = "n0001"
        tree.write_session(self.path, t)
        again, recovered = tree.read_session(self.path)
        self.assertEqual(recovered, [])
        self.assertEqual(again, t)
        self.assertEqual(formats.read_json(self.path)["format"], tree.SESSION_FORMAT)

    def test_running_reloads_as_failed(self):
        t = build(("n0001", "n0000"))
        tree.write_session(self.path, t)
        again, recovered = tree.read_session(self.path)
        self.assertEqual(recovered, ["n0001"])
        self.assertEqual(again.node("n0001").status, "failed")

    def assert_invalid(self, obj, *parts):
        with self.assertRaises(formats.FormatError) as cm:
            tree.validate_session(obj, "x/session.json")
        message = str(cm.exception)
        self.assertIn("x/session.json", message)
        for part in parts:
            self.assertIn(part, message)

    def test_validation(self):
        good = tree.to_json(build(("n0001", "n0000"), ("n0002", "n0001")))
        tree.validate_session(good)

        def broken(change):
            obj = tree.to_json(tree.from_json(good))
            change(obj)
            return obj

        self.assert_invalid(broken(lambda o: o.pop("current")), "'current'")
        self.assert_invalid(broken(lambda o: o["nodes"]["n0001"].pop("status")), "n0001", "'status'")
        self.assert_invalid(broken(lambda o: o["nodes"]["n0001"].update(num_turns="3")), "'num_turns'")
        self.assert_invalid(broken(lambda o: o["nodes"]["n0001"].update(status="paused")), "paused")
        self.assert_invalid(broken(lambda o: o["nodes"]["n0002"].update(parent="n0000")), "n0001", "child")
        self.assert_invalid(broken(lambda o: o.update(current="n0042")), "'current'", "n0042")
        self.assert_invalid(broken(lambda o: o.update(format="whittle.request")), "format")
        self.assert_invalid(broken(lambda o: o["nodes"]["n0001"].update(id="n0007")), "id")

        def planted(o):
            # A node id names a folder: one like this would point outside the chat.
            bad = "../../../x"
            o["nodes"][bad] = dict(o["nodes"].pop("n0002"), id=bad)
            o["nodes"]["n0001"]["children"] = [bad]
            o["current"] = bad
        self.assert_invalid(broken(planted), "not a node id")

    def test_continued_session_round_trips_and_may_be_missing(self):
        t = build(("n0001", "n0000"), n0001=("S", "u1"))
        t.node("n0001").continued_session = "S"
        tree.write_session(self.path, t)
        again, _ = tree.read_session(self.path)
        self.assertEqual(again.node("n0001").continued_session, "S")
        older = tree.to_json(t)
        for node in older["nodes"].values():
            del node["continued_session"]
        self.assertIsNone(tree.from_json(older).node("n0001").continued_session)
        older["nodes"]["n0001"]["continued_session"] = 3
        self.assert_invalid(older, "'continued_session'")

    def test_folded_round_trips_and_is_checked(self):
        t = build(("n0001", "n0000"), n0001=("S", "u1"))
        t.finish("n0001", status="failed", folded=True)
        tree.write_session(self.path, t)
        again, _ = tree.read_session(self.path)
        self.assertTrue(again.node("n0001").folded)
        older = tree.to_json(build(("n0001", "n0000"), n0001=("S", "u1")))
        for node in older["nodes"].values():
            del node["folded"]
        self.assertFalse(tree.from_json(older).node("n0001").folded)

        def broken(change):
            obj = tree.to_json(t)
            change(obj)
            return obj

        self.assert_invalid(broken(lambda o: o["nodes"]["n0001"].update(status="complete")), "folded")
        self.assert_invalid(broken(lambda o: o.update(current="n0001")), "current", "folded")

    def test_missing_and_bad_json(self):
        with self.assertRaises(formats.FormatError):
            tree.read_session(self.path)
        self.path.write_text("{oops")
        with self.assertRaises(formats.FormatError):
            tree.read_session(self.path)


class SessionPlanTest(unittest.TestCase):
    def test_live_client_ends_at_the_node(self):
        t = build(("n0001", "n0000"), n0001=("S", "u1"))
        self.assertEqual(session_plan(t, "n0001", "n0001"), SessionPlan(restart=False))

    def test_root_without_a_live_client(self):
        t = build(("n0001", "n0000"), n0001=("S", "u1"))
        self.assertEqual(session_plan(t, "n0000", None), SessionPlan(restart=True))
        self.assertEqual(session_plan(t, "n0000", "n0001"), SessionPlan(restart=True))

    def test_latest_leaf_resumes_plainly(self):
        t = build(("n0001", "n0000"), ("n0002", "n0001"), n0001=("S", "u1"), n0002=("S", "u2"))
        self.assertEqual(session_plan(t, "n0002", None), SessionPlan(restart=True, resume="S"))

    def test_node_with_a_later_turn_in_its_session_forks_at_its_message(self):
        t = build(("n0001", "n0000"), ("n0002", "n0001"), n0001=("S", "u1"), n0002=("S", "u2"))
        plan = session_plan(t, "n0001", "n0002")
        self.assertEqual((plan.restart, plan.resume, plan.fork, plan.resume_at), (True, "S", True, "u1"))
        self.assertEqual(len(plan.notes), 1)
        self.assertIn("continuing from history node n0001 (prompt n0001)", plan.notes[0])

    def test_node_whose_children_forked_resumes_plainly(self):
        t = build(("n0001", "n0000"), ("n0002", "n0001"), n0001=("S", "u1"), n0002=("T", "u2"))
        self.assertEqual(session_plan(t, "n0001", "n0002"), SessionPlan(restart=True, resume="S"))

    def test_failed_node_uses_its_ancestors_session(self):
        t = build(("n0001", "n0000"), ("n0002", "n0001"), n0001=("S", "u1"))
        t.finish("n0002", status="failed")
        plan = session_plan(t, "n0002", None)
        self.assertEqual((plan.resume, plan.fork, plan.resume_at), ("S", True, "u1"))
        self.assertIn("turns after history node n0001", plan.notes[0])
        self.assertIn("reflects n0002", plan.notes[0])

    def test_unfinished_turn_in_the_session_forks_at_the_node(self):
        # n0002 carried on S but Blender went away before it finished, so it
        # never got S as its own session id; S has still moved past n0001.
        t = build(("n0001", "n0000"), ("n0002", "n0001"), n0001=("S", "u1"))
        t.node("n0002").continued_session = "S"
        t.recover()
        t.current = "n0001"
        self.assertEqual(t.latest_in_session("S"), "n0002")
        plan = session_plan(t, "n0001", None)
        self.assertEqual((plan.restart, plan.resume, plan.fork, plan.resume_at), (True, "S", True, "u1"))
        self.assertEqual(len(plan.notes), 1)
        self.assertIn("other branches", plan.notes[0])

    def test_unfinished_turn_in_another_session_leaves_a_plain_resume(self):
        t = build(("n0001", "n0000"), ("n0002", "n0001"), n0001=("S", "u1"))
        t.node("n0002").continued_session = None
        t.recover()
        self.assertEqual(session_plan(t, "n0001", None), SessionPlan(restart=True, resume="S"))

    def test_no_session_on_the_path(self):
        t = build(("n0001", "n0000"))
        t.finish("n0001", status="failed")
        plan = session_plan(t, "n0001", None)
        self.assertEqual((plan.restart, plan.resume, plan.fork), (True, None, False))
        self.assertEqual(len(plan.notes), 1)
        self.assertIn("not available", plan.notes[0])

    def test_fork_without_a_message_id(self):
        t = build(("n0001", "n0000"), ("n0002", "n0001"), n0001=("S", None), n0002=("S", "u2"))
        with self.assertLogs("whittle", "WARNING"):
            plan = session_plan(t, "n0001", None)
        self.assertEqual((plan.resume, plan.fork, plan.resume_at), ("S", True, None))


if __name__ == "__main__":
    unittest.main()
