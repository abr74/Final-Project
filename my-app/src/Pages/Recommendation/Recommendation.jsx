import React, { useEffect, useState } from "react";
import "./Recommendation.css";

const DATA_URL =
  "https://hkv39v0ul7.execute-api.us-east-1.amazonaws.com/prod/recommendations";

export default function Recommendations() {
  const [data, setData] = useState(null);
  const [recommendations, setRecommendations] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    async function fetchRecommendations() {
      try {
        const response = await fetch(DATA_URL);

        if (!response.ok) {
          throw new Error("Failed to fetch recommendation data");
        }

        const json = await response.json();
        setData(json);
        setRecommendations(json.recommendations || []);
      } catch (err) {
        setError(err.message);
      } finally {
        setLoading(false);
      }
    }

    fetchRecommendations();
  }, []);

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

        {loading && <p className="rec_status">Loading recommendations...</p>}

        {error && <p className="rec_error">Error: {error}</p>}

        {!loading && !error && (
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