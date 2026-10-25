import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { Toaster } from 'sonner'

import { AuthProvider } from './hooks/useAuth'
import { Layout }       from './components/Layout'

import { LoginPage }       from './pages/LoginPage'
import { DashboardPage }   from './pages/DashboardPage'
import { FridgesPage }     from './pages/FridgesPage'
import { FridgeDetailPage } from './pages/FridgeDetailPage'
import { InventoryPage }   from './pages/InventoryPage'
import { AlertsPage }      from './pages/AlertsPage'
import { AuditPage }       from './pages/AuditPage'
import { AiInsightsPage }  from './pages/AiInsightsPage'
import { AdminPage }       from './pages/AdminPage'
import { PublicQrPage }    from './pages/PublicQrPage'

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 10_000,
      retry: 1,
    },
  },
})

export default function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <AuthProvider>
          <Toaster
            position="top-right"
            theme="dark"
            richColors
            toastOptions={{
              style: {
                background: '#1e293b',
                border: '1px solid #334155',
                color: '#f1f5f9',
              },
            }}
          />
          <Routes>
            {/* Public QR batch check — no auth */}
            <Route path="/check/:token" element={<PublicQrPage />} />

            {/* Auth page */}
            <Route path="/app/login" element={<LoginPage />} />

            {/* Protected app shell */}
            <Route path="/app" element={<Layout />}>
              <Route index               element={<DashboardPage />}    />
              <Route path="fridges"      element={<FridgesPage />}       />
              <Route path="fridges/:id"  element={<FridgeDetailPage />}  />
              <Route path="inventory"    element={<InventoryPage />}     />
              <Route path="alerts"       element={<AlertsPage />}        />
              <Route path="audit"        element={<AuditPage />}         />
              <Route path="ai"           element={<AiInsightsPage />}    />
              <Route path="admin"        element={<AdminPage />}         />
            </Route>

            {/* Default redirect */}
            <Route path="/"   element={<Navigate to="/app" replace />} />
            <Route path="*"   element={<Navigate to="/app" replace />} />
          </Routes>
        </AuthProvider>
      </BrowserRouter>
    </QueryClientProvider>
  )
}
