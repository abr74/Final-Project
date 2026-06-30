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

      // IMPORTANT: do NOT set a Content-Type header here.
      // The SigV4 presigned URL does not sign Content-Type, so forcing
      // one (application/zip) makes the browser's signature differ from
      // what S3 expects -> 403 SignatureDoesNotMatch. Let the browser
      // attach its own; SigV4 ignores it for signing.
      // Also note: body is the raw File object, never FormData.
      const uploadResponse = await fetch(uploadData.uploadUrl, {
        method: "PUT",
        body: file
      });

      console.log("S3 upload status:", uploadResponse.status);

      if (!uploadResponse.ok) {
        const detail = await uploadResponse.text(); // S3 returns XML with the real reason
        console.error("S3 upload failed:", detail);
        throw new Error(`Upload to S3 failed (${uploadResponse.status}).`);
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
        <h1>YOUFEELINGS</h1>
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