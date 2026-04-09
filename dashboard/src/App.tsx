import { Route, Routes } from "react-router-dom";
import LiveDashboard from "./pages/LiveDashboard";
import SetupPage from "./pages/SetupPage";

export default function App() {
  return (
    <Routes>
      <Route path="/" element={<LiveDashboard />} />
      <Route path="/setup" element={<SetupPage />} />
    </Routes>
  );
}
