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

"""Audit Maven runtime dependency trees using public coordinates and OSV."""

import argparse
import json
import socket
import sys
import time
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path


OSV_API = "https://api.osv.dev/v1"
NS = {"m": "http://maven.apache.org/POM/4.0.0"}


def request_json(path, payload=None):
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(OSV_API + path, data=data,
                                     headers={"Content-Type": "application/json"})
    for attempt in range(2):
        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                return json.load(response)
        except urllib.error.HTTPError as error:
            if attempt or (error.code != 429 and error.code < 500):
                raise
            time.sleep(20 if error.code == 429 else 2)
        except (urllib.error.URLError, TimeoutError, socket.timeout):
            if attempt:
                raise
            time.sleep(2)


def collect_packages(root, tree_name):
    pom = ET.parse(root / "pom.xml").getroot()
    modules = ["."] + [node.text for node in pom.findall("m:modules/m:module", NS)]
    packages = {}
    for module in modules:
        tree_path = root / module / "target" / tree_name
        tree = json.loads(tree_path.read_text(encoding="utf-8"))
        pending = list(tree.get("children", []))
        while pending:
            dependency = pending.pop()
            pending.extend(dependency.get("children", []))
            group = dependency["groupId"]
            if group == "io.github.agentic-ai-java":
                continue
            coordinate = (group + ":" + dependency["artifactId"], dependency["version"])
            packages.setdefault(coordinate, set()).add(module)
    return modules, packages


def query_advisories(packages):
    matches = {}
    coordinates = sorted(packages)
    for offset in range(0, len(coordinates), 100):
        batch = coordinates[offset:offset + 100]
        queries = [{"package": {"ecosystem": "Maven", "name": name}, "version": version}
                   for name, version in batch]
        results = request_json("/querybatch", {"queries": queries})["results"]
        if len(results) != len(batch):
            raise ValueError("OSV returned an incomplete batch")
        for coordinate, query, result in zip(batch, queries, results):
            seen_tokens = set()
            while True:
                for vulnerability in result.get("vulns", []):
                    matches.setdefault(vulnerability["id"], set()).add(coordinate)
                token = result.get("next_page_token")
                if not token:
                    break
                if token in seen_tokens:
                    raise ValueError("OSV repeated a pagination token")
                seen_tokens.add(token)
                result = request_json("/query", dict(query, page_token=token))
    return matches


def audit(root, tree_name):
    modules, packages = collect_packages(root, tree_name)
    matches = query_advisories(packages)
    print(f"Modules: {len(modules)}; external runtime package versions: {len(packages)}")
    blockers = 0
    active = 0
    for identifier, coordinates in sorted(matches.items()):
        advisory = request_json("/vulns/" + identifier)
        if advisory.get("withdrawn"):
            continue
        severity = advisory.get("database_specific", {}).get("severity", "UNKNOWN").upper()
        active += 1
        blockers += severity in {"HIGH", "CRITICAL", "UNKNOWN"}
        record = {"id": identifier, "severity": severity,
                  "summary": advisory.get("summary", ""),
                  "packages": sorted(coordinates),
                  "modules": sorted(set().union(*(packages[key] for key in coordinates)))}
        print(json.dumps(record, sort_keys=True))
    print(f"Active advisories: {active}; high/critical/unknown blockers: {blockers}")
    return 1 if blockers else 0


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument("--tree-name", default="runtime-dependencies.json")
    arguments = parser.parse_args(argv)
    if Path(arguments.tree_name).name != arguments.tree_name:
        parser.error("--tree-name must be a file name")
    try:
        return audit(arguments.root.resolve(), arguments.tree_name)
    except (OSError, ValueError, KeyError, ET.ParseError) as error:
        print(f"Runtime dependency audit failed: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
