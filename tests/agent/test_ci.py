# SPDX-License-Identifier: GPL-3.0-or-later
"""The GitHub Actions setup keeps its promises: pinned actions, hosted runners
only, least privilege, and a release only the Linux job can gate. The YAML is
read as text, since PyYAML is not in the lock."""

import contextlib
import hashlib
import http.server
import importlib.util
import io
import os
import re
import subprocess
import sys
import tempfile
import threading
import unittest
import unittest.mock
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
WORKFLOWS = REPO / ".github" / "workflows"
SCRIPTS = REPO / ".github" / "scripts"
HOSTED = {"ubuntu-latest", "windows-latest", "macos-latest"}
FORWARDED = {"${{ inputs.runner }}", "${{ matrix.runner }}"}
BODY = b"a blender archive" * 16


def load(name: str):
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def workflows() -> dict[str, str]:
    return {path.name: path.read_text(encoding="utf-8") for path in sorted(WORKFLOWS.glob("*.yml"))}


def jobs(text: str) -> dict[str, str]:
    """Job id -> its block, from the two-space keys under `jobs:`."""
    body = text[text.index("\njobs:\n"):]
    parts = re.split(r"^  ([\w-]+):\n", body, flags=re.MULTILINE)
    return dict(zip(parts[1::2], parts[2::2]))


def run_blocks(text: str) -> list[str]:
    """The shell of every `run:` step, single line or block."""
    blocks = []
    lines = text.splitlines()
    for index, line in enumerate(lines):
        match = re.match(r"^(\s*)(?:- )?run:\s*(.*)$", line)
        if not match:
            continue
        if match.group(2) != "|":
            blocks.append(match.group(2))
            continue
        indent = len(match.group(1))
        body = []
        for following in lines[index + 1:]:
            if following.strip() and len(following) - len(following.lstrip()) <= indent:
                break
            body.append(following)
        blocks.append("\n".join(body))
    return blocks


class WorkflowTest(unittest.TestCase):
    def test_there_are_the_three_workflows(self):
        self.assertEqual(set(workflows()), {"ci.yml", "release.yml", "test.yml"})

    def test_every_action_is_first_party_and_pinned_to_a_commit(self):
        for name, text in workflows().items():
            for line in text.splitlines():
                match = re.match(r"^\s*(?:- )?uses:\s*(.+)$", line)
                if not match or match.group(1).startswith("./"):
                    continue
                self.assertRegex(match.group(1), r"^actions/[\w./-]+@[0-9a-f]{40} # v\d+\.\d+\.\d+$",
                                 f"{name}: {line.strip()}")

    def test_runners_are_standard_hosted_ones(self):
        for name, text in workflows().items():
            self.assertNotIn("self-hosted", text, name)
            labels = re.findall(r"^ *(?:runs-on|runner): *(\S.*)$", text, flags=re.MULTILINE)
            for row in re.findall(r"^ *runner: \[(.*)\]$", text, flags=re.MULTILINE):
                labels.remove(f"[{row}]")
                labels += row.split(", ")
            self.assertTrue(labels, name)
            for label in labels:
                self.assertIn(label, HOSTED | FORWARDED, name)

    def test_nothing_runs_on_a_fork_with_the_base_repository_s_privileges(self):
        for name, text in workflows().items():
            self.assertNotIn("pull_request_target", text, name)
            self.assertNotIn("secrets.", text, name)

    def test_checkouts_leave_no_credentials_behind(self):
        for name, text in workflows().items():
            checkouts = re.findall(r"uses: actions/checkout@.*\n\s+with:\n\s+persist-credentials: false",
                                   text)
            self.assertEqual(len(checkouts), text.count("actions/checkout@"), name)

    def test_every_job_that_runs_has_a_time_limit(self):
        # A job calling a reusable workflow cannot take one; test.yml's job has it.
        for name, text in workflows().items():
            for job, block in jobs(text).items():
                if "\n    uses: " in block or block.startswith("    uses: "):
                    continue
                self.assertRegex(block, r"(?m)^    timeout-minutes: \d+$", f"{name}: {job}")

    def test_permissions_are_read_only_but_for_publishing(self):
        for name, text in workflows().items():
            # The whole block: a second scope added under contents counts too.
            found = re.search(r"(?m)^permissions:.*\n(?:[ \t]+.*\n)*", text)
            self.assertIsNotNone(found, name)
            self.assertEqual(found.group(0), "permissions:\n  contents: read\n", name)
        granted = {(name, job): block for name, text in workflows().items()
                   for job, block in jobs(text).items() if "permissions:" in block or ": write" in block}
        self.assertEqual(set(granted), {("release.yml", "publish")})
        self.assertRegex(granted["release.yml", "publish"],
                         r"(?m)^    permissions:\n      contents: write\n    steps:$")

    def test_the_publishing_job_runs_nothing_from_the_repository(self):
        publish = jobs(workflows()["release.yml"])["publish"]
        self.assertNotIn("actions/checkout", publish)

    def test_only_the_linux_job_gates_a_release(self):
        release = jobs(workflows()["release.yml"])
        self.assertIn("needs: [tag, linux]", release["publish"])
        self.assertIn("runner: ubuntu-latest", release["linux"])
        self.assertIn("gate: true", release["linux"])
        self.assertIn("gate: false", release["untested"])

    def test_a_failed_gate_stops_the_release(self):
        # Any `if:` on these jobs replaces the implicit success() on what they
        # need, and `if: always()` would publish after a failed gate.
        release = jobs(workflows()["release.yml"])
        for job in ("tag", "linux", "publish"):
            self.assertNotRegex(release[job], r"(?m)^    if:", job)

    def test_only_the_gate_input_can_forgive_a_failure(self):
        found = [(name, line.strip()) for name, text in workflows().items() for line in text.splitlines()
                 if "continue-on-error" in line]
        self.assertEqual(found, [("test.yml", "continue-on-error: ${{ !inputs.gate }}")])

    def test_the_suite_and_the_build_always_run(self):
        test = workflows()["test.yml"]
        for step in ("- name: Run the offline suite\n        run: ./run_tests.sh\n",
                     "- name: Build the extension\n        run: ./build.sh\n"):
            self.assertIn(step, test)

    def test_the_gate_is_on_in_both_callers(self):
        for name in ("ci.yml", "release.yml"):
            linux = jobs(workflows()[name])["linux"]
            self.assertIn("runner: ubuntu-latest", linux, name)
            self.assertIn("gate: true", linux, name)

    def test_ci_runs_are_superseded_but_releases_never_are(self):
        self.assertIn("cancel-in-progress: true", workflows()["ci.yml"])
        self.assertIn("cancel-in-progress: false", workflows()["release.yml"])

    def test_no_expression_is_pasted_into_a_shell_script(self):
        # A tag or branch name is the pusher's text: it goes through env.
        for name, text in workflows().items():
            for block in run_blocks(text):
                self.assertNotIn("${{", block, name)


class ReleaseTagTest(unittest.TestCase):
    def setUp(self):
        self.tag = load("release_tag")

    def test_a_plain_tag_is_a_release(self):
        self.assertEqual(self.tag.check("v1.2.3", "1.2.3"), ("1.2.3", False))

    def test_a_hyphen_makes_a_prerelease_of_the_part_before_it(self):
        self.assertEqual(self.tag.check("v1.2.3-rc1", "1.2.3"), ("1.2.3", True))

    def test_bad_tags_are_refused(self):
        for tag in ("v1.2.4", "1.2.3", "v1.2", "v1.2.3-", "v1.2.4-rc1", "version1.2.3", "v"):
            with self.subTest(tag=tag), self.assertRaises(ValueError):
                self.tag.check(tag, "1.2.3")

    def test_it_reads_the_real_manifest_and_writes_the_outputs(self):
        version = re.search(r'(?m)^version = "(.+)"$',
                            (REPO / "whittle" / "blender_manifest.toml").read_text(encoding="utf-8")).group(1)
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "output"
            environ = {**os.environ, "GITHUB_OUTPUT": str(output)}
            done = subprocess.run([sys.executable, str(SCRIPTS / "release_tag.py"), f"v{version}-rc1"],
                                  env=environ, capture_output=True, text=True, timeout=30)
            self.assertEqual(done.returncode, 0, done.stderr)
            self.assertEqual(output.read_text(encoding="utf-8"), f"version={version}\nprerelease=true\n")
            done = subprocess.run([sys.executable, str(SCRIPTS / "release_tag.py"), "v0.0.0-not-this"],
                                  env=environ, capture_output=True, text=True, timeout=30)
            self.assertEqual(done.returncode, 1)
            self.assertIn("::error::", done.stderr)


class FetchBlenderTest(unittest.TestCase):
    def setUp(self):
        self.fetch = load("fetch_blender")
        quiet = contextlib.redirect_stdout(io.StringIO())
        quiet.__enter__()
        self.addCleanup(quiet.__exit__, None, None, None)

    def test_each_runner_platform_has_a_pinned_archive(self):
        self.assertEqual(set(self.fetch.ARCHIVES),
                         {("Linux", "x86_64"), ("Windows", "AMD64"), ("Darwin", "arm64")})
        for name, digest in self.fetch.ARCHIVES.values():
            self.assertTrue(name.startswith(f"blender-{self.fetch.VERSION}-"), name)
            self.assertRegex(digest, r"^[0-9a-f]{64}$")

    def test_the_url_is_blender_s_own_over_https(self):
        self.assertTrue(self.fetch.BASE_URL.startswith("https://download.blender.org/release/"))

    def test_a_cached_archive_that_matches_is_used_without_downloading(self):
        with tempfile.TemporaryDirectory() as tmp:
            archive = Path(tmp) / "a.zip"
            archive.write_bytes(b"blender")
            with unittest.mock.patch.object(self.fetch, "download") as download:
                found = self.fetch.fetch("a.zip", self.fetch.sha256(archive), Path(tmp))
            self.assertEqual(found, archive)
            download.assert_not_called()

    def test_a_stale_cache_is_replaced_by_a_fresh_download(self):
        def good(url, target, expected):
            target.write_bytes(b"blender")

        with tempfile.TemporaryDirectory() as tmp:
            archive = Path(tmp) / "a.zip"
            archive.write_bytes(b"a cache gone bad")
            with unittest.mock.patch.object(self.fetch, "download", good):
                self.fetch.fetch("a.zip", "0" * 64, Path(tmp))
            self.assertEqual(archive.read_bytes(), b"blender")


def whole(handler):
    handler.send_response(200)
    handler.send_header("Content-Length", str(len(BODY)))
    handler.end_headers()
    handler.wfile.write(BODY)


def cut_off(handler):
    handler.send_response(200)
    handler.send_header("Content-Length", str(len(BODY)))
    handler.end_headers()
    handler.wfile.write(BODY[:5])


def cut_off_chunked(handler):
    handler.protocol_version = "HTTP/1.1"
    handler.send_response(200)
    handler.send_header("Transfer-Encoding", "chunked")
    handler.end_headers()
    handler.wfile.write(b"100\r\n" + BODY[:5])
    handler.close_connection = True


def tampered(handler):
    handler.send_response(200)
    handler.send_header("Content-Length", str(len(BODY)))
    handler.end_headers()
    handler.wfile.write(BODY[::-1])


def not_found(handler):
    handler.send_error(404)


class DownloadTest(unittest.TestCase):
    """Against a real local server: what a cut connection does is the point."""

    def setUp(self):
        self.fetch = load("fetch_blender")
        for quiet in (contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO())):
            quiet.__enter__()
            self.addCleanup(quiet.__exit__, None, None, None)
        wait = unittest.mock.patch.object(self.fetch, "RETRY_WAIT", 0)
        wait.start()
        self.addCleanup(wait.stop)
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.folder = Path(tmp.name)
        self.target = self.folder / "a.zip"
        self.digest = hashlib.sha256(BODY).hexdigest()

    def serve(self, *replies) -> tuple[str, list]:
        """A URL answering with each reply in turn, the last one repeating."""
        served = []

        class Handler(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                served.append(self.path)
                replies[min(len(served), len(replies)) - 1](self)

            def log_message(self, *args):
                pass

        server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(thread.join, 10)
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        return f"http://127.0.0.1:{server.server_address[1]}/a.zip", served

    def assert_nothing_left(self):
        self.assertEqual(list(self.folder.iterdir()), [])

    def test_a_whole_download_takes_one_request(self):
        url, served = self.serve(whole)
        self.fetch.download(url, self.target, self.digest)
        self.assertEqual(self.target.read_bytes(), BODY)
        self.assertEqual(len(served), 1)

    def test_a_cut_connection_is_retried(self):
        for cut in (cut_off, cut_off_chunked):
            with self.subTest(cut=cut.__name__):
                url, served = self.serve(cut, whole)
                self.fetch.download(url, self.target, self.digest)
                self.assertEqual(self.target.read_bytes(), BODY)
                self.assertEqual(len(served), 2)
                self.assertEqual([path.name for path in self.folder.iterdir()], ["a.zip"])
                self.target.unlink()

    def test_a_wrong_download_is_retried(self):
        url, served = self.serve(tampered, whole)
        self.fetch.download(url, self.target, self.digest)
        self.assertEqual(self.target.read_bytes(), BODY)
        self.assertEqual(len(served), 2)

    def test_a_connection_that_keeps_being_cut_fails_and_leaves_nothing(self):
        url, served = self.serve(cut_off)
        with self.assertRaisesRegex(SystemExit, "cut off after 5 of"):
            self.fetch.download(url, self.target, self.digest)
        self.assertEqual(len(served), self.fetch.ATTEMPTS)
        self.assert_nothing_left()

    def test_a_download_that_never_matches_fails_and_leaves_nothing(self):
        url, served = self.serve(tampered)
        with self.assertRaisesRegex(SystemExit, "SHA-256 mismatch"):
            self.fetch.download(url, self.target, self.digest)
        self.assertEqual(len(served), self.fetch.ATTEMPTS)
        self.assert_nothing_left()

    def test_an_http_error_fails_and_leaves_nothing(self):
        url, served = self.serve(not_found)
        with self.assertRaisesRegex(SystemExit, "could not download"):
            self.fetch.download(url, self.target, self.digest)
        self.assert_nothing_left()


@unittest.skipIf(sys.platform == "win32", "the shim is for POSIX runners")
class TimeoutShimTest(unittest.TestCase):
    SHIM = SCRIPTS / "shims" / "timeout"

    def run_shim(self, *argv):
        # Run as PATH runs it, so a lost executable bit fails here too.
        return subprocess.run([str(self.SHIM), *argv], capture_output=True, timeout=30)

    def test_it_passes_the_command_s_exit_code_on(self):
        self.assertEqual(self.run_shim("10", sys.executable, "-c", "raise SystemExit(7)").returncode, 7)

    def test_it_stops_an_overrunning_command_and_exits_124(self):
        self.assertEqual(self.run_shim("0.2", sys.executable, "-c", "import time; time.sleep(20)").returncode, 124)


if __name__ == "__main__":
    unittest.main()
