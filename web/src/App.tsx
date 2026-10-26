import { Route, Routes } from "react-router";
import ConnectPage from "./connect/ConnectPage";
import LandingPage from "./site/LandingPage";
import PrivacyPage from "./site/PrivacyPage";
import TermsPage from "./site/TermsPage";

function App() {
  return (
    <Routes>
      <Route path="/" element={<LandingPage />} />
      <Route path="/privacy" element={<PrivacyPage />} />
      <Route path="/terms" element={<TermsPage />} />
      <Route path="/connect" element={<ConnectPage />} />
    </Routes>
  );
}

export default App;
