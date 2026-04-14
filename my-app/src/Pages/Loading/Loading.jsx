// import React from "react";
import "./Loading.css";

export default function Loading() {
  return (
    <div className="load_page">
      <div className="load_card">
        <div className="load_spinnerWrap" aria-hidden="true">
          <div className="load_spinnerRing" />
        </div>

        <h2 className="load_title">Analyzing your taste...</h2>

        <ul className="load_list">
          <li className="load_item load_done">
            <span className="load_icon load_check">✓</span>
            <span className="load_text">Connecting to Netflix</span>
          </li>

          <li className="load_item load_done">
            <span className="load_icon load_check">✓</span>
            <span className="load_text">Fetching watch history</span>
          </li>

          <li className="load_item load_todo">
            <span className="load_icon load_bullet" />
            <span className="load_text">BERT aspect analysis</span>
          </li>

          <li className="load_item load_todo">
            <span className="load_icon load_bullet" />
            <span className="load_text">Running collaborative filter</span>
          </li>

          <li className="load_item load_todo">
            <span className="load_icon load_bullet" />
            <span className="load_text">Generating recommendations</span>
          </li>
        </ul>
      </div>
    </div>
  );
}
