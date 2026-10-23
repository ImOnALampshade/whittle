# SPDX-License-Identifier: GPL-3.0-or-later
"""The history tree in session.json, and the rule that decides which SDK
session a submit continues from.

Stdlib only, so the agent tests can exercise the branching rule without
Blender. Node ids are the node folder names (n0000, n0001, ...).
"""

import logging
import time
from dataclasses import asdict, dataclass, field, fields

from . import formats

log = logging.getLogger("whittle")

SESSION_FORMAT = "whittle.session"
STATUSES = ("running", "complete", "interrupted", "failed")
ROOT_LABEL = "Start"
LABEL_CHARS = 60


def now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S%z")


def label_for(prompt: str) -> str:
    first = next((line.strip() for line in prompt.splitlines() if line.strip()), "")
    if not first:
        return "(sketch only)"
    return first if len(first) <= LABEL_CHARS else first[:LABEL_CHARS - 1] + "…"


@dataclass
class Node:
    id: str
    parent: str | None
    children: list[str] = field(default_factory=list)
    created: str = ""
    status: str = "running"
    label: str = ""
    prompt: str = ""
    agent_session_id: str | None = None
    # The SDK session the turn carried on, recorded when it began: a turn
    # that never finished still moved that conversation past its parent.
    continued_session: str | None = None
    # The last transcript message of this node's turn: where a branch from
    # this node cuts the SDK conversation.
    agent_message_uuid: str | None = None
    cost_usd: float | None = None
    num_turns: int | None = None
    duration_ms: int | None = None
    kept_partial: bool = False
    # An interrupted turn whose target was put back as it was before it.
    restored: bool = False
    # Whether target.blend was written for this node.
    snapshot: bool = False
    # whittle_uid of every object the agent created in this turn.
    created_uids: list[str] = field(default_factory=list)
    # A failed turn that changed nothing: kept (its request, transcript and
    # place in the SDK conversation), but folded into its parent, so it is
    # never current, never shown and never has children.
    folded: bool = False

    def to_json(self) -> dict:
        return asdict(self)


_NODE_SPEC = {
    "id": str, "parent": (str, None), "children": list, "created": str, "status": str,
    "label": str, "prompt": str, "agent_session_id": (str, None),
    "agent_message_uuid": (str, None), "cost_usd": (float, None), "num_turns": (int, None),
    "duration_ms": (int, None), "kept_partial": bool, "restored": bool, "snapshot": bool,
    "created_uids": list,
}
# Keys a session.json written before they existed may lack.
_OPTIONAL_SPEC = {"continued_session": (str, None), "folded": bool}


class TreeError(ValueError):
    pass


@dataclass
class Tree:
    root: str
    current: str
    nodes: dict[str, Node]
    created: str = ""

    @classmethod
    def new(cls, root_id: str = "n0000", label: str = ROOT_LABEL) -> "Tree":
        stamp = now_iso()
        root = Node(id=root_id, parent=None, created=stamp, status="complete", label=label)
        return cls(root=root_id, current=root_id, nodes={root_id: root}, created=stamp)

    def node(self, node_id: str) -> Node:
        try:
            return self.nodes[node_id]
        except KeyError:
            raise TreeError(f"no history node {node_id!r}") from None

    def add(self, node_id: str, parent: str, *, prompt: str, label: str | None = None) -> Node:
        """A running node under parent. Adding the same node under the same
        parent again returns it unchanged, so a resubmit keeps its node."""
        existing = self.nodes.get(node_id)
        if existing is not None:
            if existing.parent != parent:
                raise TreeError(f"node {node_id} already exists under {existing.parent}")
            return existing
        parent_node = self.node(parent)
        node = Node(id=node_id, parent=parent, created=now_iso(), prompt=prompt,
                    label=label if label is not None else label_for(prompt))
        self.nodes[node_id] = node
        parent_node.children.append(node_id)
        return node

    def discard(self, node_id: str) -> None:
        """Forgets a node whose turn never started. Only a leaf can go."""
        node = self.nodes.get(node_id)
        if node is None:
            return
        if node.children:
            raise TreeError(f"node {node_id} has children")
        if node_id == self.root:
            raise TreeError("the root cannot be discarded")
        parent = self.nodes.get(node.parent)
        if parent is not None and node_id in parent.children:
            parent.children.remove(node_id)
        del self.nodes[node_id]
        if self.current == node_id:
            self.current = node.parent

    def finish(self, node_id: str, **values) -> Node:
        node = self.node(node_id)
        known = {f.name for f in fields(Node)} - {"id", "parent", "children", "created"}
        unknown = set(values) - known
        if unknown:
            raise TreeError(f"unknown node fields {sorted(unknown)}")
        if "status" in values and values["status"] not in STATUSES:
            raise TreeError(f"unknown status {values['status']!r}")
        for key, value in values.items():
            setattr(node, key, value)
        return node

    def visible_children(self, node_id: str) -> list[str]:
        """The children the history shows: all but folded failures."""
        return [c for c in self.node(node_id).children if not self.node(c).folded]

    def is_leaf(self, node_id: str) -> bool:
        """No turn grew from it, a folded failure aside."""
        return not self.visible_children(node_id)

    def siblings(self, node_id: str) -> list[str]:
        """The node and the other visible children of its parent, in creation
        order: the alternatives a branch switcher steps through. The root has
        none but itself."""
        parent = self.node(node_id).parent
        if parent is None:
            return [node_id]
        return self.visible_children(parent)

    def leaves_under(self, node_id: str) -> list[str]:
        """The visible leaves of the subtree at node_id (itself when it is a
        leaf), newest first by node number."""
        leaves, todo = [], [node_id]
        while todo:
            current = todo.pop()
            children = self.visible_children(current)
            if children:
                todo.extend(children)
            else:
                leaves.append(current)
        return sorted(leaves, key=formats.node_number, reverse=True)

    def newest_leaf(self, node_id: str) -> str:
        """Where a branch that starts at node_id ends: its newest leaf."""
        return self.leaves_under(node_id)[0]

    def path(self, node_id: str) -> list[str]:
        """The root, then each node down to node_id."""
        out, seen = [], set()
        current = node_id
        while current is not None:
            if current in seen:
                raise TreeError(f"the tree has a cycle at {current}")
            seen.add(current)
            out.append(current)
            current = self.node(current).parent
        return out[::-1]

    def walk(self, *, folded: bool = False) -> list[tuple[Node, int]]:
        """Every node depth first, children in creation order, with its
        depth; folded failures only when asked for."""
        out = []
        todo = [(self.root, 0)]
        while todo:
            node_id, depth = todo.pop()
            node = self.node(node_id)
            out.append((node, depth))
            children = node.children if folded else self.visible_children(node_id)
            todo.extend((child, depth + 1) for child in reversed(children))
        return out

    def all_created_uids(self) -> set[str]:
        return {uid for node in self.nodes.values() for uid in node.created_uids}

    def latest_in_session(self, session_id: str) -> str | None:
        """The newest node, by number, that ran in this SDK session, finished
        or not."""
        found = [n.id for n in self.nodes.values()
                 if session_id in (n.agent_session_id, n.continued_session)]
        return max(found, key=formats.node_number, default=None)

    def recover(self) -> list[str]:
        """Marks turns that were still running (Blender went away mid-turn)
        as failed; returns their ids."""
        stale = [n.id for n in self.nodes.values() if n.status == "running"]
        for node_id in stale:
            self.nodes[node_id].status = "failed"
        return stale


# -- session.json --------------------------------------------------------------

def to_json(tree: Tree) -> dict:
    return {"format": SESSION_FORMAT, "version": formats.VERSION, "created": tree.created,
            "root": tree.root, "current": tree.current,
            "nodes": {node_id: node.to_json() for node_id, node in tree.nodes.items()}}


def validate_session(obj: dict, where: str = "session.json") -> None:
    formats._check_header(obj, where, SESSION_FORMAT)
    formats._check(obj, where, {"created": str, "root": str, "current": str, "nodes": dict})
    nodes = obj["nodes"]
    for node_id, node in nodes.items():
        w = f"{where}: nodes[{node_id!r}]"
        # Node ids name folders, so one that is not n<digits> could point
        # anywhere (a chat unpacked from someone else's file, say).
        if not formats.is_node_id(node_id):
            raise formats.FormatError(f"{w}: not a node id")
        if not isinstance(node, dict):
            raise formats.FormatError(f"{w} is not an object")
        formats._check(node, w, _NODE_SPEC)
        formats._check(node, w, {k: t for k, t in _OPTIONAL_SPEC.items() if k in node})
        if node["id"] != node_id:
            raise formats.FormatError(f"{w}: id is {node['id']!r}")
        if node["status"] not in STATUSES:
            raise formats.FormatError(f"{w}: unknown status {node['status']!r}")
        if node.get("folded") and (node["status"] != "failed" or node["children"]):
            raise formats.FormatError(f"{w}: only a failed leaf can be folded")
        formats._check_names(node["children"], w, "children")
        formats._check_names(node["created_uids"], w, "created_uids")
        if node["parent"] is not None and node["parent"] not in nodes:
            raise formats.FormatError(f"{w}: parent {node['parent']!r} is not a node")
        for child in node["children"]:
            if child not in nodes or nodes[child]["parent"] != node_id:
                raise formats.FormatError(f"{w}: child {child!r} does not name it as parent")
    for key in ("root", "current"):
        if obj[key] not in nodes:
            raise formats.FormatError(f"{where}: key {key!r} names no node ({obj[key]!r})")
    if nodes[obj["current"]].get("folded"):
        raise formats.FormatError(f"{where}: the current node {obj['current']!r} is folded")
    if nodes[obj["root"]]["parent"] is not None:
        raise formats.FormatError(f"{where}: the root has a parent")


def from_json(obj: dict) -> Tree:
    validate_session(obj)
    nodes = {node_id: Node(**{f.name: data[f.name] for f in fields(Node) if f.name in data})
             for node_id, data in obj["nodes"].items()}
    for node in nodes.values():
        node.children = list(node.children)
        node.created_uids = list(node.created_uids)
    return Tree(root=obj["root"], current=obj["current"], nodes=nodes, created=obj["created"])


def read_session(path) -> tuple[Tree, list[str]]:
    """The tree in session.json, with turns left running marked failed;
    also returns the ids it recovered. FormatError names the file and key."""
    obj = formats.read_json(path)
    validate_session(obj, str(path))
    tree = from_json(obj)
    return tree, tree.recover()


def write_session(path, tree: Tree) -> None:
    obj = to_json(tree)
    validate_session(obj, str(path))
    formats.write_json_atomic(path, obj)


# -- which SDK session a submit continues --------------------------------------

@dataclass(frozen=True)
class SessionPlan:
    # False: the live SDK client already ends at this node.
    restart: bool
    resume: str | None = None
    fork: bool = False
    resume_at: str | None = None
    # Context lines for the agent on the next submit.
    notes: tuple[str, ...] = ()


def _describe(node: Node) -> str:
    return f"{node.id} ({node.label})" if node.label else node.id


def session_plan(tree: Tree, node_id: str, live: str | None) -> SessionPlan:
    """How the next submit, made while the scene reflects node_id, reaches a
    conversation that matches it. `live` is the node the running SDK client
    last finished on, or None when there is no client."""
    if live is not None and live == node_id:
        return SessionPlan(restart=False)
    node = tree.node(node_id)
    anchor = next((tree.node(n) for n in reversed(tree.path(node_id))
                   if tree.node(n).agent_session_id), None)
    if anchor is None:
        notes = () if node_id == tree.root else (
            f"The scene reflects history node {_describe(node)}, but the conversation that "
            "led to it is not available. Inspect the target before editing.",)
        return SessionPlan(restart=True, notes=notes)
    notes = []
    if anchor.id != node_id:
        notes.append(f"The turns after history node {_describe(anchor)} on this branch are not "
                     f"in this conversation. The target reflects {_describe(node)}; inspect it "
                     "before editing.")
    session = anchor.agent_session_id
    if anchor.id == node_id and tree.latest_in_session(session) == node_id:
        return SessionPlan(restart=True, resume=session, notes=tuple(notes))
    if anchor.agent_message_uuid is None:
        log.warning("branching from %s without a message id: the whole session %s is forked",
                    anchor.id, session)
    notes.append(f"You are continuing from history node {_describe(node)}. Changes made on "
                 "other branches after it do not exist in the scene.")
    return SessionPlan(restart=True, resume=session, fork=True,
                       resume_at=anchor.agent_message_uuid, notes=tuple(notes))
