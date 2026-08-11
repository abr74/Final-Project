import { useState } from "react";
import "./Landing.css";

const UPLOAD_URL_API =
  "https://hkv39v0ul7.execute-api.us-east-1.amazonaws.com/prod/upload-url";
// GET endpoint for recommendation-lambda (v2). Takes ?userId=<uploadId>.
const RECOMMENDATIONS_API =
  "https://hkv39v0ul7.execute-api.us-east-1.amazonaws.com/prod/recommendations";

export default function Landing({ onUploadSuccess }) {
  const [file, setFile] = useState(null);
  const [loading, setLoading] = useState(false);
  const [message, setMessage] = useState("");

  // Poll until the S3 -> parser -> fusion chain has written our results.
  // The GET lambda returns 404 with {status:"processing"} until then, so a
  // 404 is expected and is NOT an error.
  async function pollForRecommendations(uploadId, { tries = 40, delayMs = 5000 } = {}) {
    for (let i = 0; i < tries; i++) {
      try {
        const res = await fetch(
          `${RECOMMENDATIONS_API}?userId=${encodeURIComponent(uploadId)}`
        );
        if (res.ok) return await res.json();
        if (res.status !== 404) {
          console.warn("Unexpected status while polling:", res.status);
        }
      } catch (err) {
        console.warn("Poll attempt failed:", err);
      }
      setMessage(
        `Analyzing your watch history... (${Math.round(((i + 1) * delayMs) / 1000)}s)`
      );
      await new Promise((r) => setTimeout(r, delayMs));
    }
    throw new Error(
      "Still processing. Large histories can take a few minutes — try refreshing shortly."
    );
  }

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
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ fileName: file.name }),
      });

      const rawText = await urlResponse.text();
      console.log("Raw upload URL response:", rawText);
      if (!urlResponse.ok) throw new Error("Could not create upload URL.");

      let uploadData = JSON.parse(rawText);
      if (uploadData.body && typeof uploadData.body === "string") {
        uploadData = JSON.parse(uploadData.body);
      }
      if (!uploadData.uploadUrl) {
        throw new Error("Upload URL missing from Lambda response.");
      }

      // FIX: keep the upload UUID. Previously it was thrown away, so the
      // results call had no way to identify this user and the GET lambda
      // fell back to a hardcoded recommendations/sam.json.
      const uploadId =
        uploadData.uploadId ||
        (uploadData.objectKey ? uploadData.objectKey.split("/")[1] : null);
      if (!uploadId) throw new Error("Upload ID missing from Lambda response.");
      console.log("uploadId:", uploadId);

      setMessage("Uploading Takeout ZIP to S3...");

      // No Content-Type header: the SigV4 presigned URL leaves it unsigned,
      // and body is the raw File (never FormData).
      const uploadResponse = await fetch(uploadData.uploadUrl, {
        method: "PUT",
        body: file,
      });
      console.log("S3 upload status:", uploadResponse.status);
      if (!uploadResponse.ok) {
        const detail = await uploadResponse.text();
        console.error("S3 upload failed:", detail);
        throw new Error(`Upload to S3 failed (${uploadResponse.status}).`);
      }

      setMessage("Upload complete. Processing your recommendations...");
      const results = await pollForRecommendations(uploadId);

      console.log(
        `Got ${results.num_recommendations} recommendations (mode: ${results.mode})`
      );
      onUploadSuccess(results, uploadId);
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
            {loading ? "Processing..." : "Upload Takeout"}
          </button>
        </div>
      </div>
    </div>
  );
}
