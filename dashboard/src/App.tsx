import { useState } from "react";
import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import { isLoggedIn } from "./lib/auth";
import { Layout } from "./components/Layout";
import { Toaster } from "./components/Toaster";
import Login from "./pages/Login";
import SetupPassword from "./pages/SetupPassword";
import Dashboard from "./pages/Dashboard";
import Users from "./pages/Users";
import Payments from "./pages/Payments";
import Broadcasts from "./pages/Broadcasts";
import BroadcastCreate from "./pages/BroadcastCreate";
import Referrals from "./pages/Referrals";
import Gifts from "./pages/Gifts";
import Audit from "./pages/Audit";
import Settings from "./pages/Settings";

export default function App() {
  const [authed, setAuthed] = useState(isLoggedIn());

  return (
    <BrowserRouter basename="/dashboard">
      <Routes>
        <Route path="/setup" element={<SetupPassword onDone={() => setAuthed(true)} />} />
        {!authed ? (
          <Route path="*" element={<Login onDone={() => setAuthed(true)} />} />
        ) : (
          <Route element={<Layout />}>
            <Route index element={<Dashboard />} />
            <Route path="users" element={<Users />} />
            <Route path="payments" element={<Payments />} />
            <Route path="broadcasts" element={<Broadcasts />} />
            <Route path="broadcasts/new" element={<BroadcastCreate />} />
            <Route path="referrals" element={<Referrals />} />
            <Route path="gifts" element={<Gifts />} />
            <Route path="audit" element={<Audit />} />
            <Route path="settings" element={<Settings />} />
            <Route path="*" element={<Navigate to="/" replace />} />
          </Route>
        )}
      </Routes>
      <Toaster />
    </BrowserRouter>
  );
}
