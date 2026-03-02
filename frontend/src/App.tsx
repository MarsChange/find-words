import { BrowserRouter, Routes, Route } from 'react-router-dom';
import Navbar from '@/components/Navbar';
import SearchPage from '@/pages/SearchPage';
import FilesPage from '@/pages/FilesPage';
import ReaderPage from '@/pages/ReaderPage';
import SettingsPage from '@/pages/SettingsPage';

export default function App() {
  return (
    <BrowserRouter>
      <div className="flex min-h-screen flex-col bg-parchment-50">
        <Navbar />
        <main className="flex-1">
          <Routes>
            <Route path="/" element={<SearchPage />} />
            <Route path="/files" element={<FilesPage />} />
            <Route path="/reader/:fileId" element={<ReaderPage />} />
            <Route path="/settings" element={<SettingsPage />} />
          </Routes>
        </main>
      </div>
    </BrowserRouter>
  );
}
