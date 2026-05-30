import React from "react";
import "./Dashboard.css";

export default function Dashboard() {
    const prefs = ["Complex plots", "Stunning visuals", "Intense drama"];

    const aspectPrefs = [
        {label: "Plot", value: 92},
        {label: "Visuals", value: 78},
        {label: "Acting", value: 72}
    ];

    const history = new Array(5).fill(null);

    return (
        <>
        
            <div className="dash">
                <header className="dash_topbar">
                    <div className="dash_brand">NETFEELINGS</div>

                    <nav className="dash_nav">
                        <span className="dash_link dash_link_active">For You</span>
                        <span className="dash_link">History</span>
                        <span className="dash_link">Aspects</span>
                    </nav>
                </header>

                <main className="dash_wrap">
                    <section className="dash_panel">
                        <h2 className="dash_panel_title"> Your Taste Profile</h2>

                        <div className="dash_grid">
                            <div>
                                <div className="dash_subtitle"> What you Love:</div>
                                <ul className="dash_list">
                                    {prefs.map((item) => (
                                        <li key={item} className="dash_list_item">
                                            <span className="dash_check">✓</span>
                                            {item}
                                        </li>
                                    ))}
                                </ul>
                            </div>

                            <div>
                                <div className="dash_subtitle">Aspect Preferences</div>

                                <div className="dash_bars">
                                    {aspectPrefs.map((a) => (
                                        <div key={a.label} className="dash_bar_row">
                                            <div className="dash_bar_label">{a.label}</div>
                                            <div className="dash_bar_track">
                                                <div
                                                className="dash_bar_fill"
                                                style={{width: `${a.value}%`}}
                                                />
                                            </div>
                                        </div>
                                    ))}
                                </div>
                            </div>
                        </div>
                    </section>

                    {/* watch history */}
                    <section className="dash_panel">
                        <h2 className="dash_panel_title"> Your Watch History</h2>

                        <div className="dash_history_row">
                            {history.map((_, i) => (
                                <div key={i} className="dash_title">
                                    <img 
                                    src=""
                                    alt="placeholder"
                                    className="dash_tile_image"
                                    />
                                </div>
                            ))}
                        </div>
                    </section>

                </main>
            </div>

        </>
    )
}