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
import datetime
import json
import re
import socket
import sys
import time
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path


OSV_API = "https://api.osv.dev/v1"
NS = {"m": "http://maven.apache.org/POM/4.0.0"}
SUPPRESSIONS = "tools/ci-config/runtime-dependency-suppressions.json"


def load_suppressions(path, today=None):
    """Require a reviewed, exact package/version waiver with a finite lifetime."""
    today = today or datetime.date.today()
    document = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(document, dict) or set(document) != {"suppressions"} or not isinstance(
            document["suppressions"], list):
        raise ValueError("Suppression file must contain only a suppressions array")
    entries = {}
    fields = {"id", "package", "version", "reason", "issue", "expires"}
    for entry in document["suppressions"]:
        if not isinstance(entry, dict) or set(entry) != fields or any(
                not isinstance(value, str) or not value.strip() for value in entry.values()):
            raise ValueError("Each suppression requires id, package, version, reason, issue and expires")
        if not re.fullmatch(r"[A-Za-z0-9_.-]+:[A-Za-z0-9_.-]+", entry["package"]) or any(
                char in entry["version"] for char in "*[],() "):
            raise ValueError("Suppression package and version must be exact Maven coordinates")
        if not re.fullmatch(r"https://github\.com/[^/\s]+/[^/\s]+/issues/[1-9][0-9]*", entry["issue"]):
            raise ValueError("Suppression issue must link to a GitHub tracking issue")
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", entry["expires"]) or datetime.date.fromisoformat(
                entry["expires"]) <= today:
            raise ValueError(f"Suppression is expired or has an invalid expiry: {entry['id']}")
        key = (entry["id"], entry["package"], entry["version"])
        if key in entries:
            raise ValueError(f"Duplicate suppression: {key}")
        entries[key] = entry
    return entries


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


def audit(root, tree_name, suppression_path=None):
    # Load policy before contacting OSV; an invalid waiver must never bypass the gate.
    suppressions = load_suppressions(suppression_path or root / SUPPRESSIONS)
    modules, packages = collect_packages(root, tree_name)
    matches = query_advisories(packages)
    print(f"Modules: {len(modules)}; external runtime package versions: {len(packages)}")
    blockers = 0
    active = 0
    for identifier, coordinates in sorted(matches.items()):
        advisory = request_json("/vulns/" + identifier)
        if advisory.get("withdrawn"):
            continue
        database_specific = advisory.get("database_specific")
        raw_severity = database_specific.get("severity") if isinstance(database_specific, dict) else None
        severity = raw_severity.strip().upper() if isinstance(raw_severity, str) else "UNKNOWN"
        if severity not in {"LOW", "MODERATE", "MEDIUM", "HIGH", "CRITICAL"}:
            severity = "UNKNOWN"
        active += 1
        waived = [suppressions[(identifier, name, version)] for name, version in sorted(coordinates)
                  if (identifier, name, version) in suppressions]
        unsuppressed = [(name, version) for name, version in sorted(coordinates)
                        if (identifier, name, version) not in suppressions]
        blockers += bool(unsuppressed) and severity in {"HIGH", "CRITICAL", "UNKNOWN"}
        record = {"id": identifier, "severity": severity,
                  "summary": advisory.get("summary", ""),
                  "packages": sorted(coordinates), "unsuppressed_packages": unsuppressed,
                  "suppressions": waived,
                  "modules": sorted(set().union(*(packages[key] for key in coordinates)))}
        print(json.dumps(record, sort_keys=True))
    print(f"Active advisories: {active}; high/critical/unknown blockers: {blockers}")
    return 1 if blockers else 0


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument("--tree-name", default="runtime-dependencies.json")
    parser.add_argument("--suppressions", type=Path, help="Reviewed expiry-dated suppression file")
    arguments = parser.parse_args(argv)
    if Path(arguments.tree_name).name != arguments.tree_name:
        parser.error("--tree-name must be a file name")
    try:
        return audit(arguments.root.resolve(), arguments.tree_name, arguments.suppressions)
    except (OSError, ValueError, KeyError, ET.ParseError) as error:
        print(f"Runtime dependency audit failed: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
