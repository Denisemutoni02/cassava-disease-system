import { NavLink, Outlet, useNavigate } from 'react-router-dom';
import { useAuth } from '../context/AuthContext';
import OfflineBanner from './OfflineBanner';

const NAV = [
  { to: '/diagnose', label: 'Diagnose', icon: '📷', end: true },
  { to: '/map', label: 'Map', icon: '🗺️' },
  { to: '/history', label: 'History', icon: '🕘' },
];

export default function Layout() {
  const { user, logout } = useAuth();
  const navigate = useNavigate();

  return (
    <div className="app-shell">
      <header className="topbar">
        <div className="brand">
          <span className="brand-leaf" aria-hidden>
            🌿
          </span>
          <div>
            <h1>CassavaGuard</h1>
            <p className="brand-sub">MuZARDI · Uganda</p>
          </div>
        </div>
        {user && (
          <div className="topbar-user">
            <span className="role-chip" title={user.demo ? 'Demo session' : 'Backend session'}>
              {String(user.role || '').replace('_', ' ')}
            </span>
            <button
              className="btn btn-ghost btn-sm"
              onClick={() => {
                logout();
                navigate('/login');
              }}
            >
              Log out
            </button>
          </div>
        )}
      </header>

      <OfflineBanner />

      <main className="content">
        <Outlet />
      </main>

      <nav className="bottom-nav" aria-label="Primary">
        {NAV.map((item) => (
          <NavLink
            key={item.to}
            to={item.to}
            end={item.end}
            className={({ isActive }) => `nav-item${isActive ? ' active' : ''}`}
          >
            <span aria-hidden>{item.icon}</span>
            <span>{item.label}</span>
          </NavLink>
        ))}
      </nav>
    </div>
  );
}
