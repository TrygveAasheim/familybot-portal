import React, { useState } from "react";
import { createRoot } from "react-dom/client";
import { WeekPlanDocument } from "../../app/_components/WeekPlanDocument";
import "../../app/globals.css";

function Fixture() {
  const [plan, setPlan] = useState("plan");
  return <main style={{ maxWidth: 900, margin: "auto", padding: 20 }}>
    <h2>Ukeplan – fiktiv familie</h2>
    <p>Isolert visningstest. Ingen husholdningsdata eller integrasjoner.</p>
    <nav className="document-controls" aria-label="Testtilstander">
      {[["plan", "Plan A"], ["other", "Plan B"], ["missing", "Mangler"], ["broken", "Ugyldig"], ["closed", "Tilbake"]].map(([value, label]) =>
        <button type="button" key={value} onClick={() => setPlan(value)}>{label}</button>)}
    </nav>
    {plan !== "closed" && <WeekPlanDocument key={plan} url={`/__fixture__/${plan}.pdf`} token="fictional-session" />}
    {plan !== "closed" && <details><summary>Tekst fra ukeplanen</summary><p>Norsk: Les side 12. Matematikk: Regn 1–4.</p></details>}
  </main>;
}

createRoot(document.getElementById("root")!).render(<React.StrictMode><Fixture /></React.StrictMode>);
