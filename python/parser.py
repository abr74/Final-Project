import csv
import json
import re
import sys
import zipfile
from pathlib import Path
from datetime import datetime, timezone
from html import unescape
from typing import Any, Dict, List, Optional, Union
from urllib.parse import parse_qs, urlparse

from bs4 import BeautifulSoup


class YouTubeTakeoutParser:
    """
    Self-contained parser for Google Takeout exports containing
    YouTube and YouTube Music data.

    Expected folder structure:

        parser.py
        Takeout Collection/
            some_takeout.zip
            another_takeout.zip
            extracted_takeout_folder/

    The parser can:
    - list available takeout sources
    - parse one takeout source by name
    - parse multiple takeout sources
    - parse all takeout sources
    - output per-record-type JSONL files
    - output one central combined JSON file
    """

    def __init__(
        self,
        takeout_collection_dir: Union[str, Path] = "Takeout Collection",
        output_dir: Union[str, Path] = "parsed_output",
    ) -> None:
        self.takeout_collection_dir = Path(takeout_collection_dir)
        self.output_dir = Path(output_dir)

    # ============================================================
    # Public API
    # ============================================================

    def list_takeout_files(self) -> List[str]:
        """
        Return a list of all files/folders inside Takeout Collection
        that look like valid parse targets.
        """
        if not self.takeout_collection_dir.exists():
            return []

        valid: List[str] = []
        for item in sorted(self.takeout_collection_dir.iterdir()):
            if item.is_file() and item.suffix.lower() == ".zip":
                valid.append(item.name)
            elif item.is_dir():
                valid.append(item.name)
        return valid

    def parse(self, targets: Optional[Union[str, List[str]]] = None) -> Dict[str, Any]:
        """
        Parse:
        - None: all available takeout sources
        - str: one source name
        - List[str]: multiple source names
        """
        if targets is None:
            source_names = self.list_takeout_files()
        elif isinstance(targets, str):
            source_names = [targets]
        else:
            source_names = targets

        resolved_sources = [self.takeout_collection_dir / name for name in source_names]

        all_records: List[Dict[str, Any]] = []
        source_summaries: List[Dict[str, Any]] = []

        for source in resolved_sources:
            if not source.exists():
                source_summaries.append(
                    {
                        "source_name": source.name,
                        "source_path": str(source),
                        "status": "missing",
                        "record_count": 0,
                        "counts": {},
                    }
                )
                continue

            try:
                records = self._parse_source(source)
                counts = self._count_records(records)

                source_summaries.append(
                    {
                        "source_name": source.name,
                        "source_path": str(source),
                        "status": "parsed",
                        "record_count": len(records),
                        "counts": counts,
                    }
                )
                all_records.extend(records)

            except Exception as exc:
                source_summaries.append(
                    {
                        "source_name": source.name,
                        "source_path": str(source),
                        "status": "error",
                        "record_count": 0,
                        "counts": {},
                        "error": str(exc),
                    }
                )

        result = {
            "generated_at": self._now_iso(),
            "sources": source_summaries,
            "counts": self._count_records(all_records),
            "all_records": all_records,
        }
        return result

    def write_output(self, result: Dict[str, Any], output_dir: Optional[Union[str, Path]] = None) -> Path:
        """
        Write:
        - central_output.json
        - all_records.jsonl
        - one JSONL per record_type
        - manifest.json
        """
        out_dir = Path(output_dir) if output_dir else self.output_dir
        out_dir.mkdir(parents=True, exist_ok=True)

        central_output_path = out_dir / "central_output.json"
        with central_output_path.open("w", encoding="utf-8") as f:
            json.dump(result, f, indent=2, ensure_ascii=False)

        all_records_path = out_dir / "all_records.jsonl"
        with all_records_path.open("w", encoding="utf-8") as f:
            for record in result.get("all_records", []):
                f.write(json.dumps(record, ensure_ascii=False) + "\n")

        grouped: Dict[str, List[Dict[str, Any]]] = {}
        for record in result.get("all_records", []):
            grouped.setdefault(record.get("record_type", "unknown"), []).append(record)

        for record_type, records in grouped.items():
            file_path = out_dir / f"{record_type}.jsonl"
            with file_path.open("w", encoding="utf-8") as f:
                for record in records:
                    f.write(json.dumps(record, ensure_ascii=False) + "\n")

        manifest = {
            "generated_at": self._now_iso(),
            "output_dir": str(out_dir),
            "files_written": ["central_output.json", "all_records.jsonl"]
            + [f"{record_type}.jsonl" for record_type in sorted(grouped.keys())],
            "counts": result.get("counts", {}),
            "sources": result.get("sources", []),
        }

        manifest_path = out_dir / "manifest.json"
        with manifest_path.open("w", encoding="utf-8") as f:
            json.dump(manifest, f, indent=2, ensure_ascii=False)

        return out_dir

    # ============================================================
    # Recommended schema getter methods
    # ============================================================

    def get_channel_profiles(self, records: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        return [r for r in records if r.get("record_type") == "channel_profile"]

    def get_comments(self, records: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        return [r for r in records if r.get("record_type") == "comment"]

    def get_live_chats(self, records: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        return [r for r in records if r.get("record_type") == "live_chat"]

    def get_subscriptions(self, records: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        return [r for r in records if r.get("record_type") == "subscription"]

    def get_playlists(self, records: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        return [r for r in records if r.get("record_type") == "playlist"]

    def get_playlist_items(self, records: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        return [r for r in records if r.get("record_type") == "playlist_item"]

    def get_uploaded_videos(self, records: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        return [r for r in records if r.get("record_type") == "uploaded_video"]

    def get_watch_history(self, records: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        return [r for r in records if r.get("record_type") == "watch_event"]

    def get_search_history(self, records: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        return [r for r in records if r.get("record_type") == "search_event"]

    def get_media_assets(self, records: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        return [r for r in records if r.get("record_type") == "media_asset"]

    # ============================================================
    # Source parsing
    # ============================================================

    def _parse_source(self, source: Path) -> List[Dict[str, Any]]:
        if source.is_file() and source.suffix.lower() == ".zip":
            return self._parse_zip_source(source)
        if source.is_dir():
            return self._parse_directory_source(source)
        return []

    def _parse_zip_source(self, zip_path: Path) -> List[Dict[str, Any]]:
        records: List[Dict[str, Any]] = []

        with zipfile.ZipFile(zip_path, "r") as zf:
            names = zf.namelist()

            channel_rows = self._read_csv_from_zip(zf, names, "channel.csv")
            channel_url_rows = self._read_csv_from_zip(zf, names, "channel URL configs.csv")
            channel_feature_rows = self._read_csv_from_zip(zf, names, "channel feature data.csv")

            comment_rows = self._read_csv_from_zip(zf, names, "comments/comments.csv")
            subscription_rows = self._read_csv_from_zip(zf, names, "subscriptions/subscriptions.csv")
            playlist_rows = self._read_csv_from_zip(zf, names, "playlists/playlists.csv")
            video_rows = self._read_csv_from_zip(zf, names, "video metadata/videos.csv")
            video_text_rows = self._read_csv_from_zip(zf, names, "video metadata/video texts.csv")
            video_recording_rows = self._read_csv_from_zip(zf, names, "video metadata/video recordings.csv")

            watch_html = self._read_text_from_zip(zf, names, "history/watch-history.html")
            search_html = self._read_text_from_zip(zf, names, "history/search-history.html")

            live_chat_files = [n for n in names if "/live chats/" in n.lower() and n.lower().endswith(".csv")]
            playlist_item_files = [
                n for n in names
                if "/playlists/" in n.lower()
                and n.lower().endswith(".csv")
                and not n.lower().endswith("/playlists.csv")
            ]
            video_files = [n for n in names if "/videos/" in n.lower() and self._is_media_file(n)]

            records.extend(
                self._parse_channel_profiles(
                    channel_rows,
                    channel_url_rows,
                    channel_feature_rows,
                    source_name=zip_path.name,
                )
            )
            records.extend(self._parse_comments(comment_rows, source_name=zip_path.name))
            records.extend(self._parse_subscriptions(subscription_rows, source_name=zip_path.name))
            records.extend(self._parse_playlists(playlist_rows, source_name=zip_path.name))
            records.extend(self._parse_playlist_items_from_zip(zf, playlist_item_files, source_name=zip_path.name))
            records.extend(
                self._parse_uploaded_videos(
                    video_rows,
                    video_text_rows,
                    video_recording_rows,
                    video_files=video_files,
                    source_name=zip_path.name,
                )
            )
            records.extend(self._parse_watch_history(watch_html, source_name=zip_path.name))
            records.extend(self._parse_search_history(search_html, source_name=zip_path.name))
            records.extend(self._parse_live_chats_from_zip(zf, live_chat_files, source_name=zip_path.name))
            records.extend(self._parse_media_assets_from_zip(video_files, zf, source_name=zip_path.name))

        return records

    def _parse_directory_source(self, root_dir: Path) -> List[Dict[str, Any]]:
        records: List[Dict[str, Any]] = []

        all_files = [p for p in root_dir.rglob("*") if p.is_file()]

        def find_file(needle: str) -> Optional[Path]:
            needle_lower = needle.lower().replace("\\", "/")
            for f in all_files:
                path_lower = str(f.relative_to(root_dir)).replace("\\", "/").lower()
                if path_lower.endswith(needle_lower):
                    return f
            return None

        channel_rows = self._read_csv_from_path(find_file("channel.csv"))
        channel_url_rows = self._read_csv_from_path(find_file("channel URL configs.csv"))
        channel_feature_rows = self._read_csv_from_path(find_file("channel feature data.csv"))

        comment_rows = self._read_csv_from_path(find_file("comments/comments.csv"))
        subscription_rows = self._read_csv_from_path(find_file("subscriptions/subscriptions.csv"))
        playlist_rows = self._read_csv_from_path(find_file("playlists/playlists.csv"))
        video_rows = self._read_csv_from_path(find_file("video metadata/videos.csv"))
        video_text_rows = self._read_csv_from_path(find_file("video metadata/video texts.csv"))
        video_recording_rows = self._read_csv_from_path(find_file("video metadata/video recordings.csv"))

        watch_file = find_file("history/watch-history.html")
        search_file = find_file("history/search-history.html")

        watch_html = watch_file.read_text(encoding="utf-8", errors="replace") if watch_file else None
        search_html = search_file.read_text(encoding="utf-8", errors="replace") if search_file else None

        live_chat_files = [
            f for f in all_files if "/live chats/" in str(f.relative_to(root_dir)).replace("\\", "/").lower() and f.suffix.lower() == ".csv"
        ]
        playlist_item_files = [
            f for f in all_files
            if "/playlists/" in str(f.relative_to(root_dir)).replace("\\", "/").lower()
            and f.suffix.lower() == ".csv"
            and f.name.lower() != "playlists.csv"
        ]
        video_files = [
            f for f in all_files
            if "/videos/" in str(f.relative_to(root_dir)).replace("\\", "/").lower() and self._is_media_file(f.name)
        ]

        records.extend(
            self._parse_channel_profiles(
                channel_rows,
                channel_url_rows,
                channel_feature_rows,
                source_name=root_dir.name,
            )
        )
        records.extend(self._parse_comments(comment_rows, source_name=root_dir.name))
        records.extend(self._parse_subscriptions(subscription_rows, source_name=root_dir.name))
        records.extend(self._parse_playlists(playlist_rows, source_name=root_dir.name))
        records.extend(self._parse_playlist_items_from_paths(playlist_item_files, root_dir, source_name=root_dir.name))
        records.extend(
            self._parse_uploaded_videos(
                video_rows,
                video_text_rows,
                video_recording_rows,
                video_files=[str(p.relative_to(root_dir)).replace("\\", "/") for p in video_files],
                source_name=root_dir.name,
            )
        )
        records.extend(self._parse_watch_history(watch_html, source_name=root_dir.name))
        records.extend(self._parse_search_history(search_html, source_name=root_dir.name))
        records.extend(self._parse_live_chats_from_paths(live_chat_files, root_dir, source_name=root_dir.name))
        records.extend(self._parse_media_assets_from_paths(video_files, root_dir, source_name=root_dir.name))

        return records

    # ============================================================
    # Core parsers
    # ============================================================

    def _parse_channel_profiles(
        self,
        channel_rows: List[Dict[str, str]],
        channel_url_rows: List[Dict[str, str]],
        channel_feature_rows: List[Dict[str, str]],
        source_name: str,
    ) -> List[Dict[str, Any]]:
        if not channel_rows and not channel_url_rows and not channel_feature_rows:
            return []

        base = channel_rows[0] if channel_rows else {}
        url_cfg = channel_url_rows[0] if channel_url_rows else {}
        feature = channel_feature_rows[0] if channel_feature_rows else {}

        channel_id = (
            self._first_value(base, ["Channel ID", "channel id", "channel_id"])
            or self._extract_channel_id(self._first_value(url_cfg, ["Channel URL", "channel url"]))
            or self._extract_channel_id(self._first_value(base, ["Channel URL", "channel url"]))
            or "unknown_channel"
        )
        channel_title = self._first_value(base, ["Title", "Channel Title", "Name"]) or "Unknown Channel"

        record = self._base_record(
            record_id=f"channel:{channel_id}",
            record_type="channel_profile",
            source_name=source_name,
            source_path="YouTube and YouTube Music/channels/",
            title=channel_title,
            text=f"YouTube channel profile for {channel_title}.",
            entity_id=channel_id,
            channel_id=channel_id,
            channel_title=channel_title,
            metadata={
                "visibility": self._first_value(base, ["Visibility"]),
                "channel_url": self._first_value(base, ["Channel URL"]) or self._first_value(url_cfg, ["Channel URL"]),
                "vanity_url_name": self._first_value(url_cfg, ["Vanity URL Name", "Vanity URL"]),
                "auto_moderation_live_chat": self._to_bool(
                    self._first_value(feature, ["Auto Moderation in Live Chat"])
                ),
                "default_comments_type": self._first_value(feature, ["Default Comments Setting"]),
                "default_target_audience": self._first_value(feature, ["Default Target Audience"]),
                "default_license": self._first_value(feature, ["Default License"]),
                "default_location_latitude": self._to_number(
                    self._first_value(feature, ["Default Recording Location Latitude"])
                ),
                "default_location_longitude": self._to_number(
                    self._first_value(feature, ["Default Recording Location Longitude"])
                ),
            },
            raw={
                "channel_row": base,
                "channel_url_config_row": url_cfg,
                "channel_feature_row": feature,
            },
        )
        return [record]

    def _parse_comments(self, rows: List[Dict[str, str]], source_name: str) -> List[Dict[str, Any]]:
        records: List[Dict[str, Any]] = []

        for row in rows:
            comment_id = self._first_value(row, ["Comment ID", "CommentId"]) or self._stable_hash(json.dumps(row, sort_keys=True))
            parent_comment_id = self._first_value(row, ["Parent Comment ID"])
            top_level_comment_id = self._first_value(row, ["Top Level Comment ID"])
            channel_id = self._first_value(row, ["Channel ID"])
            video_id = self._first_value(row, ["Video ID"])
            timestamp = self._normalize_datetime(self._first_value(row, ["Time", "Timestamp"]))
            price = self._to_number(self._first_value(row, ["Price"]))
            comment_text_raw = self._first_value(row, ["Comment Text", "Text"]) or ""
            comment_segments = self._parse_serialized_segments(comment_text_raw)
            flat_text = self._segments_to_text(comment_segments) or self._clean_text(comment_text_raw)

            record = self._base_record(
                record_id=f"comment:{comment_id}",
                record_type="comment",
                source_name=source_name,
                source_path="YouTube and YouTube Music/comments/comments.csv",
                timestamp=timestamp,
                text=flat_text,
                entity_id=comment_id,
                video_id=video_id,
                channel_id=channel_id,
                metadata={
                    "comment_id": comment_id,
                    "parent_comment_id": parent_comment_id,
                    "top_level_comment_id": top_level_comment_id,
                    "price": price,
                    "comment_segments": comment_segments,
                },
                raw=row,
            )
            records.append(record)

        return records

    def _parse_live_chats_from_zip(
        self,
        zf: zipfile.ZipFile,
        file_names: List[str],
        source_name: str,
    ) -> List[Dict[str, Any]]:
        records: List[Dict[str, Any]] = []
        for file_name in file_names:
            rows = self._read_csv_fileobj(zf.open(file_name))
            records.extend(self._parse_live_chat_rows(rows, source_name, file_name))
        return records

    def _parse_live_chats_from_paths(
        self,
        file_paths: List[Path],
        root_dir: Path,
        source_name: str,
    ) -> List[Dict[str, Any]]:
        records: List[Dict[str, Any]] = []
        for path in file_paths:
            rows = self._read_csv_from_path(path)
            rel = str(path.relative_to(root_dir)).replace("\\", "/")
            records.extend(self._parse_live_chat_rows(rows, source_name, rel))
        return records

    def _parse_live_chat_rows(
        self,
        rows: List[Dict[str, str]],
        source_name: str,
        source_path: str,
    ) -> List[Dict[str, Any]]:
        records: List[Dict[str, Any]] = []

        for row in rows:
            live_chat_id = self._first_value(row, ["Live Chat Message ID", "Message ID"]) or self._stable_hash(
                json.dumps(row, sort_keys=True)
            )
            channel_id = self._first_value(row, ["Channel ID"])
            video_id = self._first_value(row, ["Video ID"])
            timestamp = self._normalize_datetime(self._first_value(row, ["Time", "Timestamp"]))
            price = self._to_number(self._first_value(row, ["Price"]))
            chat_text_raw = self._first_value(row, ["Message", "Live Chat Text", "Text"]) or ""
            chat_segments = self._parse_serialized_segments(chat_text_raw)
            flat_text = self._segments_to_text(chat_segments) or self._clean_text(chat_text_raw)

            record = self._base_record(
                record_id=f"live_chat:{live_chat_id}",
                record_type="live_chat",
                source_name=source_name,
                source_path=source_path,
                timestamp=timestamp,
                text=flat_text,
                entity_id=live_chat_id,
                video_id=video_id,
                channel_id=channel_id,
                metadata={
                    "live_chat_id": live_chat_id,
                    "price": price,
                    "chat_segments": chat_segments,
                },
                raw=row,
            )
            records.append(record)

        return records

    def _parse_subscriptions(self, rows: List[Dict[str, str]], source_name: str) -> List[Dict[str, Any]]:
        records: List[Dict[str, Any]] = []

        for row in rows:
            channel_url = self._first_value(row, ["Channel URL", "URL"])
            channel_id = self._first_value(row, ["Channel ID"]) or self._extract_channel_id(channel_url) or "unknown_channel"
            channel_title = self._first_value(row, ["Channel Title", "Title", "Name"]) or "Unknown Channel"

            record = self._base_record(
                record_id=f"subscription:{channel_id}",
                record_type="subscription",
                source_name=source_name,
                source_path="YouTube and YouTube Music/subscriptions/subscriptions.csv",
                title=channel_title,
                text=f"Subscribed to {channel_title}.",
                entity_id=channel_id,
                channel_id=channel_id,
                channel_title=channel_title,
                url=channel_url,
                metadata={
                    "subscribed_channel_id": channel_id,
                    "subscribed_channel_title": channel_title,
                    "subscribed_channel_url": channel_url,
                },
                raw=row,
            )
            records.append(record)

        return records

    def _parse_playlists(self, rows: List[Dict[str, str]], source_name: str) -> List[Dict[str, Any]]:
        records: List[Dict[str, Any]] = []

        for row in rows:
            playlist_id = self._first_value(row, ["Playlist Id", "Playlist ID", "PlaylistId"]) or self._stable_hash(
                json.dumps(row, sort_keys=True)
            )
            title = self._first_value(row, ["Title", "Playlist Title"]) or "Untitled Playlist"

            record = self._base_record(
                record_id=f"playlist:{playlist_id}",
                record_type="playlist",
                source_name=source_name,
                source_path="YouTube and YouTube Music/playlists/playlists.csv",
                title=title,
                text=f"Playlist {title}.",
                entity_id=playlist_id,
                playlist_id=playlist_id,
                playlist_title=title,
                created_at=self._normalize_datetime(self._first_value(row, ["Create Timestamp", "Created At"])),
                updated_at=self._normalize_datetime(self._first_value(row, ["Update Timestamp", "Updated At"])),
                metadata={
                    "playlist_id": playlist_id,
                    "title_language": self._first_value(row, ["Title Language"]),
                    "visibility": self._first_value(row, ["Visibility"]),
                    "video_order": self._first_value(row, ["Video Order"]),
                    "add_new_videos_to_top": self._to_bool(self._first_value(row, ["New Videos Added to Top"])),
                    "image_url": self._first_value(row, ["Image URL"]),
                    "image_width": self._to_number(self._first_value(row, ["Image Width"])),
                    "image_height": self._to_number(self._first_value(row, ["Image Height"])),
                },
                raw=row,
            )
            records.append(record)

        return records

    def _parse_playlist_items_from_zip(
        self,
        zf: zipfile.ZipFile,
        file_names: List[str],
        source_name: str,
    ) -> List[Dict[str, Any]]:
        records: List[Dict[str, Any]] = []
        for file_name in file_names:
            rows = self._read_csv_fileobj(zf.open(file_name))
            records.extend(self._parse_playlist_item_rows(rows, source_name, file_name))
        return records

    def _parse_playlist_items_from_paths(
        self,
        file_paths: List[Path],
        root_dir: Path,
        source_name: str,
    ) -> List[Dict[str, Any]]:
        records: List[Dict[str, Any]] = []
        for path in file_paths:
            rows = self._read_csv_from_path(path)
            rel = str(path.relative_to(root_dir)).replace("\\", "/")
            records.extend(self._parse_playlist_item_rows(rows, source_name, rel))
        return records

    def _parse_playlist_item_rows(
        self,
        rows: List[Dict[str, str]],
        source_name: str,
        source_path: str,
    ) -> List[Dict[str, Any]]:
        records: List[Dict[str, Any]] = []

        playlist_title_guess = Path(source_path).stem.replace("-videos", "").strip()

        for row in rows:
            playlist_id = self._first_value(row, ["Playlist Id", "Playlist ID", "PlaylistId"]) or playlist_title_guess
            playlist_title = self._first_value(row, ["Playlist Title", "Title"]) or playlist_title_guess
            video_id = self._first_value(row, ["Video ID", "Video Id", "VideoId"])
            added_at = self._normalize_datetime(self._first_value(row, ["Added At", "Create Timestamp", "Timestamp"]))

            if not video_id:
                video_url = self._first_value(row, ["Video URL", "URL"])
                video_id = self._extract_video_id(video_url)

            item_id = f"playlist_item:{playlist_id}:{video_id or self._stable_hash(json.dumps(row, sort_keys=True))}"

            record = self._base_record(
                record_id=item_id,
                record_type="playlist_item",
                source_name=source_name,
                source_path=source_path,
                timestamp=added_at,
                text=f"Video {video_id or 'unknown_video'} added to playlist {playlist_title}.",
                entity_id=item_id,
                video_id=video_id,
                playlist_id=playlist_id,
                playlist_title=playlist_title,
                metadata={
                    "playlist_id": playlist_id,
                    "playlist_title": playlist_title,
                    "video_id": video_id,
                    "added_at": added_at,
                    "video_title": self._first_value(row, ["Video Title"]),
                    "video_url": self._first_value(row, ["Video URL", "URL"]),
                },
                raw=row,
            )
            records.append(record)

        return records

    def _parse_uploaded_videos(
        self,
        video_rows: List[Dict[str, str]],
        video_text_rows: List[Dict[str, str]],
        video_recording_rows: List[Dict[str, str]],
        video_files: List[str],
        source_name: str,
    ) -> List[Dict[str, Any]]:
        video_text_map: Dict[str, Dict[str, str]] = {}
        video_recording_map: Dict[str, Dict[str, str]] = {}

        for row in video_text_rows:
            vid = self._first_value(row, ["Video ID", "Video Id", "VideoId"])
            if vid:
                video_text_map[vid] = row

        for row in video_recording_rows:
            vid = self._first_value(row, ["Video ID", "Video Id", "VideoId"])
            if vid:
                video_recording_map[vid] = row

        media_map: Dict[str, str] = {}
        for file_path in video_files:
            file_name = Path(file_path).name
            media_map[file_name.lower()] = file_path

        records: List[Dict[str, Any]] = []

        for row in video_rows:
            video_id = self._first_value(row, ["Video ID", "Video Id", "VideoId"]) or self._stable_hash(
                json.dumps(row, sort_keys=True)
            )
            title = self._first_value(row, ["Video Title", "Title"]) or "Untitled Video"
            channel_id = self._first_value(row, ["Channel ID"])
            created_at = self._normalize_datetime(self._first_value(row, ["Create Timestamp", "Created At"]))
            updated_at = self._normalize_datetime(self._first_value(row, ["Update Timestamp", "Updated At"]))

            text_row = video_text_map.get(video_id, {})
            rec_row = video_recording_map.get(video_id, {})

            media_filename = self._first_value(row, ["Video Filename", "Filename", "File Name"])
            if not media_filename:
                possible = f"{title}.mp4".lower()
                media_filename = Path(media_map.get(possible, "")).name if possible in media_map else None

            media_path = None
            if media_filename:
                media_path = media_map.get(media_filename.lower())

            description = self._first_value(text_row, ["Description", "Video Description"])
            record_text = f"Uploaded video titled {title}."
            if description:
                record_text += f" Description: {self._clean_text(description)}"

            record = self._base_record(
                record_id=f"video:{video_id}",
                record_type="uploaded_video",
                source_name=source_name,
                source_path="YouTube and YouTube Music/video metadata/",
                title=title,
                text=record_text,
                entity_id=video_id,
                video_id=video_id,
                channel_id=channel_id,
                created_at=created_at,
                updated_at=updated_at,
                metadata={
                    "video_id": video_id,
                    "video_title_original": title,
                    "video_category": self._first_value(row, ["Video Category", "Category"]),
                    "privacy": self._first_value(row, ["Privacy"]),
                    "video_state": self._first_value(row, ["Video State", "State"]),
                    "duration_ms": self._to_number(self._first_value(row, ["Video Duration", "Duration ms", "Duration"])),
                    "description": description,
                    "tags": self._first_value(text_row, ["Tags"]),
                    "recording_latitude": self._to_number(
                        self._first_value(rec_row, ["Recording Latitude", "Latitude"])
                    ),
                    "recording_longitude": self._to_number(
                        self._first_value(rec_row, ["Recording Longitude", "Longitude"])
                    ),
                    "recording_altitude": self._to_number(
                        self._first_value(rec_row, ["Recording Altitude", "Altitude"])
                    ),
                    "media_filename": media_filename,
                    "media_path": media_path,
                },
                raw={
                    "video_row": row,
                    "video_text_row": text_row,
                    "video_recording_row": rec_row,
                },
            )
            records.append(record)

        return records

    def _parse_watch_history(self, html_text: Optional[str], source_name: str) -> List[Dict[str, Any]]:
        if not html_text:
            return []

        records: List[Dict[str, Any]] = []
        soup = BeautifulSoup(html_text, "html.parser")

        cells = soup.find_all(["div", "li"])
        for cell in cells:
            text = self._clean_text(cell.get_text(" ", strip=True))
            if not text:
                continue

            links = cell.find_all("a")
            if not links:
                continue

            video_url = None
            video_title = None
            channel_url = None
            channel_title = None

            for link in links:
                href = link.get("href", "")
                label = self._clean_text(link.get_text(" ", strip=True))
                if not href:
                    continue
                if ("watch?" in href or "youtu.be/" in href) and not video_url:
                    video_url = href
                    video_title = label
                elif ("/channel/" in href or "/c/" in href or "/@" in href or "/user/" in href) and not channel_url:
                    channel_url = href
                    channel_title = label

            timestamp = self._extract_datetime_from_text(text)
            video_id = self._extract_video_id(video_url)

            if video_url or video_title:
                record = self._base_record(
                    record_id=f"watch_event:{self._stable_hash((video_url or '') + '|' + (timestamp or '') + '|' + text)}",
                    record_type="watch_event",
                    source_name=source_name,
                    source_path="YouTube and YouTube Music/history/watch-history.html",
                    timestamp=timestamp,
                    title=video_title,
                    text=f"Watched {video_title or 'a video'}" + (f" by {channel_title}." if channel_title else "."),
                    url=video_url,
                    entity_id=video_id,
                    video_id=video_id,
                    channel_id=self._extract_channel_id(channel_url),
                    channel_title=channel_title,
                    metadata={
                        "video_url": video_url,
                        "channel_url": channel_url,
                        "raw_text": text,
                    },
                    raw={"html_text": str(cell)},
                )
                records.append(record)

        return records

    def _parse_search_history(self, html_text: Optional[str], source_name: str) -> List[Dict[str, Any]]:
        if not html_text:
            return []

        records: List[Dict[str, Any]] = []
        soup = BeautifulSoup(html_text, "html.parser")

        cells = soup.find_all(["div", "li"])
        for cell in cells:
            text = self._clean_text(cell.get_text(" ", strip=True))
            if not text:
                continue

            links = cell.find_all("a")
            if not links:
                continue

            search_url = None
            query = None
            for link in links:
                href = link.get("href", "")
                label = self._clean_text(link.get_text(" ", strip=True))
                if "search_query=" in href:
                    search_url = href
                    query = label
                    break

            if not search_url and "searched for" not in text.lower():
                continue

            if not query and search_url:
                query = self._extract_search_query(search_url)

            timestamp = self._extract_datetime_from_text(text)

            if query or search_url:
                record = self._base_record(
                    record_id=f"search_event:{self._stable_hash((search_url or '') + '|' + (timestamp or '') + '|' + text)}",
                    record_type="search_event",
                    source_name=source_name,
                    source_path="YouTube and YouTube Music/history/search-history.html",
                    timestamp=timestamp,
                    text=f"Searched YouTube for {query}." if query else "Searched YouTube.",
                    url=search_url,
                    entity_id=self._stable_hash(query or text),
                    metadata={
                        "query": query,
                        "raw_text": text,
                    },
                    raw={"html_text": str(cell)},
                )
                records.append(record)

        return records

    def _parse_media_assets_from_zip(
        self,
        file_names: List[str],
        zf: zipfile.ZipFile,
        source_name: str,
    ) -> List[Dict[str, Any]]:
        records: List[Dict[str, Any]] = []

        for file_name in file_names:
            info = zf.getinfo(file_name)
            filename = Path(file_name).name
            stem = Path(filename).stem

            record = self._base_record(
                record_id=f"media:{self._stable_hash(file_name)}",
                record_type="media_asset",
                source_name=source_name,
                source_path=file_name,
                text=None,
                entity_id=stem,
                metadata={
                    "filename": filename,
                    "path": file_name,
                    "extension": Path(filename).suffix.lower(),
                    "linked_video_id": None,
                    "size_bytes": info.file_size,
                },
                raw={},
            )
            records.append(record)

        return records

    def _parse_media_assets_from_paths(
        self,
        file_paths: List[Path],
        root_dir: Path,
        source_name: str,
    ) -> List[Dict[str, Any]]:
        records: List[Dict[str, Any]] = []

        for path in file_paths:
            rel = str(path.relative_to(root_dir)).replace("\\", "/")
            filename = path.name
            stem = path.stem

            record = self._base_record(
                record_id=f"media:{self._stable_hash(rel)}",
                record_type="media_asset",
                source_name=source_name,
                source_path=rel,
                text=None,
                entity_id=stem,
                metadata={
                    "filename": filename,
                    "path": rel,
                    "extension": path.suffix.lower(),
                    "linked_video_id": None,
                    "size_bytes": path.stat().st_size,
                },
                raw={},
            )
            records.append(record)

        return records

    # ============================================================
    # Reading helpers
    # ============================================================

    def _read_csv_from_zip(
        self,
        zf: zipfile.ZipFile,
        names: List[str],
        suffix: str,
    ) -> List[Dict[str, str]]:
        suffix_lower = suffix.lower().replace("\\", "/")
        for name in names:
            if name.lower().replace("\\", "/").endswith(suffix_lower):
                return self._read_csv_fileobj(zf.open(name))
        return []

    def _read_text_from_zip(
        self,
        zf: zipfile.ZipFile,
        names: List[str],
        suffix: str,
    ) -> Optional[str]:
        suffix_lower = suffix.lower().replace("\\", "/")
        for name in names:
            if name.lower().replace("\\", "/").endswith(suffix_lower):
                with zf.open(name) as f:
                    return f.read().decode("utf-8", errors="replace")
        return None

    def _read_csv_from_path(self, path: Optional[Path]) -> List[Dict[str, str]]:
        if not path or not path.exists():
            return []
        with path.open("r", encoding="utf-8", errors="replace", newline="") as f:
            reader = csv.DictReader(f)
            return [dict(row) for row in reader]

    def _read_csv_fileobj(self, file_obj: Any) -> List[Dict[str, str]]:
        text = file_obj.read().decode("utf-8", errors="replace")
        lines = text.splitlines()
        reader = csv.DictReader(lines)
        return [dict(row) for row in reader]

    # ============================================================
    # Record helpers
    # ============================================================

    def _base_record(
        self,
        record_id: str,
        record_type: str,
        source_name: str,
        source_path: str,
        title: Optional[str] = None,
        text: Optional[str] = None,
        url: Optional[str] = None,
        entity_id: Optional[str] = None,
        video_id: Optional[str] = None,
        channel_id: Optional[str] = None,
        channel_title: Optional[str] = None,
        playlist_id: Optional[str] = None,
        playlist_title: Optional[str] = None,
        timestamp: Optional[str] = None,
        created_at: Optional[str] = None,
        updated_at: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
        raw: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        return {
            "id": record_id,
            "record_type": record_type,
            "source_product": "youtube",
            "source_file": source_name,
            "source_path": source_path,
            "timestamp": timestamp,
            "created_at": created_at,
            "updated_at": updated_at,
            "title": title,
            "text": text,
            "url": url,
            "entity_id": entity_id,
            "video_id": video_id,
            "channel_id": channel_id,
            "channel_title": channel_title,
            "playlist_id": playlist_id,
            "playlist_title": playlist_title,
            "metadata": metadata or {},
            "raw": raw or {},
        }

    def _count_records(self, records: List[Dict[str, Any]]) -> Dict[str, int]:
        counts: Dict[str, int] = {}
        for record in records:
            record_type = record.get("record_type", "unknown")
            counts[record_type] = counts.get(record_type, 0) + 1
        return dict(sorted(counts.items(), key=lambda x: x[0]))

    # ============================================================
    # Utility helpers
    # ============================================================

    def _first_value(self, row: Dict[str, Any], keys: List[str]) -> Optional[str]:
        lowered = {str(k).strip().lower(): v for k, v in row.items()}
        for key in keys:
            value = lowered.get(key.strip().lower())
            if value is not None:
                value = str(value).strip()
                if value != "":
                    return value
        return None

    def _to_bool(self, value: Optional[str]) -> Optional[bool]:
        if value is None:
            return None
        v = str(value).strip().lower()
        if v in {"true", "yes", "1"}:
            return True
        if v in {"false", "no", "0"}:
            return False
        return None

    def _to_number(self, value: Optional[str]) -> Optional[Union[int, float]]:
        if value is None:
            return None
        s = str(value).strip()
        if s == "":
            return None
        try:
            if "." in s:
                return float(s)
            return int(s)
        except ValueError:
            return None

    def _normalize_datetime(self, value: Optional[str]) -> Optional[str]:
        if not value:
            return None

        s = str(value).strip()
        if not s:
            return None

        formats = [
            "%Y-%m-%dT%H:%M:%S.%f%z",
            "%Y-%m-%dT%H:%M:%S%z",
            "%Y-%m-%d %H:%M:%S%z",
            "%Y-%m-%d %H:%M:%S",
            "%Y-%m-%d",
        ]
        for fmt in formats:
            try:
                dt = datetime.strptime(s, fmt)
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                return dt.isoformat()
            except ValueError:
                continue

        try:
            dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.isoformat()
        except ValueError:
            return None

    def _extract_datetime_from_text(self, text: str) -> Optional[str]:
        patterns = [
            r"([A-Z][a-z]{2}\s+\d{1,2},\s+\d{4},\s+\d{1,2}:\d{2}:\d{2}\s*(?:AM|PM)\s*UTC)",
            r"([A-Z][a-z]{2}\s+\d{1,2},\s+\d{4},\s+\d{1,2}:\d{2}:\d{2}\s*(?:AM|PM))",
            r"(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z?)",
        ]

        for pattern in patterns:
            match = re.search(pattern, text)
            if match:
                value = match.group(1)
                # Try a couple of formats common in Google Takeout HTML
                for fmt in [
                    "%b %d, %Y, %I:%M:%S %p UTC",
                    "%b %d, %Y, %I:%M:%S %p",
                ]:
                    try:
                        dt = datetime.strptime(value, fmt).replace(tzinfo=timezone.utc)
                        return dt.isoformat()
                    except ValueError:
                        pass
                norm = self._normalize_datetime(value)
                if norm:
                    return norm
        return None

    def _extract_video_id(self, url: Optional[str]) -> Optional[str]:
        if not url:
            return None
        parsed = urlparse(url)
        if "youtu.be" in parsed.netloc:
            return parsed.path.strip("/") or None
        qs = parse_qs(parsed.query)
        if "v" in qs and qs["v"]:
            return qs["v"][0]
        return None

    def _extract_channel_id(self, url: Optional[str]) -> Optional[str]:
        if not url:
            return None
        m = re.search(r"/channel/([^/?]+)", url)
        if m:
            return m.group(1)
        return None

    def _extract_search_query(self, url: Optional[str]) -> Optional[str]:
        if not url:
            return None
        parsed = urlparse(url)
        qs = parse_qs(parsed.query)
        query = qs.get("search_query", [None])[0]
        return unescape(query) if query else None

    def _parse_serialized_segments(self, value: str) -> List[Dict[str, str]]:
        """
        Google Takeout sometimes stores text like a serialized list of segments.
        This tries to extract text parts safely.
        """
        if not value:
            return []

        cleaned = value.strip()

        # Try JSON-like first
        try:
            obj = json.loads(cleaned)
            if isinstance(obj, list):
                segments = []
                for item in obj:
                    if isinstance(item, dict):
                        text_val = item.get("text")
                        if text_val is not None:
                            segments.append({"text": str(text_val)})
                    elif isinstance(item, str):
                        segments.append({"text": item})
                if segments:
                    return segments
        except Exception:
            pass

        # Fallback: try to extract repeated text:'...'
        found = re.findall(r"""['"]text['"]\s*:\s*['"](.*?)['"]""", cleaned)
        if found:
            return [{"text": unescape(x)} for x in found]

        return [{"text": self._clean_text(cleaned)}]

    def _segments_to_text(self, segments: List[Dict[str, str]]) -> str:
        parts = []
        for seg in segments:
            text = seg.get("text")
            if text:
                parts.append(str(text))
        return self._clean_text("".join(parts))

    def _clean_text(self, value: Optional[str]) -> str:
        if value is None:
            return ""
        text = unescape(str(value))
        text = re.sub(r"\s+", " ", text).strip()
        return text

    def _is_media_file(self, name: str) -> bool:
        return Path(name).suffix.lower() in {
            ".mp4", ".mov", ".mkv", ".webm", ".avi", ".m4v", ".mp3", ".m4a", ".wav", ".flac"
        }

    def _stable_hash(self, value: str) -> str:
        import hashlib
        return hashlib.sha256(value.encode("utf-8", errors="ignore")).hexdigest()[:20]

    def _now_iso(self) -> str:
        return datetime.now(timezone.utc).isoformat()

    # ============================================================
    # CLI
    # ============================================================

    def run_cli(self, argv: List[str]) -> int:
        if len(argv) <= 1:
            result = self.parse()
        else:
            args = argv[1:]

            if args[0] in {"--list", "-l"}:
                for name in self.list_takeout_files():
                    print(name)
                return 0

            result = self.parse(args if len(args) > 1 else args[0])

        out_dir = self.write_output(result)
        print(f"Done. Output written to: {out_dir}")
        print(json.dumps(result.get("counts", {}), indent=2))
        return 0


def main() -> int:
    parser = YouTubeTakeoutParser()
    return parser.run_cli(sys.argv)


if __name__ == "__main__":
    raise SystemExit(main())