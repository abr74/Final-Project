import { GoogleLogin } from "@react-oauth/google";
import "./Landing.css";
// import Card from "react-bootstrap"
// import Button from "react-bootstrap";

export function Landing() {

    const handleSubmit = (e) => {
        e.console.error("Does not work");
    }
    return (
        <>
            {/* for Sign in with Google  */}
            {/* <GoogleLogin
            onSuccess={(credentialResponse) => {
                console.log(credentialResponse)
            }}
            onError={() => console.log("Login failed")}/> */}

            <div className="landing">
                <div className="landing_card">
                    <h1 className="landing_logo">NETFEELINGS</h1>

                    <h2 className="landing_card_title">Sign in</h2>

                    <form className="landing_form" onSubmit={handleSubmit}>
                        <input
                        className="landing_input"
                        type="email"
                        placeholder="Netflix Email"
                        />

                        <input 
                        className="landing_input"
                        type="password"
                        placeholder="Password"
                        />

                        <button className="landing_button" type="submit">
                            Connect &amp; Get Recommendations
                        </button>
                    </form>

                    <div className="landing_card_footer">
                        Pwered by BERT - NCF - Content AI
                    </div>
                </div>
            </div>
        </>        
    )
}