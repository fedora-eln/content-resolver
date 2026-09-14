#!/usr/bin/env python3
"""
Check CDN dependencies in templates/layout.html.

Versions live only in HTML. Compatibility is resolved dynamically from npm
metadata across the full deployed stack.
"""

from __future__ import annotations

import re
import sys
import traceback
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import requests
from bs4 import BeautifulSoup

NPM_REGISTRY_HOST = "https://registry.npmjs.org"


class StackResolver:
    """Resolve mutually-compatible CDN package versions from npm metadata.

    Versions are read from HTML only. Compatibility is derived dynamically from each
    package's peerDependencies, dependencies, and devDependencies.
    """

    CONSTRAINT_FIELDS = (
        ("peerDependencies", "requires peer"),
        ("dependencies", "depends on"),
        ("devDependencies", "is tested/developed with"),
    )

    def __init__(self, registry_host: str = NPM_REGISTRY_HOST) -> None:
        """Initialize resolver with npm registry host and empty caches."""
        self.registry_host = registry_host
        self._package_metadata_cache = {}
        self._package_index_cache = {}
        self._stable_versions_cache = {}

    # --- Semver helpers ---

    @staticmethod
    def parse_version(version: str) -> Tuple[int, int, int]:
        """Parse a semantic version string to a tuple for comparison."""
        try:
            parts = version.split(".")
            return (
                int(parts[0]),
                int(parts[1]),
                int(parts[2]) if len(parts) > 2 else 0,
            )
        except (ValueError, IndexError):
            return 0, 0, 0

    @classmethod
    def version_compare(cls, v1: str, v2: str) -> int:
        """Compare two versions. Returns -1, 0, or 1."""
        t1 = cls.parse_version(v1)
        t2 = cls.parse_version(v2)
        if t1 < t2:
            return -1
        if t1 > t2:
            return 1
        return 0

    @classmethod
    def check_semver_constraint(cls, version: str, constraint: str) -> bool:
        """Check whether a version satisfies an npm semver constraint."""
        constraint = constraint.strip()

        if constraint == "*":
            return True

        if " - " in constraint:
            parts = constraint.split(" - ")
            if len(parts) == 2:
                min_ver = parts[0].strip()
                max_ver = parts[1].strip()
                if "." not in max_ver:
                    max_major = int(max_ver)
                    return (
                        cls.version_compare(version, min_ver) >= 0
                        and cls.parse_version(version)[0] <= max_major
                    )
                return (
                    cls.version_compare(version, min_ver)
                    >= 0
                    >= cls.version_compare(version, max_ver)
                )

        if constraint.startswith("^"):
            target = constraint[1:]
            target_parts = cls.parse_version(target)
            version_parts = cls.parse_version(version)
            if target_parts[0] > 0:
                return (
                    version_parts[0] == target_parts[0]
                    and cls.version_compare(version, target) >= 0
                )
            return (
                version_parts[0] == target_parts[0]
                and version_parts[1] == target_parts[1]
                and cls.version_compare(version, target) >= 0
            )

        if constraint.startswith("~"):
            target = constraint[1:]
            target_parts = cls.parse_version(target)
            version_parts = cls.parse_version(version)
            return (
                version_parts[0] == target_parts[0]
                and version_parts[1] == target_parts[1]
                and cls.version_compare(version, target) >= 0
            )

        for op in (">=", "<=", ">", "<"):
            if constraint.startswith(op):
                target = constraint[len(op):].strip()
                cmp = cls.version_compare(version, target)
                if op == ">=":
                    return cmp >= 0
                elif op == "<=":
                    return cmp <= 0
                elif op == ">":
                    return cmp > 0
                elif op == "<":
                    return cmp < 0

        return version == constraint

    # --- npm registry ---

    def get_package_index(self, package_name: str) -> Optional[Dict]:
        """Fetch the full npm registry index for a package (one request per package).

        The index contains all version metadata under index["versions"][ver], so
        get_package_metadata and get_latest_version read from this cache rather than
        making additional requests.
        """
        if package_name in self._package_index_cache:
            return self._package_index_cache[package_name]

        url = f"{self.registry_host}/{package_name}"
        try:
            response = requests.get(url, timeout=10)
            response.raise_for_status()
            data = response.json()
            self._package_index_cache[package_name] = data
            return data
        except Exception as e:
            print(
                f"Error fetching package index for {package_name}: {e}",
                file=sys.stderr,
            )
            return None

    def get_package_metadata(self, package_name: str, version: str) -> Optional[Dict]:
        """Return metadata for a specific package version.

        Reads from the index cache (populated by get_all_stable_versions) so no
        extra HTTP request is needed when the index is already loaded.
        """
        cache_key = f"{package_name}@{version}"
        if cache_key in self._package_metadata_cache:
            return self._package_metadata_cache[cache_key]

        # Use already-cached index data if available
        index = self._package_index_cache.get(package_name)
        if index:
            data = index.get("versions", {}).get(version)
            if data:
                self._package_metadata_cache[cache_key] = data
                return data

        # Fall back to a dedicated per-version request (e.g. index not yet loaded)
        url = f"{self.registry_host}/{package_name}/{version}"
        try:
            response = requests.get(url, timeout=10)
            response.raise_for_status()
            data = response.json()
            self._package_metadata_cache[cache_key] = data
            return data
        except Exception as e:
            print(
                f"  Warning: Could not fetch metadata for {package_name}@{version}: "
                f"{type(e).__name__}",
                file=sys.stderr,
            )
            return None

    def get_latest_version(self, package_name: str) -> str:
        """Return the npm `latest` dist-tag version for a package.

        Reads from the index cache so no extra HTTP request is needed after
        get_all_stable_versions has already fetched the index.
        """
        index = self._package_index_cache.get(package_name)
        if index:
            return index.get("dist-tags", {}).get("latest", "unknown")

        # Fall back to a dedicated /latest request if the index is not cached
        url = f"{self.registry_host}/{package_name}/latest"
        try:
            response = requests.get(url, timeout=10)
            response.raise_for_status()
            return response.json().get("version", "unknown")
        except Exception as e:
            print(f"Error fetching {package_name}: {e}", file=sys.stderr)
            return "unknown"

    def get_all_stable_versions(self, package_name: str) -> List[str]:
        """Return all stable semver releases for a package, highest first."""
        if package_name in self._stable_versions_cache:
            return self._stable_versions_cache[package_name]

        index = self.get_package_index(package_name)
        if not index:
            return []

        versions = [
            v
            for v in index.get("versions", {}).keys()
            if re.match(r"^\d+\.\d+\.\d+$", v)
        ]
        versions.sort(key=lambda v: self.parse_version(v), reverse=True)
        self._stable_versions_cache[package_name] = versions
        return versions

    # --- Stack compatibility ---

    @staticmethod
    def normalize_package_name(name: str) -> str:
        """Normalize a package name for fuzzy cross-reference matching."""
        return re.sub(r"[^a-z0-9]", "", name.lower())

    def package_names_match(self, declared_name: str, stack_package: str) -> bool:
        """Return True if two package names refer to the same npm package."""
        declared = self.normalize_package_name(declared_name)
        stack = self.normalize_package_name(stack_package)
        if not declared or not stack:
            return False
        return declared == stack or declared in stack or stack in declared

    @staticmethod
    def is_ranged_constraint(constraint: str) -> bool:
        """Return True if a constraint is a range (^, ~, >=, etc.) rather than an exact pin."""
        constraint = constraint.strip()
        if constraint in ("*", "latest"):
            return True
        return (
            constraint.startswith(("^", "~", ">=", "<=", ">", "<"))
            or " - " in constraint
        )

    def find_constraint_violation(
        self,
        from_pkg: str,
        from_version: str,
        to_pkg: str,
        to_version: str,
    ) -> Optional[Dict]:
        """Return violation details if from_pkg@from_version rejects to_pkg@to_version."""
        metadata = self.get_package_metadata(from_pkg, from_version)
        if not metadata:
            return None

        for field, label in self.CONSTRAINT_FIELDS:
            for dep_name, constraint in (metadata.get(field) or {}).items():
                if not self.package_names_match(dep_name, to_pkg):
                    continue
                if field == "devDependencies" and not self.is_ranged_constraint(
                    constraint
                ):
                    continue
                if not self.check_semver_constraint(to_version, constraint):
                    return {
                        "from_package": from_pkg,
                        "from_version": from_version,
                        "to_package": to_pkg,
                        "to_version": to_version,
                        "constraint": constraint,
                        "field": field,
                        "reason": (
                            f"{from_pkg}@{from_version} {label} {dep_name} {constraint}, "
                            f"but {to_pkg}@{to_version} does not satisfy this"
                        ),
                    }
        return None

    def find_stack_incompatibility(self, stack: Dict[str, str]) -> Optional[Dict]:
        """Return the first constraint violation found across all pairs in the stack."""
        for from_pkg, from_version in stack.items():
            for to_pkg, to_version in stack.items():
                if from_pkg == to_pkg:
                    continue
                violation = self.find_constraint_violation(
                    from_pkg, from_version, to_pkg, to_version
                )
                if violation:
                    return violation
        return None

    def is_stack_compatible(self, stack: Dict[str, str]) -> bool:
        """Return True if every package version in the stack satisfies all constraints."""
        return self.find_stack_incompatibility(stack) is None

    def find_max_compatible_version(
        self, package: str, deployed: Dict[str, str]
    ) -> str:
        """Return the highest npm version of package compatible with the deployed stack."""
        current = deployed[package]
        for version in self.get_all_stable_versions(package):
            trial_stack = {**deployed, package: version}
            if self.is_stack_compatible(trial_stack):
                return version
        return current

    def analyze_deployed_stack(
        self,
        deployed: Dict[str, str],
        cdn_urls: Dict[str, List[str]],
    ) -> List[Dict]:
        """Classify each deployed package against max-compatible and npm latest versions."""
        results = []

        for package, current in deployed.items():
            max_compatible = self.find_max_compatible_version(package, deployed)
            npm_latest = self.get_latest_version(package)
            urls = cdn_urls.get(package, [])

            result = {
                "package": package,
                "current": current,
                "max_compatible": max_compatible,
                "npm_latest": npm_latest,
                "urls": urls,
                "status": "up_to_date",
                "violation": None,
            }

            if self.version_compare(current, max_compatible) < 0:
                if (
                    self.parse_version(max_compatible)[0]
                    > self.parse_version(current)[0]
                ):
                    result["status"] = "compatible_major_update"
                else:
                    result["status"] = "within_major_update"
            elif (
                npm_latest != "unknown"
                and self.version_compare(npm_latest, max_compatible) > 0
            ):
                trial_stack = {**deployed, package: npm_latest}
                result["status"] = "blocked_major"
                result["violation"] = self.find_stack_incompatibility(trial_stack)

            results.append(result)

        return results


class LayoutParser:
    """Parse CDN package versions and URLs from layout HTML."""


    # NOTE: If deps change in HTML, they need to be udated here too
    PACKAGE_MATCHERS = (
        ("bootstrap", "bootstrap"),
        ("datatables", "datatables.net"),
        ("jquery", "jquery"),
        ("chart.js", "chart.js"),
        ("axios", "axios"),
    )

    @staticmethod
    def extract_version_from_url(url: str, package_name: str) -> Optional[str]:
        """Extract a semver version string from a CDN URL for the given package."""
        patterns = [
            rf"{package_name}@(\d+\.\d+\.\d+)",
            rf"{package_name}[/-](\d+\.\d+\.\d+)",
            rf"{package_name}\.js[/@](\d+\.\d+\.\d+)",
            r"bootstrap(?:cdn)?/(?:bootstrap/)?(\d+\.\d+\.\d+)",
            r"datatables\.net[@/](\d+\.\d+\.\d+)",
        ]

        for pattern in patterns:
            match = re.search(pattern, url, re.IGNORECASE)
            if match:
                return match.group(1)
        return None

    def parse(self, file_path: str) -> Tuple[Dict[str, str], Dict[str, List[str]]]:
        """
        Parse layout.html and return deployed versions and CDN URLs.

        Returns:
            versions: package_name -> version
            urls: package_name -> list of CDN URLs
        """
        with open(file_path, "r", encoding="utf-8") as f:
            soup = BeautifulSoup(f.read(), "html.parser")

        versions: Dict[str, str] = {}
        urls: Dict[str, List[str]] = {}

        cdn_tags = []
        cdn_tags.extend(soup.find_all("script", src=True))
        cdn_tags.extend(soup.find_all("link", href=True))

        for tag in cdn_tags:
            url = tag.get("src") or tag.get("href")
            if not url:
                continue

            url_lower = url.lower()
            for url_fragment, package_name in self.PACKAGE_MATCHERS:
                if url_fragment not in url_lower:
                    continue

                version = self.extract_version_from_url(
                    url, url_fragment.replace(".js", "")
                )
                if not version and url_fragment == "chart.js":
                    version = self.extract_version_from_url(url, "chart")
                if not version:
                    continue

                if package_name not in versions:
                    versions[package_name] = version
                    urls[package_name] = []
                urls[package_name].append(url)
                break

        return versions, urls


class LtsPolicy:
    """Run LTS-style CDN checks: versions from HTML, compatibility from npm."""

    def __init__(
        self,
        resolver: Optional[StackResolver] = None,
        parser: Optional[LayoutParser] = None,
        *,
        verbose: bool = False,
        report_path: str = "cdn-update-report.md",
    ) -> None:
        """Configure resolver, parser, and report output options."""
        self.resolver = resolver or StackResolver()
        self.parser = parser or LayoutParser()
        self.verbose = verbose
        self.report_path = report_path

    def _print_result(self, result: Dict) -> None:
        """Print a single package check result to stdout."""
        package = result["package"]
        current = result["current"]
        max_compatible = result["max_compatible"]
        npm_latest = result["npm_latest"]
        status = result["status"]
        violation = result["violation"]

        if status == "compatible_major_update":
            print(
                f"  🔶  {package}: {current} → {max_compatible} "
                f"(compatible major upgrade available; npm latest {npm_latest})"
            )
        elif status == "within_major_update":
            major = self.resolver.parse_version(current)[0]
            print(
                f"  ℹ️   {package}: {current} → {max_compatible} "
                f"(update within compatible {major}.x; optional only)"
            )
        elif status == "blocked_major":
            conflict = violation["from_package"] if violation else package
            conflict_ver = violation["from_version"] if violation else "unknown"
            print(
                f"  ✅  {package}: {current} (max compatible {max_compatible}; "
                f"npm latest {npm_latest} blocked by {conflict} {conflict_ver})"
            )
            if violation:
                print(f"       ↳ {violation['reason']}")
        else:
            print(f"  ✅  {package}: {current} (max compatible for current stack)")

    def generate_within_major_report(self, updates: List[Dict]) -> str:
        """Build a Markdown report for optional within-major compatible updates."""
        report = "# ℹ️ Compatible Updates Within Current Major (Manual)\n\n"
        report += (
            "These updates are compatible with the full deployed stack in "
            "`templates/layout.html` but are not raised as GitHub issues.\n\n"
        )
        report += "| Package | Current | Max Compatible |\n"
        report += "|---------|---------|----------------|\n"
        for item in updates:
            report += f"| `{item['package']}` | {item['current']} | {item['max_compatible']} |\n"
        report += "\n"
        return report

    def generate_compatible_major_report(self, updates: List[Dict]) -> str:
        """Build a Markdown report for compatible major upgrades (triggers GitHub issue)."""
        report = "# 🔶 Compatible Major Version Updates Available\n\n"
        report += (
            "A newer major version is available and compatible with the rest of the "
            "deployed stack.\n\n"
        )
        report += "| Package | Current | Max Compatible | npm Latest |\n"
        report += "|---------|---------|----------------|------------|\n"
        for item in updates:
            report += (
                f"| `{item['package']}` | {item['current']} | **{item['max_compatible']}** "
                f"| {item['npm_latest']} |\n"
            )
        report += "\n### Next Steps\n\n"
        report += "1. Update `templates/layout.html` with new URLs and SRI hashes\n"
        report += "2. Test all pages locally\n\n"
        return report

    def generate_blocked_major_report(self, updates: List[Dict]) -> str:
        """Build a markdown report for npm releases blocked by stack incompatibility."""
        report = "# ⚠️ Incompatible npm Releases (No Action Needed)\n\n"
        report += (
            "npm publishes newer versions that are **not compatible** with the current "
            "deployed stack. The versions in `templates/layout.html` are already at the "
            "maximum mutually-compatible release.\n\n"
        )
        report += "| Package | Deployed | Max Compatible | npm Latest | Blocked By |\n"
        report += "|---------|----------|----------------|------------|------------|\n"
        for item in updates:
            violation = item["violation"] or {}
            blocker = violation.get("from_package", "—")
            blocker_ver = violation.get("from_version", "—")
            report += (
                f"| `{item['package']}` | {item['current']} | {item['max_compatible']} "
                f"| ~~{item['npm_latest']}~~ | `{blocker}` {blocker_ver} |\n"
            )
        report += "\n### Details\n\n"
        for item in updates:
            if item["violation"]:
                report += f"#### {item['package']}\n\n"
                report += f"❌ {item['violation']['reason']}\n\n"
        return report

    def _write_report(self, content: str) -> None:
        """Write report content to self.report_path."""
        with open(self.report_path, "w", encoding="utf-8") as f:
            f.write(content)

    def run(self, layout_file: str) -> int:
        """
        Run dynamic stack-aware CDN dependency check.

        Exit codes:
            0 - stack is at max compatible versions (or only manual/blocked updates)
            1 - compatible major upgrade available (create GitHub issue)
        """
        print(
            "Checking CDN dependencies (versions from HTML, compatibility from npm)...\n"
        )

        deployed, cdn_urls = self.parser.parse(layout_file)
        print(f"Found {len(deployed)} dependencies in {layout_file}\n")
        print("  Resolving max mutually-compatible versions from npm metadata...\n")

        results = self.resolver.analyze_deployed_stack(deployed, cdn_urls)

        for result in results:
            self._print_result(result)

        within_major = [r for r in results if r["status"] == "within_major_update"]
        compatible_major = [
            r for r in results if r["status"] == "compatible_major_update"
        ]
        blocked_major = [r for r in results if r["status"] == "blocked_major"]

        print(f"\n{'=' * 60}")

        if compatible_major:
            print(f"Found {len(compatible_major)} compatible major upgrade(s)")
            self._write_report(self.generate_compatible_major_report(compatible_major))
            print(f"Report written to {self.report_path}")
            return 1

        if self.verbose and (within_major or blocked_major):
            sections = []
            if within_major:
                sections.append(self.generate_within_major_report(within_major))
            if blocked_major:
                sections.append(self.generate_blocked_major_report(blocked_major))
            self._write_report("\n".join(sections))
            print(f"Verbose report written to {self.report_path}")
        elif within_major:
            print(f"{len(within_major)} within-major update(s) available (manual only)")
        elif blocked_major:
            print(
                f"{len(blocked_major)} incompatible newer release(s) on npm (no issue)"
            )

        print("Stack is at maximum mutually-compatible versions.")
        return 0


def main() -> None:
    """CLI entry point: parse args and run the CDN dependency check."""

    layout_file = "templates/layout.html"
    verbose = "--verbose" in sys.argv
    policy = LtsPolicy(verbose=verbose)
    result=policy.run(layout_file)
    sys.exit(result)


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print("\n❌ Error: Unhandled exception in CDN update check", file=sys.stderr)
        print(f"   {type(e).__name__}: {e}", file=sys.stderr)
        traceback.print_exc()
        sys.exit(3)  # Exit with distinct error code for unhandled exceptions
