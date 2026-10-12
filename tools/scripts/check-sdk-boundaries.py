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

"""Check provider SDK isolation in neutral sources, POMs, trees and bytecode.

Run after Maven compile and dependency:tree with scope=runtime, outputType=json
and outputFile=target/runtime-dependencies.json. Test-only adapter fixtures are
allowed; adapters and their dedicated starters are intentionally not neutral.
The base API must have no non-test dependencies, including inherited ones.
"""

import argparse
import json
import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path


NS = {"m": "http://maven.apache.org/POM/4.0.0"}
BASE_API_MODULE = "argi-api/argi-api-base"
NEUTRAL_MODULES = (
    BASE_API_MODULE,
    "argi-graph-core",
    "argi-agent-framework",
    "argi-studio",
    "argi-spring-boot-starter/argi-starter-builtin-nodes",
    "argi-spring-boot-starter/argi-starter-graph-observation",
)
SDK_PACKAGES = (
    "org.springframework.ai", "dev.langchain4j", "com.google.adk",
    "com.google.genai", "io.agentscope", "io.github.agentic.ai.adapter",
)
SDK_GROUPS = (
    "org.springframework.ai", "dev.langchain4j", "com.google.adk",
    "com.google.genai", "io.agentscope",
)


def prohibited(group, artifact):
    return any(group == prefix or group.startswith(prefix + ".") for prefix in SDK_GROUPS) or (
        group == "io.github.agentic-ai-java" and
        (artifact.startswith("argi-adapter-") or artifact.startswith("argi-starter-adapter-")))


def dependency_nodes(tree):
    for child in tree.get("children", []):
        yield child
        yield from dependency_nodes(child)


def local_poms(directory, root):
    """Include local parent declarations that a direct-POM scan would miss."""
    path = (directory / "pom.xml").resolve()
    visited = set()
    while path.is_relative_to(root) and path.is_file():
        if path in visited:
            raise ValueError(f"Cyclic local POM inheritance: {path.relative_to(root)}")
        visited.add(path)
        pom = ET.parse(path).getroot()
        yield path, pom
        parent = pom.find("m:parent", NS)
        if parent is None:
            break
        relative = parent.findtext("m:relativePath", "../pom.xml", NS)
        if not relative:
            break
        path = (path.parent / relative).resolve()


def check(root, modules=NEUTRAL_MODULES):
    errors = []
    sources = 0
    classes = 0
    dependencies = 0
    pattern = re.compile("|".join(re.escape(prefix) + r"(?:[./]|\b)" for prefix in SDK_PACKAGES))
    for module in modules:
        directory = root / module
        pom = ET.parse(directory / "pom.xml").getroot()
        jdk_only = directory.resolve() == (root / BASE_API_MODULE).resolve()
        for pom_path, declaration in local_poms(directory, root):
            for dependency in declaration.findall("m:dependencies/m:dependency", NS):
                group = dependency.findtext("m:groupId", "", NS)
                artifact = dependency.findtext("m:artifactId", "", NS)
                scope = dependency.findtext("m:scope", "compile", NS)
                location = pom_path.relative_to(root)
                if scope != "test" and jdk_only:
                    errors.append(f"{module}: JDK-only API inherits or declares {scope} dependency "
                                  f"{group}:{artifact} in {location}")
                elif scope != "test" and prohibited(group, artifact):
                    errors.append(f"{module}: {scope} SDK dependency {group}:{artifact} in {location}")
        for source in (directory / "src/main").rglob("*.java"):
            sources += 1
            for number, line in enumerate(source.read_text(encoding="utf-8").splitlines(), 1):
                if pattern.search(line):
                    errors.append(f"{source.relative_to(root)}:{number}: provider SDK reference")
        compiled = list((directory / "target/classes").rglob("*.class"))
        if not compiled:
            errors.append(f"{module}: no compiled classes; run Maven compile first")
        for bytecode in compiled:
            classes += 1
            data = bytecode.read_bytes()
            # JVM constant-pool names include signatures, annotations and method bodies.
            for prefix in SDK_PACKAGES:
                if prefix.encode() in data or prefix.replace(".", "/").encode() in data:
                    errors.append(f"{bytecode.relative_to(root)}: SDK constant-pool reference {prefix}")
        tree_path = directory / "target/runtime-dependencies.json"
        tree = json.loads(tree_path.read_text(encoding="utf-8"))
        expected_artifact = pom.findtext("m:artifactId", "", NS)
        if tree["artifactId"] != expected_artifact:
            errors.append(f"{tree_path.relative_to(root)}: dependency tree belongs to another artifact")
        for dependency in dependency_nodes(tree):
            dependencies += 1
            group = dependency["groupId"]
            artifact = dependency["artifactId"]
            if jdk_only:
                errors.append(f"{module}: JDK-only API resolved external dependency {group}:{artifact}")
            if dependency.get("scope") == "test":
                errors.append(f"{module}: tree contains test dependencies; regenerate with scope=runtime")
            if prohibited(group, artifact):
                errors.append(f"{module}: resolved SDK dependency {group}:{artifact}:{dependency['version']}")
    print(f"Neutral modules: {len(modules)}; sources: {sources}; "
          f"classes: {classes}; resolved dependencies: {dependencies}")
    for error in errors:
        print(error, file=sys.stderr)
    print(f"SDK boundary violations: {len(errors)}")
    return 1 if errors else 0


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument("--module", action="append", help="Check a specific neutral consumer module")
    arguments = parser.parse_args(argv)
    try:
        return check(arguments.root.resolve(), arguments.module or NEUTRAL_MODULES)
    except (OSError, ValueError, KeyError, ET.ParseError) as error:
        print(f"SDK boundary check could not complete: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
