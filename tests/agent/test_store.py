# SPDX-License-Identifier: GPL-3.0-or-later
import shutil
import tempfile
import unittest
import uuid
from pathlib import Path

from claude_agent_sdk import ClaudeAgentOptions
from claude_agent_sdk._internal.session_resume import materialize_resume_session
from claude_agent_sdk._internal.session_store_validation import validate_session_store_options

from whittle.agent.runner import build_options
from whittle.agent.store import FolderSessionStore
from whittle.agent.tools import ToolContext, build_servers


def entry(n, **extra):
    return {"type": "user", "uuid": f"u{n}", "n": n, **extra}


class FolderSessionStoreTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="whittle-store-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.store = FolderSessionStore(self.tmp / "sdk")

    async def test_append_and_load_in_order(self):
        key = {"project_key": "anything", "session_id": "s1"}
        self.assertIsNone(await self.store.load(key))
        await self.store.append(key, [entry(1), entry(2, text="ünïcode")])
        await self.store.append(key, [])
        await self.store.append(key, [entry(3)])
        self.assertEqual(await self.store.load(key), [entry(1), entry(2, text="ünïcode"), entry(3)])
        self.assertEqual((self.tmp / "sdk" / "s1.jsonl").read_text(encoding="utf-8").count("\n"), 3)

    async def test_one_store_per_chat_ignores_the_project_key(self):
        """The project key follows the cwd, which moves with the chat; the
        store is the chat's own, so a moved chat still finds its sessions."""
        await self.store.append({"project_key": "-old-place", "session_id": "s1"}, [entry(1)])
        self.assertEqual(await self.store.load({"project_key": "-new-place", "session_id": "s1"}), [entry(1)])

    async def test_subagent_transcripts(self):
        main = {"project_key": "p", "session_id": "s1"}
        sub = {**main, "subpath": "subagents/agent-1"}
        await self.store.append(main, [entry(1)])
        await self.store.append(sub, [entry(2)])
        self.assertEqual(await self.store.load(main), [entry(1)])
        self.assertEqual(await self.store.load(sub), [entry(2)])
        self.assertTrue((self.tmp / "sdk" / "s1" / "subagents" / "agent-1.jsonl").is_file())
        self.assertEqual(await self.store.list_subkeys(main), ["subagents/agent-1"])
        self.assertEqual(await self.store.list_subkeys({"project_key": "p", "session_id": "s2"}), [])

    async def test_keys_cannot_leave_the_folder(self):
        for key in ({"session_id": "../x"}, {"session_id": "/etc/passwd"}, {"session_id": ""},
                    {"session_id": "s1", "subpath": "../../x"}, {"session_id": "s1", "subpath": "/abs"}):
            with self.assertRaises(ValueError, msg=key):
                await self.store.append({"project_key": "p", **key}, [entry(1)])
        self.assertFalse((self.tmp / "x.jsonl").exists())

    async def test_a_damaged_line_is_skipped(self):
        path = self.tmp / "sdk" / "s1.jsonl"
        path.parent.mkdir(parents=True)
        path.write_text('{"type": "user", "n": 1}\n{"type": "us\n', encoding="utf-8")
        with self.assertLogs("whittle.agent", "WARNING"):
            self.assertEqual(await self.store.load({"project_key": "p", "session_id": "s1"}),
                             [{"type": "user", "n": 1}])

    async def test_the_sdk_resumes_from_it(self):
        """What a store-backed resume does before the CLI starts: the SDK
        loads the session from the store into a temporary config folder."""
        session = str(uuid.uuid4())
        cwd = self.tmp / "chat"
        cwd.mkdir()
        config = self.tmp / "claude"
        config.mkdir()
        await self.store.append({"project_key": "p", "session_id": session}, [entry(1), entry(2)])
        await self.store.append({"project_key": "p", "session_id": session, "subpath": "subagents/a1"},
                                [entry(3)])
        options = ClaudeAgentOptions(cwd=str(cwd), resume=session, session_store=self.store,
                                     env={"CLAUDE_CONFIG_DIR": str(config)})
        validate_session_store_options(options)
        materialized = await materialize_resume_session(options)
        self.assertIsNotNone(materialized)
        try:
            files = sorted(p.relative_to(materialized.config_dir).as_posix()
                           for p in materialized.config_dir.rglob("*.jsonl"))
            self.assertEqual(len(files), 2, files)
            main = next(materialized.config_dir.rglob(f"{session}.jsonl"))
            self.assertEqual(main.read_text().count("\n"), 2)
        finally:
            await materialized.cleanup()

    def test_runner_options(self):
        params = {"session_dir": str(self.tmp), "store_dir": str(self.tmp / "sdk"), "model": "m",
                  "resume": None, "fork": False, "settings": {}}
        options = build_options(params, build_servers(ToolContext(None)), inline_skills=False)
        self.assertIsInstance(options.session_store, FolderSessionStore)
        self.assertEqual(options.session_store.folder, self.tmp / "sdk")
        self.assertFalse(options.enable_file_checkpointing, "the SDK refuses checkpoints with a store")
        validate_session_store_options(options)
        options = build_options({**params, "store_dir": None}, build_servers(ToolContext(None)),
                                inline_skills=False)
        self.assertIsNone(options.session_store)
