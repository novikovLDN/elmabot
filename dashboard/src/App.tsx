import { useEffect, useState } from "react";
import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import { isLoggedIn } from "./lib/auth";
import { Layout } from "./components/Layout";
import { Toaster } from "./components/Toaster";
import { EntryOverlay } from "./components/EntryOverlay";
import Login from "./pages/Login";
import SetupPassword from "./pages/SetupPassword";
import Dashboard from "./pages/Dashboard";
import Analytics from "./pages/Analytics";
import Users from "./pages/Users";
import Payments from "./pages/Payments";
import Broadcasts from "./pages/Broadcasts";
import BroadcastCreate from "./pages/BroadcastCreate";
import Referrals from "./pages/Referrals";
import Gifts from "./pages/Gifts";
import PromoCodes from "./pages/PromoCodes";
import MarketingLinks from "./pages/MarketingLinks";
import Audit from "./pages/Audit";
import Settings from "./pages/Settings";

export default function App() {
  const [authed, setAuthed] = useState(isLoggedIn());
  const [entry, setEntry] = useState(false);

  // Play the entrance once per session when opening an already-signed-in panel.
  useEffect(() => {
    if (isLoggedIn() && !sessionStorage.getItem("entry_shown")) setEntry(true);
  }, []);

  const enter = () => { setAuthed(true); setEntry(true); };
  const finishEntry = () => { sessionStorage.setItem("entry_shown", "1"); setEntry(false); };

  return (
    <BrowserRouter basename="/dashboard">
      <Routes>
        <Route path="/setup" element={<SetupPassword onDone={enter} />} />
        {!authed ? (
          <Route path="*" element={<Login onDone={enter} />} />
        ) : (
          <Route element={<Layout />}>
            <Route index element={<Dashboard />} />
            <Route path="analytics" element={<Analytics />} />
            <Route path="users" element={<Users />} />
            <Route path="payments" element={<Payments />} />
            <Route path="broadcasts" element={<Broadcasts />} />
            <Route path="broadcasts/new" element={<BroadcastCreate />} />
            <Route path="referrals" element={<Referrals />} />
            <Route path="gifts" element={<Gifts />} />
            <Route path="promo" element={<PromoCodes />} />
            <Route path="links" element={<MarketingLinks />} />
            <Route path="audit" element={<Audit />} />
            <Route path="settings" element={<Settings />} />
            <Route path="*" element={<Navigate to="/" replace />} />
          </Route>
        )}
      </Routes>
      {entry && <EntryOverlay onDone={finishEntry} />}
      <Toaster />
    </BrowserRouter>
  );
}
