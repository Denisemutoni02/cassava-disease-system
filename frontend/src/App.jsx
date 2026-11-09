import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom';
import Layout from './components/Layout';
import ProtectedRoute from './components/ProtectedRoute';
import { AuthProvider } from './context/AuthContext';
import { NetworkProvider } from './context/NetworkContext';
import History from './pages/History';
import Login from './pages/Login';
import MapPage from './pages/MapPage';
import Register from './pages/Register';
import Result from './pages/Result';
import Upload from './pages/Upload';

export default function App() {
  return (
    <NetworkProvider>
      <AuthProvider>
        <BrowserRouter>
          <Routes>
            <Route path="/login" element={<Login />} />
            <Route path="/register" element={<Register />} />
            {/* Home = the upload screen */}
            <Route path="/" element={<Navigate to="/diagnose" replace />} />
            <Route
              element={
                <ProtectedRoute>
                  <Layout />
                </ProtectedRoute>
              }
            >
              <Route path="/diagnose" element={<Upload />} />
              <Route path="/result" element={<Result />} />
              <Route path="/map" element={<MapPage />} />
              <Route path="/history" element={<History />} />
            </Route>
            <Route path="*" element={<Navigate to="/diagnose" replace />} />
          </Routes>
        </BrowserRouter>
      </AuthProvider>
    </NetworkProvider>
  );
}
