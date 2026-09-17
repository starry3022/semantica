"""Explicit, versioned source material snapshots for the Explorer.

Only trusted server setup can register text or files. HTTP clients resolve graph
identities; source IDs and source URIs are never interpreted as file paths or URLs.
"""

import hashlib
import json
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


@dataclass(frozen=True)
class SourceResource:
    source_id: str
    sha256: str
    text: str
    title: Optional[str] = None
    version: Optional[str] = None
    source_uri: Optional[str] = None


class SourceResourceRegistry:
    """Keep exact UTF-8 text snapshots indexed by source identity and digest."""

    def __init__(self) -> None:
        self._resources: dict[str, dict[str, SourceResource]] = {}
        self._unavailable: set[str] = set()
        self._lock = threading.RLock()

    def register_text(
        self,
        source_id: str,
        text: str,
        *,
        title: Optional[str] = None,
        version: Optional[str] = None,
        source_uri: Optional[str] = None,
    ) -> str:
        """Register an immutable material revision; return its computed SHA-256."""
        source_id = self._validate_metadata(source_id, title, version, source_uri)
        if not isinstance(text, str):
            raise ValueError("Source text must be a UTF-8 string.")
        digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
        resource = SourceResource(source_id, digest, text, title, version, source_uri)
        with self._lock:
            self._resources.setdefault(source_id, {})[digest] = resource
        return digest

    def register_file(self, source_id: str, path: Path, **metadata) -> str:
        """Read a trusted local file once, without newline normalization."""
        return self.register_text(
            source_id, Path(path).read_bytes().decode("utf-8"), **metadata
        )

    @staticmethod
    def _validate_metadata(source_id, title, version, source_uri) -> str:
        if not isinstance(source_id, str) or not source_id.strip():
            raise ValueError("A source_id must be a non-empty string.")
        for value in (title, version, source_uri):
            if value is not None and not isinstance(value, str):
                raise ValueError("Source metadata must be strings or null.")
        return source_id

    @classmethod
    def from_manifest(cls, manifest_path: Path) -> "SourceResourceRegistry":
        """Load ``{sources: [{source_id, path, title?, version?, source_uri?}]}``.

        Paths must stay inside the manifest directory, including after symlink
        resolution. Missing/unreadable UTF-8 resources remain explicit empty
        states. Unsafe paths and malformed manifests reject configuration.
        """
        manifest_path = Path(manifest_path).resolve()
        document = json.loads(manifest_path.read_bytes().decode("utf-8"))
        if not isinstance(document, dict) or not isinstance(
            document.get("sources"), list
        ):
            raise ValueError("Source manifest must contain a sources list.")
        resources = cls()
        root = manifest_path.parent
        for entry in document["sources"]:
            if not isinstance(entry, dict):
                raise ValueError("Source manifest entries must be objects.")
            source_id = entry.get("source_id")
            metadata = {
                key: entry.get(key) for key in ("title", "version", "source_uri")
            }
            source_id = cls._validate_metadata(source_id, **metadata)
            raw_path = entry.get("path")
            if (
                not isinstance(raw_path, str)
                or not raw_path
                or "\\" in raw_path
                or ":" in raw_path
                or "\x00" in raw_path
                or Path(raw_path).is_absolute()
                or ".." in Path(raw_path).parts
            ):
                raise ValueError(
                    "Source paths must be relative to the manifest directory."
                )
            path = (root / raw_path).resolve()
            if not path.is_relative_to(root):
                raise ValueError("Source path escapes the manifest directory.")
            try:
                resources.register_file(source_id, path, **metadata)
            except (OSError, UnicodeError):
                # Without file bytes, metadata cannot be bound to a revision.
                resources._unavailable.add(source_id)
        return resources

    def read(self, source_id: Optional[str], source_sha256: Optional[str]) -> dict:
        """Resolve only the requested revision, never a guessed/latest source."""
        result: dict = {
            "source_id": source_id,
            "source_sha256": source_sha256,
            "actual_sha256": None,
            "title": None,
            "version": None,
            "source_uri": None,
            "status": "source_missing",
            "reason": "No original material is registered for this source identity.",
            "text": None,
            "character_count": None,
        }
        if not isinstance(source_id, str) or not isinstance(source_sha256, str):
            result["reason"] = "Source identity or SHA-256 is missing or invalid."
            return result
        with self._lock:
            versions = self._resources.get(source_id, {})
            resource = versions.get(source_sha256)
            if resource is not None:
                result.update(
                    actual_sha256=resource.sha256,
                    title=resource.title,
                    version=resource.version,
                    source_uri=resource.source_uri,
                    status="available",
                    reason=None,
                    text=resource.text,
                    character_count=len(resource.text),
                )
            elif versions:
                result.update(
                    status="hash_mismatch",
                    reason="Registered material does not match the requested SHA-256.",
                )
                if len(versions) == 1:
                    result["actual_sha256"] = next(iter(versions))
            elif source_id in self._unavailable:
                result[
                    "reason"
                ] = "The registered material file is missing or is not readable UTF-8."
        return result
