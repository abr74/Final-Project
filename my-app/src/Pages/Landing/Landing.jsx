import { useState } from "react";
import "./Landing.css";

const UPLOAD_URL_API =
  "https://hkv39v0ul7.execute-api.us-east-1.amazonaws.com/prod/upload-url";

export default function Landing({ onUploadSuccess }) {
  const [file, setFile] = useState(null);
  const [loading, setLoading] = useState(false);
  const [message, setMessage] = useState("");

  async function handleUpload() {
    console.log("Upload button clicked");

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
      console.log("Raw upload URL response:", rawText);

      if (!urlResponse.ok) {
        throw new Error("Could not create upload URL.");
      }

      let uploadData = JSON.parse(rawText);

      if (uploadData.body && typeof uploadData.body === "string") {
        uploadData = JSON.parse(uploadData.body);
      }

      console.log("Parsed upload data:", uploadData);

      if (!uploadData.uploadUrl) {
        throw new Error("Upload URL missing from Lambda response.");
      }

      setMessage("Uploading Takeout ZIP to S3...");

      const uploadResponse = await fetch(uploadData.uploadUrl, {
        method: "PUT",
        headers: {
          "Content-Type": "application/zip"
        },
        body: file
      });

      if (!uploadResponse.ok) {
        throw new Error("Upload to S3 failed.");
      }

      console.log("Uploaded object key:", uploadData.objectKey);

      setMessage("Upload complete. Processing recommendations...");

      setTimeout(() => {
        onUploadSuccess();
      }, 3000);
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
        <h1>NETFEELINGS</h1>

        <p>
          Upload your Google Takeout ZIP file and discover personalized
          recommendations based on your watch taste.
        </p>

        <div className="upload_box">
          <input
            type="file"
            accept=".zip"
            onChange={(e) => setFile(e.target.files[0])}
          />

          {file && <div className="selected">{file.name}</div>}

          {message && <div className="selected">{message}</div>}

          <button disabled={loading} onClick={handleUpload}>
            {loading ? "Uploading..." : "Upload Takeout"}
          </button>
        </div>
      </div>
    </div>
  );
}