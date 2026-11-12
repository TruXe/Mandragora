export default function Features() {
  return (
    <section className="grid grid-cols-3 gap-10">
      <article className="col-span-2">
        <h3 className="text-2xl font-semibold">Offline sync</h3>
        <img src="/img/conflict-resolver.png" alt="Conflict resolver showing two edits" />
        <p className="mt-2">Edits made on the train merge when the laptop reconnects.</p>
      </article>
      <aside>
        <h4 className="text-sm uppercase text-gray-500">Also included</h4>
        <ul className="mt-2 space-y-1">
          <li>CSV and Parquet export</li>
          <li>SSO through any SAML provider</li>
          <li>Audit log kept 400 days</li>
        </ul>
      </aside>
    </section>
  );
}
