import React, { useEffect, useState } from "react";
import "./Recommendation.css";
import Loading from "../Loading/Loading";

const DATA_URL =
  "https://hkv39v0ul7.execute-api.us-east-1.amazonaws.com/prod/recommendations";

const POLL_INTERVAL_MS = 1000;
const MAX_POLL_ATTEMPTS = 180; // ~3 minutes

export default function Recommendations({ userId }) {
  const [data, setData] = useState(null);
  const [recommendations, setRecommendations] = useState([]);
  const [processing, setProcessing] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    if (!userId) {
      setError("Missing upload session. Please upload your Takeout ZIP again.");
      setProcessing(false);
      return;
    }

    let cancelled = false;
    let timeoutId;
    let attempts = 0;

    async function poll() {
      try {
        const response = await fetch(
          `${DATA_URL}?userId=${encodeURIComponent(userId)}`
        );

        if (response.status === 404) {
          const body = await response.json().catch(() => ({}));
          attempts += 1;

          if (body.status === "processing" && attempts < MAX_POLL_ATTEMPTS) {
            if (!cancelled) {
              timeoutId = setTimeout(poll, POLL_INTERVAL_MS);
            }
            return;
          }

          throw new Error(
            body.message || "Recommendations are taking longer than expected."
          );
        }

        if (!response.ok) {
          throw new Error("Failed to fetch recommendation data");
        }

        const json = await response.json();
        if (!cancelled) {
          setData(json);
          setRecommendations(json.recommendations || []);
          setProcessing(false);
        }
      } catch (err) {
        if (!cancelled) {
          setError(err.message);
          setProcessing(false);
        }
      }
    }

    poll();

    return () => {
      cancelled = true;
      clearTimeout(timeoutId);
    };
  }, [userId]);

  if (processing) {
    return <Loading />;
  }

  return (
    <div className="rec_page">
      <div className="rec_panel">
        <div className="rec_header">
          <div>
            <h1 className="rec_title">NETFEELINGS</h1>
            <p className="rec_subtitle">
              Personalized recommendations based on your watch taste.
            </p>
          </div>
        </div>

        {error && <p className="rec_error">Error: {error}</p>}

        {!error && (
          <>
            <div className="rec_summary">
              <div>
                <span>User</span>
                <strong>{data?.user_id || "Unknown"}</strong>
              </div>

              <div>
                <span>Recommendations</span>
                <strong>{recommendations.length}</strong>
              </div>
            </div>

            <div className="rec_channels">
              <p>Based on channels you watched</p>
              <div>
                {(data?.watched_channels || []).map((channel, index) => (
                  <span key={index}>{channel}</span>
                ))}
              </div>
            </div>

            <div className="rec_grid">
              {recommendations.map((item, index) => (
                <div className="rec_card" key={index}>
                  <div className="rec_rank">#{index + 1}</div>

                  <div className="rec_imagePlaceholder">
                    {item.category || "video"}
                  </div>

                  <div className="rec_cardBody">
                    <div className="rec_category">{item.category}</div>

                    <h2 className="rec_movieTitle">{item.title}</h2>

                    <p className="rec_channel">{item.author || item.channel}</p>

                    <p className="rec_explanation">{item.explanation}</p>

                    <div className="rec_match">
                      <span>Match</span>
                      <strong>{item.match_percent?.toFixed(1)}%</strong>
                    </div>

                    <div className="rec_barTrack">
                      <div
                        className="rec_barFill"
                        style={{ width: `${item.match_percent}%` }}
                      />
                    </div>

                    <a
                      className="rec_link"
                      href={item.video_url}
                      target="_blank"
                      rel="noreferrer"
                    >
                      Watch Recommendation
                    </a>
                  </div>
                </div>
              ))}
            </div>
          </>
        )}
      </div>
    </div>
  );
}
