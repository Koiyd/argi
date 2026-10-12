#!/usr/bin/env python3
# Copyright 2025-2026 the original author or authors.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     https://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Offline regression tests for the runtime dependency audit."""

import contextlib
import importlib.util
import io
import json
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest.mock import patch


SCRIPT = Path(__file__).resolve().parents[1] / "scripts/audit-runtime-dependencies.py"
SPEC = importlib.util.spec_from_file_location("dependency_audit", SCRIPT)
AUDIT = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(AUDIT)


class RuntimeAuditTest(unittest.TestCase):
    def test_collects_nested_dependencies_and_excludes_own_artifacts(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "target").mkdir()
            (root / "pom.xml").write_text(
                '<project xmlns="http://maven.apache.org/POM/4.0.0"/>', encoding="utf-8")
            dependency = {"groupId": "org.example", "artifactId": "library", "version": "1.0"}
            own = {"groupId": "io.github.agentic-ai-java", "artifactId": "argi-api",
                   "version": "2.1", "children": [dependency]}
            (root / "target/tree.json").write_text(json.dumps({"children": [own, dependency]}),
                                                   encoding="utf-8")
            self.assertEqual((["."], {("org.example:library", "1.0"): {"."}}),
                             AUDIT.collect_packages(root, "tree.json"))

    def test_missing_tree_is_a_failure(self):
        with contextlib.redirect_stderr(io.StringIO()), patch.object(
                AUDIT, "audit", side_effect=FileNotFoundError("missing tree")):
            self.assertEqual(2, AUDIT.main([]))

    def test_rejects_tree_path(self):
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            AUDIT.main(["--tree-name", "../tree.json"])

    def test_batch_pagination(self):
        responses = [{"results": [{"vulns": [{"id": "A"}], "next_page_token": "next"}]},
                     {"vulns": [{"id": "B"}]}]
        with patch.object(AUDIT, "request_json", side_effect=responses) as request:
            expected = {"A": {("org.example:lib", "1")}, "B": {("org.example:lib", "1")}}
            self.assertEqual(expected, AUDIT.query_advisories({("org.example:lib", "1"): {"."}}))
            self.assertEqual("next", request.call_args.args[1]["page_token"])

    def test_incomplete_batch_fails(self):
        with patch.object(AUDIT, "request_json", return_value={"results": []}):
            with self.assertRaisesRegex(ValueError, "incomplete"):
                AUDIT.query_advisories({("org.example:lib", "1"): {"."}})

    def test_repeated_token_fails(self):
        response = {"next_page_token": "same"}
        with patch.object(AUDIT, "request_json", side_effect=[{"results": [response]}, response]):
            with self.assertRaisesRegex(ValueError, "repeated"):
                AUDIT.query_advisories({("org.example:lib", "1"): {"."}})

    def test_severity_and_withdrawn_rules(self):
        coordinate = ("org.example:lib", "1")
        for severity, withdrawn, expected in [("HIGH", False, 1), ("CRITICAL", False, 1),
                                              (None, False, 1), ("MODERATE", False, 0),
                                              ("HIGH", True, 0)]:
            with self.subTest(severity=severity, withdrawn=withdrawn):
                advisory = {"withdrawn": "2026-01-01"} if withdrawn else {}
                if severity:
                    advisory["database_specific"] = {"severity": severity}
                with contextlib.redirect_stdout(io.StringIO()), \
                        patch.object(AUDIT, "collect_packages", return_value=(["."], {coordinate: {"."}})), \
                        patch.object(AUDIT, "query_advisories", return_value={"A": {coordinate}}), \
                        patch.object(AUDIT, "request_json", return_value=advisory):
                    self.assertEqual(expected, AUDIT.audit(Path("."), "tree.json"))

    def test_http_retry_backoff_and_limit(self):
        for status, delay in [(429, 20), (503, 2), (400, None)]:
            with self.subTest(status=status):
                error = urllib.error.HTTPError("https://api.osv.dev", status, "failure", {}, None)
                with patch.object(AUDIT.urllib.request, "urlopen", side_effect=error) as request, \
                        patch.object(AUDIT.time, "sleep") as sleep, self.assertRaises(urllib.error.HTTPError):
                    AUDIT.request_json("/querybatch", {"queries": []})
                self.assertEqual(1 if delay is None else 2, request.call_count)
                self.assertEqual([] if delay is None else [(delay,)],
                                 [call.args for call in sleep.call_args_list])

    def test_timeout_retry_and_successful_response(self):
        with patch.object(AUDIT.urllib.request, "urlopen", side_effect=TimeoutError), \
                patch.object(AUDIT.time, "sleep") as sleep, self.assertRaises(TimeoutError):
            AUDIT.request_json("/querybatch")
        sleep.assert_called_once_with(2)
        with patch.object(AUDIT.urllib.request, "urlopen", return_value=io.BytesIO(b'{"results": []}')):
            self.assertEqual({"results": []}, AUDIT.request_json("/querybatch"))


if __name__ == "__main__":
    unittest.main()
