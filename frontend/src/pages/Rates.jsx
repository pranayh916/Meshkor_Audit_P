import RatesTable from "./RatesTable.jsx";

export default function Rates({ user }) {
  const isAdmin = user?.roles?.includes("Admin");
  return (
    <section>
      <h1>{isAdmin ? "All hospital rates" : "Released hospital comparisons"}</h1>
      <p className="lede">{isAdmin
        ? "Hospital rate rows from the normalized comparison layer, including flags and source lineage."
        : "Released rate rows for clinically reviewed drugs. Rows with unresolved dosage units are not shown."}</p>
      <RatesTable user={user} />
    </section>
  );
}
