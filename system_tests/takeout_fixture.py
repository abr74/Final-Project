"""
Builds a small, synthetic Google Takeout ZIP matching the CSV/HTML layout
that python/parser.py already understands (see tests/test_parser.py for the
same shapes used in the unit tests). Used as real upload payload against the
live upload-url Lambda + S3 in the system tests.

Every generated file embeds a unique marker so a system test can later prove
that *this specific* upload made it through the deployed pipeline, by
searching for the marker in the recommendations endpoint's response or in
the parsed output in S3.
"""

import io
import zipfile
from typing import Tuple


def build_synthetic_takeout_zip(marker: str) -> Tuple[bytes, str]:
    """
    Returns (zip_bytes, channel_title) for a synthetic Takeout export.

    channel_title is a real channel from the deployed model universe (not a
    synthetic one) so the fusion-recommender's known-channel filter actually
    recognizes it in watched_channels -- the marker instead lives in the
    comment text, video/channel IDs, and (via the upload/output S3 keys) the
    uploadId, which is enough to prove this specific test run flowed through
    the pipeline end to end.
    """
    channel_id = f"UCsystest{marker}"
    channel_title = "Ed Sheeran"  # known channel in models-v2/bert_scores.json
    video_id = f"vid{marker}"

    comments_csv = (
        "Comment ID,Parent Comment ID,Top Level Comment ID,Channel ID,Video ID,Time,Price,Comment Text\n"
        f'c{marker},p{marker},t{marker},{channel_id},{video_id},2024-01-01T12:00:00+00:00,0,'
        f'"[{{""text"": ""system test comment {marker}""}}]"\n'
    )

    subscriptions_csv = (
        "Channel ID,Channel Title,Channel URL\n"
        f"{channel_id},{channel_title},https://www.youtube.com/channel/{channel_id}\n"
    )

    watch_history_html = f"""
    <html><body>
      <div>
        Watched
        <a href="https://www.youtube.com/watch?v={video_id}">SysTest Video {marker}</a>
        from
        <a href="https://www.youtube.com/channel/{channel_id}">{channel_title}</a>
        Jan 02, 2024, 03:04:05 PM UTC
      </div>
    </body></html>
    """

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as zf:
        zf.writestr(
            "Takeout/YouTube and YouTube Music/comments/comments.csv", comments_csv
        )
        zf.writestr(
            "Takeout/YouTube and YouTube Music/subscriptions/subscriptions.csv",
            subscriptions_csv,
        )
        zf.writestr(
            "Takeout/YouTube and YouTube Music/history/watch-history.html",
            watch_history_html,
        )

    return buffer.getvalue(), channel_title
