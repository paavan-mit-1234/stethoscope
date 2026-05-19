import React from "react";
import ReactDOM from "react-dom/client";

// IBM Plex Mono everywhere; Press Start 2P stands in for the custom
// "Stethoscope Display" pixel font (PRD 8.3) until that asset is shipped.
import "@fontsource/ibm-plex-mono/400.css";
import "@fontsource/ibm-plex-mono/600.css";
import "@fontsource/press-start-2p/400.css";
import "./styles/tokens.css";
import "./styles/app.css";

import App from "./App";

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
);
