import { Route, Routes } from "react-router";
import ConnectPage from "./connect/ConnectPage";
import MySentencesPage from "./history/MySentencesPage";
import SentenceDetailPage from "./history/SentenceDetailPage";
import HomePage from "./site/LandingPage";
import PrivacyPage from "./site/PrivacyPage";
import TermsPage from "./site/TermsPage";

function App() {
  return (
    <Routes>
      <Route path="/" element={<HomePage />} />
      <Route path="/privacy" element={<PrivacyPage />} />
      <Route path="/privacy/:version" element={<PrivacyPage />} />
      <Route path="/terms" element={<TermsPage />} />
      <Route path="/terms/:version" element={<TermsPage />} />
      <Route path="/connect" element={<ConnectPage />} />
      <Route path="/sentences" element={<MySentencesPage />} />
      <Route path="/sentences/:id" element={<SentenceDetailPage />} />
    </Routes>
  );
}

export default App;
