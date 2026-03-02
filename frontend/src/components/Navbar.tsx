import { Link, useLocation } from 'react-router-dom';

const navItems = [
  { path: '/', label: '检索' },
  { path: '/files', label: '文件管理' },
  { path: '/settings', label: '设置' },
];

export default function Navbar() {
  const location = useLocation();

  return (
    <nav className="sticky top-0 z-50 border-b border-parchment-200 bg-parchment-50/95 backdrop-blur-sm">
      <div className="mx-auto flex h-14 max-w-7xl items-center justify-between px-4">
        <Link to="/" className="font-serif text-xl font-semibold text-cinnabar-500">
          古籍词语检索
        </Link>

        <div className="flex items-center gap-1">
          {navItems.map((item) => {
            const isActive = item.path === '/'
              ? location.pathname === '/'
              : location.pathname.startsWith(item.path);

            return (
              <Link
                key={item.path}
                to={item.path}
                className={`rounded-md px-3 py-1.5 text-sm transition-colors ${
                  isActive
                    ? 'bg-cinnabar-500 text-white'
                    : 'text-ink-700 hover:bg-parchment-200'
                }`}
              >
                {item.label}
              </Link>
            );
          })}
        </div>
      </div>
    </nav>
  );
}
