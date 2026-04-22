import { Head, router, useForm, usePage } from "@inertiajs/react";

type Metric = {
  label: string;
  note: string;
  value: string;
};

type HomeProps = {
  activity?: string[];
  errors: Record<string, string>;
  headline: string;
  metrics: Metric[];
  summary: string;
  updatedAt: string;
};

type InertiaPageModel = {
  flash?: {
    message?: string;
  };
  props: HomeProps;
};

export default function Home() {
  const page = usePage() as InertiaPageModel;
  const form = useForm({
    name: "",
    topic: "",
  });
  const flashMessage = page.flash?.message;
  const { activity, headline, metrics, summary, updatedAt } = page.props;

  return (
    <>
      <Head title="Gdansk Inertia" />
      <main className="shell">
        <section className="hero">
          <div className="eyebrow">Initial design</div>
          <h1>{headline}</h1>
          <p>{summary}</p>
          <div className="hero-actions">
            <button className="solid-button" onClick={() => router.reload({ only: ["activity"] })} type="button">
              Refresh activity
            </button>
            <button className="ghost-button" onClick={() => router.visit("/inertia")} type="button">
              Open Inertia docs
            </button>
          </div>
          <div className="hero-footnote">Updated {updatedAt}</div>
        </section>

        {flashMessage ? <p className="flash-banner">{flashMessage}</p> : null}

        <section className="metrics">
          {metrics.map((metric) => (
            <article className="metric-card" key={metric.label}>
              <div className="metric-label">{metric.label}</div>
              <div className="metric-value">{metric.value}</div>
              <p>{metric.note}</p>
            </article>
          ))}
        </section>

        <section className="panel-grid">
          <form
            className="panel"
            onSubmit={(event) => {
              event.preventDefault();
              form.post("/feedback");
            }}
          >
            <div className="panel-heading">
              <h2>Session-backed feedback</h2>
              <p>Validation errors return through the redirect cycle and hydrate into the form state.</p>
            </div>

            <label className="field">
              <span>Name</span>
              <input
                onChange={(event) => form.setData("name", event.currentTarget.value)}
                placeholder="Marta"
                value={form.data.name}
              />
              {form.errors.name ? <small>{form.errors.name}</small> : null}
            </label>

            <label className="field">
              <span>Topic</span>
              <input
                onChange={(event) => form.setData("topic", event.currentTarget.value)}
                placeholder="Design system"
                value={form.data.topic}
              />
              {form.errors.topic ? <small>{form.errors.topic}</small> : null}
            </label>

            <button className="solid-button" disabled={form.processing} type="submit">
              {form.processing ? "Sending..." : "Send feedback"}
            </button>
          </form>

          <section className="panel activity-panel">
            <div className="panel-heading">
              <h2>Deferred activity</h2>
              <p>This list is deferred on the first response and can be refreshed with a targeted partial reload.</p>
            </div>

            {activity ? (
              <ul className="activity-list">
                {activity.map((item) => (
                  <li key={item}>{item}</li>
                ))}
              </ul>
            ) : (
              <div className="activity-loading">Loading deferred activity…</div>
            )}
          </section>
        </section>
      </main>
    </>
  );
}
