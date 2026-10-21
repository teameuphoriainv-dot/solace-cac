import { Suspense, lazy, useEffect } from "react";
import { Navigate, Route, Routes, useLocation, useNavigate } from "react-router-dom";
import { Loader2 } from "lucide-react";
import { onSessionExpired } from "./lib/session";
import PatientIntake from "./pages/PatientIntake";
import PatientResult from "./pages/PatientResult";
import { ErrorBoundary } from "./components/ui/ErrorBoundary";

// Patients only download the check-in and result pages. The clinician side, the
// QR card and the judge pages (home included) load on demand.
const Home = lazy(() => import("./pages/Home"));
const ClinicianDashboard = lazy(() => import("./pages/ClinicianDashboard"));
const PatientDetailPage = lazy(() => import("./pages/PatientDetailPage"));
const QRCard = lazy(() => import("./pages/QRCard"));
const ShowcaseDemo = lazy(() => import("./pages/ShowcaseDemo"));
const HowItWorks = lazy(() => import("./pages/HowItWorks"));
// The repo's AI disclosure and full stress test report, shown on the site itself.
const AiDisclosure = lazy(() => import("./pages/AiDisclosure"));
const StressTestReport = lazy(() => import("./pages/StressTest"));

// A centered busy state covers the brief lazy-chunk fetch.
function RouteFallback() {
  return (
    <div className="min-h-[100dvh] flex items-center justify-center text-text-muted" role="status" aria-live="polite">
      <Loader2 size={20} className="animate-spin" aria-hidden="true" />
      <span className="sr-only">Loading</span>
    </div>
  );
}

/**
 * Routes to the sign-in screen when the api layer reports an expired session.
 *
 * Clinician sign-in lives on ClinicianDashboard at `/:hospitalId/clinician`, so the
 * login route for any clinician sub-page is that page's path cut at `/clinician`.
 */
function SessionExpiryRedirect() {
  const navigate = useNavigate();
  const { pathname } = useLocation();

  useEffect(() => {
    return onSessionExpired((reason) => {
      const marker = "/clinician";
      const at = pathname.indexOf(marker);
      // A 401 on a patient page has no clinician login to fall back to.
      if (at === -1) return;
      const loginPath = pathname.slice(0, at + marker.length);
      if (loginPath === pathname) return;
      navigate(loginPath, { replace: true, state: { authReason: reason } });
    });
  }, [navigate, pathname]);

  return null;
}

export default function App() {
  return (
    <ErrorBoundary>
      <SessionExpiryRedirect />
      <Suspense fallback={<RouteFallback />}>
        <Routes>
          <Route path="/" element={<Home />} />
          <Route path="/how-it-works" element={<HowItWorks />} />
          <Route path="/ai-disclosure" element={<AiDisclosure />} />
          <Route path="/stress-test" element={<StressTestReport />} />
          {/* Split screen: patient phone on the left, live clinician queue on the right. */}
          <Route path="/showcase" element={<ShowcaseDemo />} />
          {/* "/clinician" alone would otherwise be read as a hospital called "clinician". */}
          <Route path="/clinician" element={<Navigate to="/" replace />} />
          <Route path="/:hospitalId" element={<PatientIntake />} />
          <Route path="/:hospitalId/qr" element={<QRCard />} />
          <Route path="/:hospitalId/result/:patientId" element={<PatientResult />} />
          <Route path="/:hospitalId/clinician" element={<ClinicianDashboard />} />
          <Route path="/:hospitalId/clinician/patient/:patientId" element={<PatientDetailPage />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </Suspense>
    </ErrorBoundary>
  );
}
