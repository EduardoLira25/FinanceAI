import { lazy, Suspense } from 'react'
import { useBackendStatus } from './hooks/useBackendStatus'
import {
  Activity,
  LayoutDashboard,
  Bitcoin,
  TrendingUp,
  Bot,
  Wallet,
  ArrowLeftRight,
  ShieldCheck,
  AlertTriangle,
  Clock,
  ChevronRight,
  CircleHelp,
} from 'lucide-react'

import {
  NavLink,
  Link,
  Routes,
  Route,
  useLocation,
} from 'react-router-dom'


const Dashboard = lazy(
  () => import('./pages/Dashboard'),
)

const Market = lazy(
  () => import('./pages/Market'),
)

const Predictions = lazy(
  () => import('./pages/Predictions'),
)

const Agent = lazy(
  () => import('./pages/Agent'),
)

const Portfolio = lazy(
  () => import('./pages/Portfolio'),
)

const Orders = lazy(
  () => import('./pages/Orders'),
)

const Risk = lazy(
  () => import('./pages/Risk'),
)

const Incidents = lazy(
  () => import('./pages/Incidents'),
)

const sections = [
  {
    path: '/',
    name: 'Dashboard',
    icon: LayoutDashboard,
    description: 'Resumen general del sistema financiero',
    features: [],
  },
  {
    path: '/mercado',
    name: 'Mercado',
    icon: Bitcoin,
    description: 'Análisis de Bitcoin y datos de MEXC',
    features: [
      'Velas japonesas BTC/USDT',
      'Historial de precios',
      'Media móvil de 20 días',
      'Volatilidad y rendimientos',
    ],
  },
  {
    path: '/predicciones',
    name: 'Predicciones',
    icon: TrendingUp,
    description: 'Pronósticos del modelo LSTM',
    features: [
      'Predicción del siguiente cierre diario',
      'Rendimiento esperado',
      'Historial de pronósticos',
      'Información del modelo predictivo',
    ],
  },
  {
    path: '/agente',
    name: 'Agente IA',
    icon: Bot,
    description: 'Inteligencia artificial y decisiones financieras',
    features: [
      'Estado operativo de Qwen3',
      'Propuestas BUY, HOLD y SELL',
      'Justificación de las decisiones',
      'Controles de ejecución y recuperación',
    ],
  },
  {
    path: '/cartera',
    name: 'Cartera',
    icon: Wallet,
    description: 'Administración del patrimonio virtual',
    features: [
      'Patrimonio total',
      'Efectivo disponible',
      'Posición en Bitcoin',
      'Distribución y exposición financiera',
    ],
  },
  {
    path: '/operaciones',
    name: 'Operaciones',
    icon: ArrowLeftRight,
    description: 'Historial de operaciones simuladas',
    features: [
      'Compras virtuales',
      'Ventas virtuales',
      'Precio y cantidad de ejecución',
      'Costos y resultados financieros',
    ],
  },
  {
    path: '/riesgo',
    name: 'Riesgo',
    icon: ShieldCheck,
    description: 'Controles de protección del capital',
    features: [
      'Exposición máxima',
      'Límite de pérdida diaria',
      'Antigüedad máxima de datos',
      'Paro de emergencia',
    ],
  },
  {
    path: '/incidentes',
    name: 'Incidentes',
    icon: AlertTriangle,
    description: 'Supervisión y recuperación del sistema',
    features: [
      'Registro de errores',
      'Incidentes pendientes',
      'Acciones correctivas',
      'Historial de recuperación',
    ],
  },
]


function Sidebar() {
  return (
    <aside className="sidebar">

      <Link to="/" className="brand">
        <div className="brand-icon">
          <Activity size={25} />
        </div>
        <div>
          <div className="brand-name">
            Finance<span>AI</span>
          </div>
          <div className="brand-subtitle">
            INTELLIGENT TRADING
          </div>
        </div>
      </Link>

      <div className="nav-label">PLATAFORMA</div>

      <nav
        className="navigation"
        aria-label="Navegación principal"
      >
        {sections.map((section) => {
          const Icon = section.icon

          return (
            <NavLink
              key={section.path}
              to={section.path}
              end={section.path === '/'}
              className={({ isActive }) =>
                `nav-item ${isActive ? 'active' : ''}`
              }
            >
              <Icon size={19} />
              <span>{section.name}</span>
            </NavLink>
          )
        })}
      </nav>

      <div className="sidebar-bottom">

        <div className="simulation-card">
          <ShieldCheck size={20} />

          <div>
            <strong>Paper Trading</strong>
            <small>Capital exclusivamente virtual</small>
          </div>
        </div>

        <div className="version">
          FinanceAI v0.1.0
          <span> LOCAL </span>
        </div>

      </div>

    </aside>
  )
}


function Header() {
  const location = useLocation()
  const connection = useBackendStatus()

  const section = sections.find(
    (item) => item.path === location.pathname,
  )

  return (
    <header className="topbar">

      <div className="breadcrumb">
        FinanceAI
        <ChevronRight size={15} />
        <strong>{section?.name ?? 'Página no encontrada'}</strong>
      </div>

      <div className="header-right">

        <div className="market-tag">
          <Bitcoin size={16} />
          BTC/USDT
        </div>

        <div
          className={`connection-tag ${connection}`}
          role="status"
        >
          <span className="status-dot" />
          {connection === 'connected'
            ? 'Backend conectado'
            : connection === 'checking'
              ? 'Verificando conexión'
              : 'Sin conexión al backend'}
        </div>

      </div>

    </header>
  )
}


type Section = (typeof sections)[number]


function ModulePage({ section }: { section: Section }) {

  const Icon = section.icon

  return (
    <div className="page">

      <div className="page-heading">
        <div>
          <div className="eyebrow">
            FINANCEAI / MÓDULOS
          </div>
          <h1>{section.name}</h1>
          <p>{section.description}</p>
        </div>

        <div className="module-heading-icon">
          <Icon size={30} />
        </div>
      </div>

      <section className="panel module-panel">

        <div className="empty-icon">
          <Icon size={36} />
        </div>

        <h2>Módulo en desarrollo</h2>

        <p>
          La navegación está disponible.
          La conexión y las funciones de este módulo
          se implementarán en los siguientes pasos.
        </p>

        <Link to="/" className="primary-link">
          Volver al Dashboard
        </Link>

      </section>

      <section className="panel">

        <div className="panel-heading">
          <div>
            <h2>Funciones previstas</h2>
            <p>Componentes que integraremos en esta sección</p>
          </div>
        </div>

        <div className="feature-grid">
          {section.features.map((feature) => (
            <div className="feature" key={feature}>
              <Clock size={18} />
              <span>{feature}</span>
            </div>
          ))}
        </div>

      </section>

    </div>
  )
}


function NotFound() {
  return (
    <div className="page">
      <section className="panel module-panel">
        <CircleHelp size={36} />
        <h1>Página no encontrada</h1>
        <Link to="/" className="primary-link">
          Volver al Dashboard
        </Link>
      </section>
    </div>
  )
}


export default function App() {

  return (
    <div className="app-shell">

      <Sidebar />

      <div className="workspace">

        <Header />

        <main className="main-content">

          <Suspense fallback={
            <div className="notice">
              Cargando módulo...
            </div>
          }>
          <Routes>

            <Route
              path="/"
              element={<Dashboard />}
            />

            {sections.slice(1).map((section) => (
              <Route
                key={section.path}
                path={section.path}
                element={
                  section.path === '/mercado'
                    ? <Market />
                    : section.path === '/predicciones'
                      ? <Predictions />
                      : section.path === '/agente'
                        ? <Agent />
                        : section.path === '/cartera'
                          ? <Portfolio />
                          : section.path === '/operaciones'
                            ? <Orders />
                            : section.path === '/riesgo'
                              ? <Risk />
                              : section.path === '/incidentes'
                                ? <Incidents />
                                : <ModulePage section={section} />
                }
              />
            ))}

            <Route
              path="*"
              element={<NotFound />}
            />

          </Routes>
          </Suspense>

        </main>

        <footer className="footer">
          FinanceAI · Sistema académico de Paper Trading
          <span>Sin operaciones con dinero real</span>
        </footer>

      </div>

    </div>
  )
}
