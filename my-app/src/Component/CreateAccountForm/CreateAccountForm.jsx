import "./CreateAccountForm.css";

export function CreateAccountForm({ onClose }) {
  const handleSubmit = (e) => {
    e.preventDefault();
    console.log("Create Account submit");
  };

  return (
    <div className="create_overlay" onMouseDown={onClose}>
      <div className="create_card" onMouseDown={(e) => e.stopPropagation()}>
        <div className="create_header">
          <h2 className="create_title">Create Account</h2>
          <button className="create_close" type="button" onClick={onClose}>
            ✕
          </button>
        </div>

        <form className="create_form" onSubmit={handleSubmit}>
          <input className="create_input" type="text" placeholder="Full Name" required />
          <input className="create_input" type="email" placeholder="Email" required />
          <input className="create_input" type="password" placeholder="Password" required />

          <button className="create_button" type="submit">
            Create Account
          </button>
        </form>

        <div className="create_footer">
          Powered by BERT - NCF - Content AI
        </div>
      </div>
    </div>
  );
}
