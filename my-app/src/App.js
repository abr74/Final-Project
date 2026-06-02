import { useState } from "react";

import Landing from "./Pages/Landing/Landing";
import Recommendations from "./Pages/Recommendation/Recommendation";

function App() {
  const [uploaded, setUploaded] = useState(false);

  return uploaded ? (
    <Recommendations />
  ) : (
    <Landing onUploadSuccess={() => setUploaded(true)} />
  );
}

export default App;