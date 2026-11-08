import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter } from "react-router-dom";
import "@fontsource/fraunces/600.css";
import "@fontsource/ibm-plex-mono/400.css";
import { loadConfig } from "@/api";
import App from "@/App";
import "./index.css";

const root = document.getElementById("root");
if (!root) throw new Error("missing root element");

if (import.meta.env.VITE_DEMO_STATIC !== "1") {
  await loadConfig();
}

createRoot(root).render(
  <StrictMode>
    <BrowserRouter>
      <App />
    </BrowserRouter>
  </StrictMode>,
);
