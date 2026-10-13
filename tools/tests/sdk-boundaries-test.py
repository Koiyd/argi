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

"""Regression tests for the fail-closed SDK isolation check."""

import contextlib
import importlib.util
import io
import json
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "scripts/check-sdk-boundaries.py"
SPEC = importlib.util.spec_from_file_location("sdk_boundaries", SCRIPT)
AUDIT = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(AUDIT)


class SdkBoundariesTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        for index, module in enumerate(AUDIT.NEUTRAL_MODULES):
            directory = self.root / module
            directory.mkdir(parents=True)
            (directory / "pom.xml").write_text(
                '<project xmlns="http://maven.apache.org/POM/4.0.0">'
                f'<artifactId>module-{index}</artifactId><dependencies/></project>', encoding="utf-8")
            (directory / "src/main/java").mkdir(parents=True)
            (directory / "src/main/java/Example.java").write_text("class Example {}", encoding="utf-8")
            (directory / "target/classes").mkdir(parents=True)
            (directory / "target/classes/Example.class").write_bytes(b"neutral fixture")
            (directory / "target/runtime-dependencies.json").write_text(
                json.dumps({"artifactId": f"module-{index}", "children": []}), encoding="utf-8")
        self.directory = self.root / AUDIT.NEUTRAL_MODULES[0]

    def result(self):
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            return AUDIT.main(["--root", str(self.root)])

    def test_neutral_modules_pass(self):
        self.assertEqual(0, self.result())

    def test_explicit_consumer_selection_checks_only_selected_module(self):
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(0, AUDIT.main([
                "--root", str(self.root), "--module", AUDIT.NEUTRAL_MODULES[0]]))

    def test_explicit_consumer_selection_fails_on_sdk_reference(self):
        (self.directory / "src/main/java/Example.java").write_text(
            "import com.google.adk.models.BaseLlm;", encoding="utf-8")
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(1, AUDIT.main([
                "--root", str(self.root), "--module", AUDIT.NEUTRAL_MODULES[0]]))

    def test_source_reference_fails(self):
        (self.directory / "src/main/java/Example.java").write_text(
            "import org.springframework.ai.chat.model.ChatModel;", encoding="utf-8")
        self.assertEqual(1, self.result())

    def test_bytecode_signature_fails(self):
        (self.directory / "target/classes/Example.class").write_bytes(
            b"Ldev/langchain4j/model/chat/ChatModel;")
        self.assertEqual(1, self.result())

    def test_adapter_bytecode_reference_fails(self):
        (self.directory / "target/classes/Example.class").write_bytes(
            b"io/github/agentic/ai/adapter/springai/SpringAiChatClient")
        self.assertEqual(1, self.result())

    def legacy_fixture(self, text, bytecode=b"neutral"):
        source = self.root / AUDIT.LEGACY_READER
        source.parent.mkdir(parents=True, exist_ok=True)
        source.write_text(text, encoding="utf-8")
        compiled = self.root / AUDIT.LEGACY_CLASS
        compiled.parent.mkdir(parents=True, exist_ok=True)
        compiled.write_bytes(bytecode)

    def test_exact_migration_wire_literals_are_allowed_only_in_reader(self):
        name = AUDIT.LEGACY_WIRE_NAMES[1]
        encoded = name.encode()
        self.legacy_fixture(f'class LegacyChatRecordSupport {{ String wire = "{name}"; }}',
                            b'\x01' + len(encoded).to_bytes(2, 'big') + encoded)
        self.assertEqual(0, self.result())
        (self.directory / "src/main/java/Example.java").write_text(f'class Example {{ String wire = "{name}"; }}')
        self.assertEqual(1, self.result())

    def test_migration_exemption_does_not_allow_imports_reflection_or_new_wire_types(self):
        name = AUDIT.LEGACY_WIRE_NAMES[1]
        for text in [f'import {name};', f'Class.forName("{name}");',
                     'String unsupported = "org.springframework.ai.chat.messages.NewMessage";']:
            with self.subTest(text=text):
                self.legacy_fixture(text)
                self.assertEqual(1, self.result())

    def test_migration_exemption_does_not_allow_type_symbols_or_partial_utf8_matches(self):
        name = AUDIT.LEGACY_WIRE_NAMES[1]
        for value in [name.replace('.', '/').encode(), (name + "$Builder").encode()]:
            self.legacy_fixture('class LegacyChatRecordSupport {}',
                                b'\x01' + len(value).to_bytes(2, 'big') + value)
            self.assertEqual(1, self.result())

    def test_transitive_dependency_fails(self):
        (self.directory / "target/runtime-dependencies.json").write_text(json.dumps({
            "artifactId": "module-0", "children": [{"groupId": "example", "artifactId": "bridge",
                "version": "1", "children": [{"groupId": "io.agentscope", "artifactId": "agentscope",
                    "version": "2", "scope": "runtime"}]}]}), encoding="utf-8")
        self.assertEqual(1, self.result())

    def test_non_test_optional_dependency_fails(self):
        pom = self.directory / "pom.xml"
        pom.write_text(pom.read_text().replace("<dependencies/>", '<dependencies><dependency>'
            '<groupId>org.springframework.ai</groupId><artifactId>spring-ai-model</artifactId>'
            '<scope>provided</scope><optional>true</optional></dependency></dependencies>'), encoding="utf-8")
        self.assertEqual(1, self.result())

    def test_explicit_test_dependency_allowed(self):
        pom = self.directory / "pom.xml"
        pom.write_text(pom.read_text().replace("<dependencies/>", '<dependencies><dependency>'
            '<groupId>org.springframework.ai</groupId><artifactId>spring-ai-model</artifactId>'
            '<scope>test</scope></dependency></dependencies>'), encoding="utf-8")
        self.assertEqual(0, self.result())

    def test_base_api_non_sdk_dependencies_fail_in_all_non_test_scopes(self):
        pom = self.directory / "pom.xml"
        original = pom.read_text()
        for scope in ("compile", "runtime", "provided", "system"):
            with self.subTest(scope=scope):
                pom.write_text(original.replace("<dependencies/>", '<dependencies><dependency>'
                    '<groupId>org.jspecify</groupId><artifactId>jspecify</artifactId>'
                    f'<scope>{scope}</scope></dependency></dependencies>'), encoding="utf-8")
                self.assertEqual(1, self.result())

    def test_base_api_inherited_runtime_dependency_fails(self):
        (self.directory / "target/runtime-dependencies.json").write_text(json.dumps({
            "artifactId": "module-0", "children": [{"groupId": "org.jspecify", "artifactId": "jspecify",
                "version": "1.0.1", "scope": "compile"}]}), encoding="utf-8")
        self.assertEqual(1, self.result())

    def test_base_api_inherited_provided_dependency_fails_without_runtime_entry(self):
        parent = self.root / "pom.xml"
        parent.write_text('<project xmlns="http://maven.apache.org/POM/4.0.0"><dependencies>'
            '<dependency><groupId>org.jspecify</groupId><artifactId>jspecify</artifactId>'
            '<scope>provided</scope></dependency></dependencies></project>', encoding="utf-8")
        pom = self.directory / "pom.xml"
        pom.write_text(pom.read_text().replace('<artifactId>module-0</artifactId>', '<parent>'
            '<relativePath>../../pom.xml</relativePath></parent><artifactId>module-0</artifactId>'),
            encoding="utf-8")
        self.assertEqual(1, self.result())

    def test_non_api_neutral_module_can_use_non_sdk_dependency(self):
        directory = self.root / AUDIT.NEUTRAL_MODULES[1]
        pom = directory / "pom.xml"
        pom.write_text(pom.read_text().replace("<dependencies/>", '<dependencies><dependency>'
            '<groupId>org.jspecify</groupId><artifactId>jspecify</artifactId>'
            '</dependency></dependencies>'), encoding="utf-8")
        self.assertEqual(0, self.result())

    def test_missing_compile_fails(self):
        (self.directory / "target/classes/Example.class").unlink()
        self.assertEqual(1, self.result())

    def test_missing_tree_fails_closed(self):
        (self.directory / "target/runtime-dependencies.json").unlink()
        self.assertEqual(2, self.result())

    def test_wrong_tree_identity_fails(self):
        (self.directory / "target/runtime-dependencies.json").write_text(
            json.dumps({"artifactId": "wrong", "children": []}), encoding="utf-8")
        self.assertEqual(1, self.result())


if __name__ == "__main__":
    unittest.main()
