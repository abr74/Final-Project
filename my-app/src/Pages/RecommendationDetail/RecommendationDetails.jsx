import React from "react";
import "./RecommendationDetails.css";

export default function RecommendationDetail() {

  const movie = {
    title: "Tenet",
    match: 96,
    genre: "Sci-Fi/Action",
    reason: "Complex plot structure like Inception, strong visual cinematography",
    image: null, // <- placeholder for now
    aspects: {
      acting: 85,
      visuals: 98,
      plot: 96,
      pacing: 78
    }
  };

  return (
    <div className="detail_overlay">

      <div className="detail_modal">

        {/* Close Button */}
        <button className="detail_closeBtn">✕</button>

        {/* Top Banner */}
        <div className="detail_banner">

          <div className="detail_imageWrap">
            {movie.image ? (
              <img src={movie.image} alt={movie.title} />
            ) : (
              <div className="detail_placeholder">
                placeholder
              </div>
            )}
          </div>

        </div>

        {/* Content */}
        <div className="detail_content">

          {/* Header */}
          <div className="detail_headerRow">
            <h1>{movie.title}</h1>

            <span className="detail_match">
              {movie.match}% Match
            </span>

            <span className="detail_genre">
              {movie.genre}
            </span>
          </div>

          {/* Reason */}
          <div className="detail_reasonBox">
            <h3>Why We Recommend This:</h3>
            <p>{movie.reason}</p>
          </div>

          {/* Aspect Bars */}
          <div className="detail_aspects">
            <h4>Aspect Breakdown:</h4>

            <div className="detail_barRow">
              <span>Acting</span>
              <div className="detail_barTrack">
                <div
                  className="detail_barFill"
                  style={{ width: `${movie.aspects.acting}%` }}
                />
              </div>

              <span>Plot</span>
              <div className="detail_barTrack">
                <div
                  className="detail_barFill"
                  style={{ width: `${movie.aspects.plot}%` }}
                />
              </div>
            </div>

            <div className="detail_barRow">
              <span>Visuals</span>
              <div className="detail_barTrack">
                <div
                  className="detail_barFill"
                  style={{ width: `${movie.aspects.visuals}%` }}
                />
              </div>

              <span>Pacing</span>
              <div className="detail_barTrack">
                <div
                  className="detail_barFill"
                  style={{ width: `${movie.aspects.pacing}%` }}
                />
              </div>
            </div>
          </div>

          {/* Buttons */}
          <div className="detail_buttons">

            <button className="detail_playBtn">
              ▶ Play on Youtube
            </button>

            <button className="detail_listBtn">
              + Add to List
            </button>

          </div>

        </div>
      </div>
    </div>
  );
}
