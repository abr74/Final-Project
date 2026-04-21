from pathlib import Path
import importlib.util
import json
import zipfile


def load_parser_class():
    project_root = Path(__file__).resolve().parents[1]

    possible_paths = [
        project_root / "parser.py",
        project_root / "python" / "parser.py",
        project_root / "src" / "parser.py",
    ]

    parser_path = None
    for path in possible_paths:
        if path.exists():
            parser_path = path
            break

    if parser_path is None:
        raise FileNotFoundError(
            f"Could not find parser.py. Checked: {[str(p) for p in possible_paths]}"
        )

    spec = importlib.util.spec_from_file_location("takeout_parser_module", parser_path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module.YouTubeTakeoutParser


YouTubeTakeoutParser = load_parser_class()


def write_zip(zip_path: Path, files: dict[str, str | bytes]) -> None:
    with zipfile.ZipFile(zip_path, "w") as zf:
        for name, content in files.items():
            zf.writestr(name, content)


def test_parser_can_parse_one_zip(tmp_path):
    takeout_dir = tmp_path / "Takeout Collection"
    takeout_dir.mkdir()

    zip_path = takeout_dir / "sample.zip"

    write_zip(
        zip_path,
        {
            "Takeout/YouTube and YouTube Music/comments/comments.csv": (
                "Comment ID,Parent Comment ID,Top Level Comment ID,Channel ID,Video ID,Time,Price,Comment Text\n"
                'c1,p1,t1,ch1,v1,2024-01-01T12:00:00+00:00,0,"[{""text"": ""hello world""}]"\n'
            ),
        },
    )

    parser = YouTubeTakeoutParser(takeout_collection_dir=takeout_dir)
    result = parser.parse("sample.zip")

    assert result["counts"]["comment"] == 1
    assert len(result["all_records"]) == 1

    record = result["all_records"][0]
    assert record["record_type"] == "comment"
    assert record["id"] == "comment:c1"
    assert record["channel_id"] == "ch1"
    assert record["video_id"] == "v1"
    assert record["text"] == "hello world"


def test_parser_returns_missing_status_for_missing_source(tmp_path):
    takeout_dir = tmp_path / "Takeout Collection"
    takeout_dir.mkdir()

    parser = YouTubeTakeoutParser(takeout_collection_dir=takeout_dir)
    result = parser.parse("does_not_exist.zip")

    assert len(result["sources"]) == 1
    assert result["sources"][0]["source_name"] == "does_not_exist.zip"
    assert result["sources"][0]["status"] == "missing"
    assert result["sources"][0]["record_count"] == 0
    assert result["counts"] == {}
    assert result["all_records"] == []


def test_list_takeout_files_includes_zip_and_directory(tmp_path):
    takeout_dir = tmp_path / "Takeout Collection"
    takeout_dir.mkdir()

    (takeout_dir / "one.zip").write_bytes(b"")
    (takeout_dir / "folder_takeout").mkdir()
    (takeout_dir / "ignore.txt").write_text("nope", encoding="utf-8")

    parser = YouTubeTakeoutParser(takeout_collection_dir=takeout_dir)
    result = parser.list_takeout_files()

    assert result == ["folder_takeout", "one.zip"]


def test_parser_can_parse_all_sources_when_targets_none(tmp_path):
    takeout_dir = tmp_path / "Takeout Collection"
    takeout_dir.mkdir()

    write_zip(
        takeout_dir / "comments.zip",
        {
            "Takeout/YouTube and YouTube Music/comments/comments.csv": (
                "Comment ID,Parent Comment ID,Top Level Comment ID,Channel ID,Video ID,Time,Price,Comment Text\n"
                'c1,p1,t1,ch1,v1,2024-01-01T12:00:00+00:00,0,"[{""text"": ""hello""}]"\n'
            ),
        },
    )

    write_zip(
        takeout_dir / "subs.zip",
        {
            "Takeout/YouTube and YouTube Music/subscriptions/subscriptions.csv": (
                "Channel ID,Channel Title,Channel URL\n"
                "sub1,Test Channel,https://www.youtube.com/channel/sub1\n"
            ),
        },
    )

    parser = YouTubeTakeoutParser(takeout_collection_dir=takeout_dir)
    result = parser.parse()

    assert len(result["sources"]) == 2
    assert all(source["status"] == "parsed" for source in result["sources"])
    assert result["counts"]["comment"] == 1
    assert result["counts"]["subscription"] == 1
    assert len(result["all_records"]) == 2


def test_parser_can_parse_multiple_named_targets(tmp_path):
    takeout_dir = tmp_path / "Takeout Collection"
    takeout_dir.mkdir()

    write_zip(
        takeout_dir / "a.zip",
        {
            "Takeout/YouTube and YouTube Music/comments/comments.csv": (
                "Comment ID,Parent Comment ID,Top Level Comment ID,Channel ID,Video ID,Time,Price,Comment Text\n"
                'c1,p1,t1,ch1,v1,2024-01-01T12:00:00+00:00,0,"plain text"\n'
            ),
        },
    )

    write_zip(
        takeout_dir / "b.zip",
        {
            "Takeout/YouTube and YouTube Music/subscriptions/subscriptions.csv": (
                "Channel ID,Channel Title,Channel URL\n"
                "sub1,Another Channel,https://www.youtube.com/channel/sub1\n"
            ),
        },
    )

    parser = YouTubeTakeoutParser(takeout_collection_dir=takeout_dir)
    result = parser.parse(["a.zip", "b.zip"])

    assert len(result["sources"]) == 2
    assert result["counts"]["comment"] == 1
    assert result["counts"]["subscription"] == 1


def test_parse_multiple_targets_with_one_missing(tmp_path):
    takeout_dir = tmp_path / "Takeout Collection"
    takeout_dir.mkdir()

    write_zip(
        takeout_dir / "good.zip",
        {
            "Takeout/YouTube and YouTube Music/comments/comments.csv": (
                "Comment ID,Parent Comment ID,Top Level Comment ID,Channel ID,Video ID,Time,Price,Comment Text\n"
                'c1,p1,t1,ch1,v1,2024-01-01T12:00:00+00:00,0,"hello"\n'
            ),
        },
    )

    parser = YouTubeTakeoutParser(takeout_collection_dir=takeout_dir)
    result = parser.parse(["good.zip", "missing.zip"])

    assert len(result["sources"]) == 2
    assert result["counts"]["comment"] == 1

    statuses = {source["source_name"]: source["status"] for source in result["sources"]}
    assert statuses["good.zip"] == "parsed"
    assert statuses["missing.zip"] == "missing"


def test_parser_can_parse_subscription_rows(tmp_path):
    takeout_dir = tmp_path / "Takeout Collection"
    takeout_dir.mkdir()

    write_zip(
        takeout_dir / "sample.zip",
        {
            "Takeout/YouTube and YouTube Music/subscriptions/subscriptions.csv": (
                "Channel ID,Channel Title,Channel URL\n"
                "sub123,My Channel,https://www.youtube.com/channel/sub123\n"
            ),
        },
    )

    parser = YouTubeTakeoutParser(takeout_collection_dir=takeout_dir)
    result = parser.parse("sample.zip")

    assert result["counts"]["subscription"] == 1

    record = result["all_records"][0]
    assert record["record_type"] == "subscription"
    assert record["id"] == "subscription:sub123"
    assert record["channel_id"] == "sub123"
    assert record["channel_title"] == "My Channel"
    assert record["url"] == "https://www.youtube.com/channel/sub123"


def test_subscription_can_extract_channel_id_from_url_when_missing_in_csv(tmp_path):
    takeout_dir = tmp_path / "Takeout Collection"
    takeout_dir.mkdir()

    write_zip(
        takeout_dir / "sub_url_only.zip",
        {
            "Takeout/YouTube and YouTube Music/subscriptions/subscriptions.csv": (
                "Channel Title,Channel URL\n"
                "Channel From URL,https://www.youtube.com/channel/channel_from_url\n"
            ),
        },
    )

    parser = YouTubeTakeoutParser(takeout_collection_dir=takeout_dir)
    result = parser.parse("sub_url_only.zip")

    record = result["all_records"][0]
    assert record["record_type"] == "subscription"
    assert record["channel_id"] == "channel_from_url"
    assert record["channel_title"] == "Channel From URL"


def test_parser_can_parse_playlist_rows(tmp_path):
    takeout_dir = tmp_path / "Takeout Collection"
    takeout_dir.mkdir()

    write_zip(
        takeout_dir / "sample.zip",
        {
            "Takeout/YouTube and YouTube Music/playlists/playlists.csv": (
                "Playlist Id,Title,Create Timestamp,Update Timestamp,Visibility,Video Order\n"
                "pl1,Favorites,2024-01-01T10:00:00+00:00,2024-01-02T10:00:00+00:00,Private,Manual\n"
            ),
        },
    )

    parser = YouTubeTakeoutParser(takeout_collection_dir=takeout_dir)
    result = parser.parse("sample.zip")

    assert result["counts"]["playlist"] == 1

    record = result["all_records"][0]
    assert record["record_type"] == "playlist"
    assert record["id"] == "playlist:pl1"
    assert record["playlist_id"] == "pl1"
    assert record["playlist_title"] == "Favorites"
    assert record["created_at"] == "2024-01-01T10:00:00+00:00"
    assert record["updated_at"] == "2024-01-02T10:00:00+00:00"


def test_parser_can_parse_playlist_item_rows(tmp_path):
    takeout_dir = tmp_path / "Takeout Collection"
    takeout_dir.mkdir()

    write_zip(
        takeout_dir / "sample.zip",
        {
            "Takeout/YouTube and YouTube Music/playlists/My Playlist-videos.csv": (
                "Playlist Id,Playlist Title,Video ID,Added At,Video Title,Video URL\n"
                "pl1,My Playlist,v123,2024-01-01T12:00:00+00:00,Video One,https://www.youtube.com/watch?v=v123\n"
            ),
        },
    )

    parser = YouTubeTakeoutParser(takeout_collection_dir=takeout_dir)
    result = parser.parse("sample.zip")

    assert result["counts"]["playlist_item"] == 1

    record = result["all_records"][0]
    assert record["record_type"] == "playlist_item"
    assert record["playlist_id"] == "pl1"
    assert record["playlist_title"] == "My Playlist"
    assert record["video_id"] == "v123"


def test_playlist_item_can_extract_video_id_from_url(tmp_path):
    takeout_dir = tmp_path / "Takeout Collection"
    takeout_dir.mkdir()

    write_zip(
        takeout_dir / "playlist_item_url.zip",
        {
            "Takeout/YouTube and YouTube Music/playlists/My Playlist-videos.csv": (
                "Playlist Id,Playlist Title,Video URL,Added At,Video Title\n"
                "pl1,My Playlist,https://www.youtube.com/watch?v=video_from_url,2024-01-01T12:00:00+00:00,Video One\n"
            ),
        },
    )

    parser = YouTubeTakeoutParser(takeout_collection_dir=takeout_dir)
    result = parser.parse("playlist_item_url.zip")

    record = result["all_records"][0]
    assert record["record_type"] == "playlist_item"
    assert record["video_id"] == "video_from_url"


def test_parser_can_parse_uploaded_video_rows(tmp_path):
    takeout_dir = tmp_path / "Takeout Collection"
    takeout_dir.mkdir()

    write_zip(
        takeout_dir / "sample.zip",
        {
            "Takeout/YouTube and YouTube Music/video metadata/videos.csv": (
                "Video ID,Video Title,Channel ID,Create Timestamp,Update Timestamp,Privacy,Video State,Video Filename\n"
                "vid1,My Video,ch1,2024-01-01T10:00:00+00:00,2024-01-02T10:00:00+00:00,Private,Processed,my_video.mp4\n"
            ),
            "Takeout/YouTube and YouTube Music/video metadata/video texts.csv": (
                "Video ID,Description,Tags\n"
                'vid1,"This is a test description","tag1,tag2"\n'
            ),
            "Takeout/YouTube and YouTube Music/video metadata/video recordings.csv": (
                "Video ID,Recording Latitude,Recording Longitude,Recording Altitude\n"
                "vid1,40.0,-75.0,10\n"
            ),
            "Takeout/YouTube and YouTube Music/videos/my_video.mp4": b"fake-video-bytes",
        },
    )

    parser = YouTubeTakeoutParser(takeout_collection_dir=takeout_dir)
    result = parser.parse("sample.zip")

    assert result["counts"]["uploaded_video"] == 1
    assert result["counts"]["media_asset"] == 1

    uploaded = [r for r in result["all_records"] if r["record_type"] == "uploaded_video"][0]
    assert uploaded["id"] == "video:vid1"
    assert uploaded["video_id"] == "vid1"
    assert uploaded["channel_id"] == "ch1"
    assert uploaded["title"] == "My Video"
    assert "This is a test description" in uploaded["text"]
    assert uploaded["metadata"]["media_filename"] == "my_video.mp4"
    assert uploaded["metadata"]["media_path"].endswith("videos/my_video.mp4")


def test_parser_can_parse_watch_history_html(tmp_path):
    takeout_dir = tmp_path / "Takeout Collection"
    takeout_dir.mkdir()

    html = """
    <html><body>
      <div>
        Watched
        <a href="https://www.youtube.com/watch?v=abc123">Test Video</a>
        from
        <a href="https://www.youtube.com/channel/ch123">Test Channel</a>
        Jan 02, 2024, 03:04:05 PM UTC
      </div>
    </body></html>
    """

    write_zip(
        takeout_dir / "sample.zip",
        {
            "Takeout/YouTube and YouTube Music/history/watch-history.html": html,
        },
    )

    parser = YouTubeTakeoutParser(takeout_collection_dir=takeout_dir)
    result = parser.parse("sample.zip")

    assert result["counts"]["watch_event"] == 1

    record = result["all_records"][0]
    assert record["record_type"] == "watch_event"
    assert record["video_id"] == "abc123"
    assert record["channel_id"] == "ch123"
    assert record["channel_title"] == "Test Channel"
    assert record["title"] == "Test Video"
    assert record["url"] == "https://www.youtube.com/watch?v=abc123"


def test_parse_watch_history_without_video_link_does_not_create_record(tmp_path):
    takeout_dir = tmp_path / "Takeout Collection"
    takeout_dir.mkdir()

    html = """
    <html><body>
      <div>
        Watched something with no actual video link
        <a href="https://www.youtube.com/channel/ch123">Some Channel</a>
        Jan 02, 2024, 03:04:05 PM UTC
      </div>
    </body></html>
    """

    write_zip(
        takeout_dir / "watch_no_video.zip",
        {
            "Takeout/YouTube and YouTube Music/history/watch-history.html": html,
        },
    )

    parser = YouTubeTakeoutParser(takeout_collection_dir=takeout_dir)
    result = parser.parse("watch_no_video.zip")

    assert result["all_records"] == []
    assert result["counts"] == {}


def test_parser_can_parse_search_history_html(tmp_path):
    takeout_dir = tmp_path / "Takeout Collection"
    takeout_dir.mkdir()

    html = """
    <html><body>
      <div>
        Searched for
        <a href="https://www.youtube.com/results?search_query=python+tutorial">python tutorial</a>
        Jan 02, 2024, 03:04:05 PM UTC
      </div>
    </body></html>
    """

    write_zip(
        takeout_dir / "sample.zip",
        {
            "Takeout/YouTube and YouTube Music/history/search-history.html": html,
        },
    )

    parser = YouTubeTakeoutParser(takeout_collection_dir=takeout_dir)
    result = parser.parse("sample.zip")

    assert result["counts"]["search_event"] == 1

    record = result["all_records"][0]
    assert record["record_type"] == "search_event"
    assert record["metadata"]["query"] == "python tutorial"
    assert record["url"] == "https://www.youtube.com/results?search_query=python+tutorial"


def test_parse_search_history_without_link_does_not_create_record(tmp_path):
    takeout_dir = tmp_path / "Takeout Collection"
    takeout_dir.mkdir()

    html = """
    <html><body>
      <div>Searched for something but no link here Jan 02, 2024, 03:04:05 PM UTC</div>
    </body></html>
    """

    write_zip(
        takeout_dir / "search_no_link.zip",
        {
            "Takeout/YouTube and YouTube Music/history/search-history.html": html,
        },
    )

    parser = YouTubeTakeoutParser(takeout_collection_dir=takeout_dir)
    result = parser.parse("search_no_link.zip")

    assert result["all_records"] == []
    assert result["counts"] == {}


def test_parser_can_parse_live_chat_rows(tmp_path):
    takeout_dir = tmp_path / "Takeout Collection"
    takeout_dir.mkdir()

    write_zip(
        takeout_dir / "sample.zip",
        {
            "Takeout/YouTube and YouTube Music/live chats/chat1.csv": (
                "Live Chat Message ID,Channel ID,Video ID,Time,Price,Message\n"
                'm1,ch1,v1,2024-01-01T12:00:00+00:00,0,"[{""text"": ""live message""}]"\n'
            ),
        },
    )

    parser = YouTubeTakeoutParser(takeout_collection_dir=takeout_dir)
    result = parser.parse("sample.zip")

    assert result["counts"]["live_chat"] == 1

    record = result["all_records"][0]
    assert record["record_type"] == "live_chat"
    assert record["id"] == "live_chat:m1"
    assert record["channel_id"] == "ch1"
    assert record["video_id"] == "v1"
    assert record["text"] == "live message"


def test_parser_can_parse_channel_profile_rows(tmp_path):
    takeout_dir = tmp_path / "Takeout Collection"
    takeout_dir.mkdir()

    write_zip(
        takeout_dir / "sample.zip",
        {
            "Takeout/YouTube and YouTube Music/channel.csv": (
                "Channel ID,Title,Visibility,Channel URL\n"
                "chan1,My Channel,Public,https://www.youtube.com/channel/chan1\n"
            ),
            "Takeout/YouTube and YouTube Music/channel URL configs.csv": (
                "Channel URL,Vanity URL Name\n"
                "https://www.youtube.com/channel/chan1,myhandle\n"
            ),
            "Takeout/YouTube and YouTube Music/channel feature data.csv": (
                "Auto Moderation in Live Chat,Default Comments Setting,Default Target Audience,Default License,Default Recording Location Latitude,Default Recording Location Longitude\n"
                "true,Allow all,Not made for kids,Standard,40.1,-75.2\n"
            ),
        },
    )

    parser = YouTubeTakeoutParser(takeout_collection_dir=takeout_dir)
    result = parser.parse("sample.zip")

    assert result["counts"]["channel_profile"] == 1

    record = result["all_records"][0]
    assert record["record_type"] == "channel_profile"
    assert record["id"] == "channel:chan1"
    assert record["channel_id"] == "chan1"
    assert record["channel_title"] == "My Channel"
    assert record["metadata"]["visibility"] == "Public"
    assert record["metadata"]["vanity_url_name"] == "myhandle"
    assert record["metadata"]["auto_moderation_live_chat"] is True


def test_channel_profile_can_extract_channel_id_from_url_configs(tmp_path):
    takeout_dir = tmp_path / "Takeout Collection"
    takeout_dir.mkdir()

    write_zip(
        takeout_dir / "channel_fallback.zip",
        {
            "Takeout/YouTube and YouTube Music/channel URL configs.csv": (
                "Channel URL,Vanity URL Name\n"
                "https://www.youtube.com/channel/fallback_channel,myvanity\n"
            ),
        },
    )

    parser = YouTubeTakeoutParser(takeout_collection_dir=takeout_dir)
    result = parser.parse("channel_fallback.zip")

    record = result["all_records"][0]
    assert record["record_type"] == "channel_profile"
    assert record["channel_id"] == "fallback_channel"
    assert record["id"] == "channel:fallback_channel"


def test_comment_text_plain_string_is_preserved(tmp_path):
    takeout_dir = tmp_path / "Takeout Collection"
    takeout_dir.mkdir()

    write_zip(
        takeout_dir / "plain_comment.zip",
        {
            "Takeout/YouTube and YouTube Music/comments/comments.csv": (
                "Comment ID,Parent Comment ID,Top Level Comment ID,Channel ID,Video ID,Time,Price,Comment Text\n"
                'c2,p2,t2,ch2,v2,2024-01-01T12:00:00+00:00,5,just plain text\n'
            ),
        },
    )

    parser = YouTubeTakeoutParser(takeout_collection_dir=takeout_dir)
    result = parser.parse("plain_comment.zip")

    record = result["all_records"][0]
    assert record["record_type"] == "comment"
    assert record["text"] == "just plain text"
    assert record["metadata"]["price"] == 5


def test_comment_without_comment_id_uses_fallback_hash(tmp_path):
    takeout_dir = tmp_path / "Takeout Collection"
    takeout_dir.mkdir()

    write_zip(
        takeout_dir / "missing_comment_id.zip",
        {
            "Takeout/YouTube and YouTube Music/comments/comments.csv": (
                "Parent Comment ID,Top Level Comment ID,Channel ID,Video ID,Time,Price,Comment Text\n"
                'p1,t1,ch1,v1,2024-01-01T12:00:00+00:00,0,"hello"\n'
            ),
        },
    )

    parser = YouTubeTakeoutParser(takeout_collection_dir=takeout_dir)
    result = parser.parse("missing_comment_id.zip")

    record = result["all_records"][0]
    assert record["record_type"] == "comment"
    assert record["id"].startswith("comment:")
    assert record["entity_id"] is not None


def test_media_asset_detects_audio_file_too(tmp_path):
    takeout_dir = tmp_path / "Takeout Collection"
    takeout_dir.mkdir()

    write_zip(
        takeout_dir / "audio_asset.zip",
        {
            "Takeout/YouTube and YouTube Music/videos/song.m4a": b"fake-audio",
        },
    )

    parser = YouTubeTakeoutParser(takeout_collection_dir=takeout_dir)
    result = parser.parse("audio_asset.zip")

    assert result["counts"]["media_asset"] == 1
    record = result["all_records"][0]
    assert record["record_type"] == "media_asset"
    assert record["metadata"]["filename"] == "song.m4a"
    assert record["metadata"]["extension"] == ".m4a"


def test_write_output_creates_expected_files(tmp_path):
    takeout_dir = tmp_path / "Takeout Collection"
    takeout_dir.mkdir()

    write_zip(
        takeout_dir / "sample.zip",
        {
            "Takeout/YouTube and YouTube Music/comments/comments.csv": (
                "Comment ID,Parent Comment ID,Top Level Comment ID,Channel ID,Video ID,Time,Price,Comment Text\n"
                'c1,p1,t1,ch1,v1,2024-01-01T12:00:00+00:00,0,"[{""text"": ""hello world""}]"\n'
            ),
        },
    )

    parser = YouTubeTakeoutParser(takeout_collection_dir=takeout_dir)
    result = parser.parse("sample.zip")

    output_dir = tmp_path / "parsed_output"
    written_dir = parser.write_output(result, output_dir)

    assert written_dir == output_dir
    assert (output_dir / "central_output.json").exists()
    assert (output_dir / "all_records.jsonl").exists()
    assert (output_dir / "comment.jsonl").exists()
    assert (output_dir / "manifest.json").exists()

    central = json.loads((output_dir / "central_output.json").read_text(encoding="utf-8"))
    manifest = json.loads((output_dir / "manifest.json").read_text(encoding="utf-8"))

    assert central["counts"]["comment"] == 1
    assert "comment.jsonl" in manifest["files_written"]


def test_getter_methods_return_filtered_records(tmp_path):
    takeout_dir = tmp_path / "Takeout Collection"
    takeout_dir.mkdir()

    write_zip(
        takeout_dir / "sample.zip",
        {
            "Takeout/YouTube and YouTube Music/comments/comments.csv": (
                "Comment ID,Parent Comment ID,Top Level Comment ID,Channel ID,Video ID,Time,Price,Comment Text\n"
                'c1,p1,t1,ch1,v1,2024-01-01T12:00:00+00:00,0,"[{""text"": ""hello world""}]"\n'
            ),
            "Takeout/YouTube and YouTube Music/subscriptions/subscriptions.csv": (
                "Channel ID,Channel Title,Channel URL\n"
                "sub1,Test Channel,https://www.youtube.com/channel/sub1\n"
            ),
        },
    )

    parser = YouTubeTakeoutParser(takeout_collection_dir=takeout_dir)
    result = parser.parse("sample.zip")
    records = result["all_records"]

    comments = parser.get_comments(records)
    subscriptions = parser.get_subscriptions(records)
    watch_history = parser.get_watch_history(records)

    assert len(comments) == 1
    assert comments[0]["record_type"] == "comment"

    assert len(subscriptions) == 1
    assert subscriptions[0]["record_type"] == "subscription"

    assert watch_history == []


def test_getter_methods_cover_more_types(tmp_path):
    takeout_dir = tmp_path / "Takeout Collection"
    takeout_dir.mkdir()

    write_zip(
        takeout_dir / "mixed.zip",
        {
            "Takeout/YouTube and YouTube Music/comments/comments.csv": (
                "Comment ID,Parent Comment ID,Top Level Comment ID,Channel ID,Video ID,Time,Price,Comment Text\n"
                'c1,p1,t1,ch1,v1,2024-01-01T12:00:00+00:00,0,"hello"\n'
            ),
            "Takeout/YouTube and YouTube Music/playlists/playlists.csv": (
                "Playlist Id,Title\n"
                "pl1,Favorites\n"
            ),
            "Takeout/YouTube and YouTube Music/video metadata/videos.csv": (
                "Video ID,Video Title,Channel ID\n"
                "vid1,My Video,ch1\n"
            ),
        },
    )

    parser = YouTubeTakeoutParser(takeout_collection_dir=takeout_dir)
    records = parser.parse("mixed.zip")["all_records"]

    assert len(parser.get_comments(records)) == 1
    assert len(parser.get_playlists(records)) == 1
    assert len(parser.get_uploaded_videos(records)) == 1
    assert parser.get_search_history(records) == []
    assert parser.get_live_chats(records) == []


def test_parse_directory_source_works_like_zip_source(tmp_path):
    takeout_dir = tmp_path / "Takeout Collection"
    takeout_dir.mkdir()

    extracted = takeout_dir / "extracted_takeout"
    comments_dir = extracted / "Takeout" / "YouTube and YouTube Music" / "comments"
    comments_dir.mkdir(parents=True)

    (comments_dir / "comments.csv").write_text(
        "Comment ID,Parent Comment ID,Top Level Comment ID,Channel ID,Video ID,Time,Price,Comment Text\n"
        'c1,p1,t1,ch1,v1,2024-01-01T12:00:00+00:00,0,"[{""text"": ""hello from folder""}]"\n',
        encoding="utf-8",
    )

    parser = YouTubeTakeoutParser(takeout_collection_dir=takeout_dir)
    result = parser.parse("extracted_takeout")

    assert result["counts"]["comment"] == 1
    assert result["all_records"][0]["text"] == "hello from folder"


def test_parse_serialized_segments_with_json_string_helper():
    parser = YouTubeTakeoutParser()

    segments = parser._parse_serialized_segments('[{"text":"hello"},{"text":" world"}]')
    assert segments == [{"text": "hello"}, {"text": " world"}]
    assert parser._segments_to_text(segments) == "hello world"


def test_parse_serialized_segments_with_key_value_style_text_helper():
    parser = YouTubeTakeoutParser()

    value = '{"runs":[{"text":"hello"},{"text":" world"}]}'
    segments = parser._parse_serialized_segments(value)

    assert parser._segments_to_text(segments) == "hello world"


def test_clean_text_unescapes_and_normalizes_spaces():
    parser = YouTubeTakeoutParser()

    result = parser._clean_text("hello&nbsp;&amp;   world \n\n test")
    assert "hello" in result
    assert "& world test" in result


def test_extract_datetime_from_text_helper():
    parser = YouTubeTakeoutParser()

    text = "Watched Something Jan 02, 2024, 03:04:05 PM UTC"
    result = parser._extract_datetime_from_text(text)

    assert result == "2024-01-02T15:04:05+00:00"


def test_helper_methods_basic_behavior():
    parser = YouTubeTakeoutParser()

    assert parser._to_bool("true") is True
    assert parser._to_bool("yes") is True
    assert parser._to_bool("false") is False
    assert parser._to_bool("no") is False
    assert parser._to_bool("maybe") is None

    assert parser._to_number("10") == 10
    assert parser._to_number("10.5") == 10.5
    assert parser._to_number("") is None
    assert parser._to_number("abc") is None

    assert parser._extract_video_id("https://www.youtube.com/watch?v=abc123") == "abc123"
    assert parser._extract_video_id("https://youtu.be/xyz789") == "xyz789"
    assert parser._extract_video_id("https://example.com") is None

    assert parser._extract_channel_id("https://www.youtube.com/channel/chan123") == "chan123"
    assert parser._extract_channel_id("https://www.youtube.com/@name") is None

    assert parser._extract_search_query(
        "https://www.youtube.com/results?search_query=python+tutorial"
    ) == "python tutorial"

    assert parser._normalize_datetime("2024-01-01") == "2024-01-01T00:00:00+00:00"
    assert parser._normalize_datetime("2024-01-01T12:00:00+00:00") == "2024-01-01T12:00:00+00:00"


def test_is_media_file_helper():
    parser = YouTubeTakeoutParser()

    assert parser._is_media_file("video.mp4") is True
    assert parser._is_media_file("audio.flac") is True
    assert parser._is_media_file("notes.txt") is False


def test_count_records_helper():
    parser = YouTubeTakeoutParser()

    records = [
        {"record_type": "comment"},
        {"record_type": "comment"},
        {"record_type": "subscription"},
    ]

    counts = parser._count_records(records)
    assert counts == {"comment": 2, "subscription": 1}


def test_parse_empty_zip_returns_no_records(tmp_path):
    takeout_dir = tmp_path / "Takeout Collection"
    takeout_dir.mkdir()

    write_zip(takeout_dir / "empty.zip", {})

    parser = YouTubeTakeoutParser(takeout_collection_dir=takeout_dir)
    result = parser.parse("empty.zip")

    assert result["all_records"] == []
    assert result["counts"] == {}
    assert result["sources"][0]["status"] == "parsed"
    assert result["sources"][0]["record_count"] == 0


def test_parse_bad_zip_is_reported_as_error(tmp_path):
    takeout_dir = tmp_path / "Takeout Collection"
    takeout_dir.mkdir()

    bad_zip = takeout_dir / "bad.zip"
    bad_zip.write_text("not actually a zip file", encoding="utf-8")

    parser = YouTubeTakeoutParser(takeout_collection_dir=takeout_dir)
    result = parser.parse("bad.zip")

    assert result["sources"][0]["status"] == "error"
    assert result["sources"][0]["record_count"] == 0
    assert "error" in result["sources"][0]