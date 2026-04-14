import React from "react";
import "./Recommendation.css";

const sampleRecs = [
  { title: "Tenet", score: 96, image: "" },
  { title: "Memories of Murder", score: 94, image: "" },
  { title: "Prisoners", score: 92, image: "" },
  { title: "Arrival", score: 91, image: "" },
];

export default function Recommendations() {
  return (
    <div className="rec_page">
      <div className="rec_panel">
        <div className="rec_header">
          <h1 className="rec_title">AI-Powered Recommendations</h1>
          <button className="rec_badge">BERT+NCF</button>
        </div>

        <div className="rec_grid">
          {sampleRecs.map((movie) => (
            <div className="rec_card" key={movie.title}>
              
              <div className="rec_cardTop">

                {/* Image Section */}
                <div className="rec_imageWrap">
                  {movie.image ? (
                    <img
                      src={movie.image}
                      alt={movie.title}
                      className="rec_image"
                    />
                  ) : (
                    <div className="rec_imagePlaceholder">
                      Image
                    </div>
                  )}
                </div>

                {/* Score Box */}
                <div className="rec_scorePill">
                  <span className="rec_score">{movie.score}%</span>
                </div>
              </div>

              {/* Bottom Section */}
              <div className="rec_cardBottom">
                <div className="rec_movieTitle">{movie.title}</div>

                <div className="rec_barTrack">
                  <div
                    className="rec_barFill"
                    style={{ width: `${movie.score}%` }}
                  />
                </div>
              </div>

            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
