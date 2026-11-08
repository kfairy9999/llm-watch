import { Route, Routes } from "react-router-dom";
import { Layout } from "@/components/Layout";
import { CallDetail } from "@/pages/CallDetail";
import { Calls } from "@/pages/Calls";
import { Comparison } from "@/pages/Comparison";
import { Evals } from "@/pages/Evals";
import { Overview } from "@/pages/Overview";

export default function App() {
  return (
    <Routes>
      <Route element={<Layout />}>
        <Route index element={<Overview />} />
        <Route path="calls" element={<Calls />} />
        <Route path="calls/:id" element={<CallDetail />} />
        <Route path="evals" element={<Evals />} />
        <Route path="evals/:id" element={<Comparison />} />
        <Route path="*" element={<Missing />} />
      </Route>
    </Routes>
  );
}

function Missing() {
  return (
    <div>
      <h1 className="font-display text-3xl">Page not found</h1>
      <p className="mt-2 text-sm text-muted-foreground">That route is not part of the ledger.</p>
    </div>
  );
}
