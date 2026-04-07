import { BrowserRouter, Routes, Route } from "react-router-dom";
import Shell from "./components/layout/Shell";
import Synthesize from "./pages/Synthesize";
import CloneVoice from "./pages/CloneVoice";
import VoiceLibrary from "./pages/VoiceLibrary";
import VoiceDesign from "./pages/VoiceDesign";
import Settings from "./pages/Settings";

function App() {
  return (
    <BrowserRouter>
      <Shell>
        <Routes>
          <Route path="/" element={<Synthesize />} />
          <Route path="/clone" element={<CloneVoice />} />
          <Route path="/library" element={<VoiceLibrary />} />
          <Route path="/design" element={<VoiceDesign />} />
          <Route path="/settings" element={<Settings />} />
        </Routes>
      </Shell>
    </BrowserRouter>
  );
}

export default App;
