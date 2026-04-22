# -*- coding: utf-8 -*-
"""
Knowledge Source Service
Scans network drives for documents and manages knowledge sources
"""
import os
from pathlib import Path
from typing import List, Dict, Any, Optional
from datetime import datetime

from app.core.config import settings


class KnowledgeSourceService:
    """Service for scanning and managing knowledge sources"""

    SUPPORTED_EXTENSIONS = {
        ".pdf": "PDF Document",
        ".docx": "Word Document",
        ".doc": "Word Document (Legacy)",
        ".pptx": "PowerPoint",
        ".ppt": "PowerPoint (Legacy)",
        ".xlsx": "Excel Spreadsheet",
        ".xls": "Excel Spreadsheet (Legacy)",
        ".hwp": "HWP Document",
        ".hwpx": "HWPX Document",
    }

    def __init__(self, root_path: Optional[str] = None):
        """
        Initialize knowledge source service

        Args:
            root_path: Root path to scan (defaults to settings)
        """
        if root_path:
            self.root_path = root_path
        else:
            # Try mapped drive first, then UNC path
            if os.path.exists(settings.knowledge_source_root):
                self.root_path = settings.knowledge_source_root
            elif hasattr(settings, 'knowledge_source_unc') and os.path.exists(settings.knowledge_source_unc):
                self.root_path = settings.knowledge_source_unc
            else:
                self.root_path = settings.knowledge_source_root

    def get_root_path(self) -> str:
        """Get the configured root path"""
        return self.root_path

    def is_accessible(self) -> bool:
        """Check if the root path is accessible"""
        try:
            return os.path.exists(self.root_path) and os.path.isdir(self.root_path)
        except Exception:
            return False

    def list_folders(self, subpath: str = "") -> List[Dict[str, Any]]:
        """
        List folders in the knowledge source

        Args:
            subpath: Subpath relative to root

        Returns:
            List of folder information
        """
        target_path = os.path.join(self.root_path, subpath) if subpath else self.root_path
        folders = []

        try:
            if not os.path.exists(target_path):
                return folders

            for item in os.listdir(target_path):
                item_path = os.path.join(target_path, item)
                if os.path.isdir(item_path):
                    try:
                        # Get folder stats
                        stat = os.stat(item_path)
                        folders.append({
                            "name": item,
                            "path": os.path.join(subpath, item) if subpath else item,
                            "full_path": item_path,
                            "modified": datetime.fromtimestamp(stat.st_mtime).isoformat(),
                        })
                    except (OSError, PermissionError):
                        # Skip folders we can't access
                        pass

            # Sort by name
            folders.sort(key=lambda x: x["name"])
            return folders

        except Exception as e:
            print(f"Error listing folders: {e}")
            return folders

    def scan_folder(
        self,
        subpath: str = "",
        recursive: bool = False,
        max_depth: int = 3
    ) -> Dict[str, Any]:
        """
        Scan a folder for supported documents

        Args:
            subpath: Subpath relative to root
            recursive: Whether to scan subdirectories
            max_depth: Maximum recursion depth

        Returns:
            Scan results with file information
        """
        target_path = os.path.join(self.root_path, subpath) if subpath else self.root_path
        results = {
            "path": subpath or "/",
            "full_path": target_path,
            "files": [],
            "folders": [],
            "summary": {
                "total_files": 0,
                "total_folders": 0,
                "by_type": {}
            }
        }

        self._scan_recursive(target_path, results, recursive, max_depth, 0)

        # Build summary
        results["summary"]["total_files"] = len(results["files"])
        results["summary"]["total_folders"] = len(results["folders"])

        for file_info in results["files"]:
            ext = file_info["extension"]
            if ext not in results["summary"]["by_type"]:
                results["summary"]["by_type"][ext] = 0
            results["summary"]["by_type"][ext] += 1

        return results

    def _scan_recursive(
        self,
        path: str,
        results: Dict[str, Any],
        recursive: bool,
        max_depth: int,
        current_depth: int
    ):
        """Recursively scan directories"""
        try:
            for item in os.listdir(path):
                item_path = os.path.join(path, item)

                try:
                    if os.path.isfile(item_path):
                        ext = os.path.splitext(item)[1].lower()
                        if ext in self.SUPPORTED_EXTENSIONS:
                            stat = os.stat(item_path)
                            results["files"].append({
                                "name": item,
                                "path": item_path,
                                "relative_path": os.path.relpath(item_path, self.root_path),
                                "extension": ext,
                                "type": self.SUPPORTED_EXTENSIONS[ext],
                                "size": stat.st_size,
                                "modified": datetime.fromtimestamp(stat.st_mtime).isoformat(),
                            })

                    elif os.path.isdir(item_path) and recursive and current_depth < max_depth:
                        results["folders"].append({
                            "name": item,
                            "path": item_path,
                            "relative_path": os.path.relpath(item_path, self.root_path),
                        })
                        self._scan_recursive(
                            item_path, results, recursive, max_depth, current_depth + 1
                        )

                except (OSError, PermissionError):
                    # Skip files/folders we can't access
                    pass

        except (OSError, PermissionError) as e:
            print(f"Error accessing {path}: {e}")

    def get_file_info(self, relative_path: str) -> Optional[Dict[str, Any]]:
        """
        Get detailed information about a specific file

        Args:
            relative_path: Path relative to root

        Returns:
            File information or None if not found
        """
        full_path = os.path.join(self.root_path, relative_path)

        if not os.path.exists(full_path) or not os.path.isfile(full_path):
            return None

        try:
            stat = os.stat(full_path)
            ext = os.path.splitext(full_path)[1].lower()

            return {
                "name": os.path.basename(full_path),
                "path": full_path,
                "relative_path": relative_path,
                "extension": ext,
                "type": self.SUPPORTED_EXTENSIONS.get(ext, "Unknown"),
                "size": stat.st_size,
                "size_human": self._format_size(stat.st_size),
                "created": datetime.fromtimestamp(stat.st_ctime).isoformat(),
                "modified": datetime.fromtimestamp(stat.st_mtime).isoformat(),
                "accessible": True
            }
        except Exception as e:
            return {
                "path": full_path,
                "error": str(e),
                "accessible": False
            }

    def search_files(
        self,
        query: str,
        subpath: str = "",
        extensions: Optional[List[str]] = None,
        max_results: int = 100
    ) -> List[Dict[str, Any]]:
        """
        Search for files by name

        Args:
            query: Search query (case-insensitive)
            subpath: Subpath to search in
            extensions: Filter by extensions
            max_results: Maximum results to return

        Returns:
            List of matching files
        """
        results = []
        query_lower = query.lower()
        target_path = os.path.join(self.root_path, subpath) if subpath else self.root_path

        def search_recursive(path: str):
            if len(results) >= max_results:
                return

            try:
                for item in os.listdir(path):
                    if len(results) >= max_results:
                        return

                    item_path = os.path.join(path, item)

                    try:
                        if os.path.isfile(item_path):
                            ext = os.path.splitext(item)[1].lower()
                            if ext in self.SUPPORTED_EXTENSIONS:
                                if extensions and ext not in extensions:
                                    continue
                                if query_lower in item.lower():
                                    stat = os.stat(item_path)
                                    results.append({
                                        "name": item,
                                        "path": item_path,
                                        "relative_path": os.path.relpath(item_path, self.root_path),
                                        "extension": ext,
                                        "type": self.SUPPORTED_EXTENSIONS[ext],
                                        "size": stat.st_size,
                                        "modified": datetime.fromtimestamp(stat.st_mtime).isoformat(),
                                    })

                        elif os.path.isdir(item_path):
                            search_recursive(item_path)

                    except (OSError, PermissionError):
                        pass

            except (OSError, PermissionError):
                pass

        search_recursive(target_path)
        return results

    def _format_size(self, size: int) -> str:
        """Format file size in human-readable format"""
        for unit in ["B", "KB", "MB", "GB"]:
            if size < 1024:
                return f"{size:.1f} {unit}"
            size /= 1024
        return f"{size:.1f} TB"

    def get_stats(self) -> Dict[str, Any]:
        """
        Get statistics about the knowledge source

        Returns:
            Statistics dictionary
        """
        scan_result = self.scan_folder(recursive=True, max_depth=5)

        total_size = sum(f["size"] for f in scan_result["files"])

        return {
            "root_path": self.root_path,
            "accessible": self.is_accessible(),
            "total_files": scan_result["summary"]["total_files"],
            "total_folders": scan_result["summary"]["total_folders"],
            "total_size": total_size,
            "total_size_human": self._format_size(total_size),
            "by_type": scan_result["summary"]["by_type"]
        }


# Singleton instance
knowledge_source_service = KnowledgeSourceService()
