import { useState } from "react";
import "./Landing.css";

const UPLOAD_URL_API =
  "https://hkv39v0ul7.execute-api.us-east-1.amazonaws.com/prod/upload-url";

export default function Landing({ onUploadSuccess }) {
  const [file, setFile] = useState(null);
  const [loading, setLoading] = useState(false);
  const [message, setMessage] = useState("");

  async function handleUpload() {
    if (!file) {
      alert("Please select your Google Takeout ZIP file first.");
      return;
    }

    if (!file.name.toLowerCase().endsWith(".zip")) {
      alert("Only .zip files are allowed.");
      return;
    }

    setLoading(true);
    setMessage("Creating secure upload link...");

    try {
      const urlResponse = await fetch(UPLOAD_URL_API, {
        method: "POST",
        headers: {
          "Content-Type": "application/json"
        },
        body: JSON.stringify({
          fileName: file.name
        })
      });

      const rawText = await urlResponse.text();

      if (!urlResponse.ok) {
        throw new Error("Could not create upload URL.");
      }

      let uploadData = JSON.parse(rawText);

      if (uploadData.body && typeof uploadData.body === "string") {
        uploadData = JSON.parse(uploadData.body);
      }

      if (!uploadData.uploadUrl || !uploadData.uploadId) {
        throw new Error("Upload URL missing from Lambda response.");
      }

      setMessage("Uploading Takeout ZIP to S3...");

      const uploadResponse = await fetch(uploadData.uploadUrl, {
        method: "PUT",
        body: file
      });

      if (!uploadResponse.ok) {
        throw new Error(`Upload to S3 failed (${uploadResponse.status}).`);
      }

      setMessage("Upload complete. Processing recommendations...");

      onUploadSuccess(uploadData.uploadId);
    } catch (error) {
      console.error(error);
      setMessage("");
      alert(error.message);
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="landing">
      <div className="landing_card">
        <div className="brand_badge">Personalized YouTube Recommendations</div>

        <h1>YOUFEELINGS</h1>

        <p className="landing_intro">
          Upload your Google Takeout ZIP to help generate recommendations
          based on your YouTube taste.
        </p>

        <div className="method_grid">
          <section className="method_card primary_method">
            <div className="method_icon">📦</div>

            <div>
              <h2>Upload Google Takeout</h2>
              <p>
                Best option for real YouTube watch history. Upload your Takeout
                ZIP and let YouFeelings process your data.
              </p>
            </div>

            <div className="upload_box">
              <label className="file_drop">
                <input
                  type="file"
                  accept=".zip"
                  onChange={(e) => setFile(e.target.files[0])}
                />
                <span>Choose Takeout ZIP</span>
                <small>Only .zip files are accepted</small>
              </label>

              {file && <div className="status_pill">{file.name}</div>}
              {message && <div className="status_pill">{message}</div>}

              <button
                className="action_button"
                disabled={loading}
                onClick={handleUpload}
              >
                {loading ? "Uploading..." : "Upload Takeout"}
              </button>
            </div>
          </section>
        </div>
      </div>
    </div>
  );
}