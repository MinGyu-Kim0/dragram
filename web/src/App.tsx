import { Route, Routes } from "react-router";
import ConnectPage from "./connect/ConnectPage";

function Home() {
  return (
    <main>
      <h1>Dragram</h1>
    </main>
  );
}

function App() {
  return (
    <Routes>
      <Route path="/" element={<Home />} />
      <Route path="/connect" element={<ConnectPage />} />
    </Routes>
  );
}

export default App;
