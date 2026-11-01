import { Navigate, Route, Routes } from "react-router";
import ConnectPage from "./connect/ConnectPage";
import MySentencesPage from "./history/MySentencesPage";
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
      {/* 문장 원문을 저장하지 않아 문장별 분석 보기는 없어졌다(#324). 옛 주소는 내 기록으로 보낸다. */}
      <Route
        path="/sentences/:id"
        element={<Navigate to="/sentences" replace />}
      />
    </Routes>
  );
}

export default App;
