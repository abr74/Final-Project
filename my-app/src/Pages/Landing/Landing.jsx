import "./Landing.css";

export function Landing() {

    const handleSubmit = (e) => {
        e.preventDefault();
        console.log("Upload button clicked");
    };

    return (
        <>
            <div className="landing">
                <div className="landing_card">
                    <h1 className="landing_logo">NETFEELINGS</h1>

                    <h2 className="landing_card_title">
                        Upload Your Google Takeout
                    </h2>

                    <p className="landing_description">
                        Upload your Google data export to generate personalized
                        recommendations and insights.
                    </p>

                    <form className="landing_form" onSubmit={handleSubmit}>

                        <button className="landing_button" type="submit">
                            Upload Takeout File
                        </button>

                    </form>

                    <div className="landing_card_footer">
                        Powered by BERT - NCF - Content AI
                    </div>
                </div>
            </div>
        </>
    );
}