import "./SignInForm.css";

export function SignInForm({ onClose }) {
  const handleSubmit = (e) => {
    e.preventDefault();
    console.log("Sign In submit");
  };

  return (
    <div className="signin_overlay" onMouseDown={onClose}>
      <div className="signin_card" onMouseDown={(e) => e.stopPropagation()}>
        <div className="signin_header">
          <h2 className="signin_title">Sign In</h2>
          <button className="signin_close" type="button" onClick={onClose}>
            ✕
          </button>
        </div>

        <form className="signin_form" onSubmit={handleSubmit}>
          <input className="signin_input" type="email" placeholder="Email" required />
          <input className="signin_input" type="password" placeholder="Password" required />

          <button className="signin_button" type="submit">
            Sign In
          </button>
        </form>

        <div className="signin_footer">
          Powered by BERT - NCF - Content AI
        </div>
      </div>
    </div>
  );
}
