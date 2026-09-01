import { useState } from "react";

import Landing from "./Pages/Landing/Landing";
import Recommendations from "./Pages/Recommendation/Recommendation";

function App() {
  const [userId, setUserId] = useState(null);

  return userId ? (
    <Recommendations userId={userId} />
  ) : (
    <Landing onUploadSuccess={(uploadId) => setUserId(uploadId)} />
  );
}

export default App;