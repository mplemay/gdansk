import { Head, router, useForm, usePage } from "@inertiajs/react";
import { useEffect, useRef } from "react";

import type { PageProps } from "../.gdansk/pages";

type RootPageProps = PageProps<"/">;

export default function RootPage() {
  const page = usePage<RootPageProps>();
  const form = useForm({
    name: "",
    topic: "",
  });
  const conversationReloadRequested = useRef(false);
  const flashMessage = typeof page.flash.message === "string" ? page.flash.message : undefined;
  const { activity, announcements, conversation, feed, headline, metrics, sessionToken, summary, updatedAt } =
    page.props;

  useEffect(() => {
    if (conversation || conversationReloadRequested.current) {
      return;
    }

    conversationReloadRequested.current = true;
    router.reload({ only: ["conversation"] });
  }, [conversation]);

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
            <button className="ghost-button" onClick={() => router.reload({ only: ["announcements"] })} type="button">
              Append announcement
            </button>
            <button className="ghost-button" onClick={() => router.reload({ only: ["conversation"] })} type="button">
              Deep-merge message
            </button>
            <button className="ghost-button" onClick={() => router.visit("/inertia")} type="button">
              Open Inertia docs
            </button>
          </div>
          <div className="hero-footnote">
            Updated {updatedAt}
            {sessionToken ? <span className="token-pill">shared once: {sessionToken}</span> : null}
          </div>
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

            <div className="action-cluster">
              <button className="solid-button" disabled={form.processing} type="submit">
                {form.processing ? "Sending..." : "Send feedback"}
              </button>
              <button className="ghost-button" onClick={() => router.post("/jump-to-activity")} type="button">
                Jump to activity
              </button>
            </div>
          </form>

          <section className="panel activity-panel" id="activity">
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

        <section className="panel-grid">
          <section className="panel">
            <div className="panel-heading">
              <h2>Merge props</h2>
              <p>Each reload returns one more announcement, and the client appends it because the prop is mergeable.</p>
            </div>

            <ul className="log-list">
              {announcements.map((announcement) => (
                <li key={announcement.id}>
                  <strong>{announcement.label}</strong>
                  <span>{announcement.note}</span>
                </li>
              ))}
            </ul>
          </section>

          <section className="panel">
            <div className="panel-heading">
              <h2>Deep merge</h2>
              <p>The conversation prop merges nested messages while still updating sibling summary fields.</p>
            </div>

            {conversation ? (
              <>
                <ul className="log-list">
                  {conversation.messages.map((message) => (
                    <li key={message.id}>
                      <strong>{message.author}</strong>
                      <span>{message.body}</span>
                    </li>
                  ))}
                </ul>
                <p>Updated {conversation.summary.updatedAt}</p>
              </>
            ) : (
              <div className="activity-loading">Loading conversation…</div>
            )}
          </section>
        </section>

        <section className="panel">
          <div className="panel-heading">
            <h2>Scroll props</h2>
            <p>
              The feed prop emits scroll metadata and can prepend new entries or reset itself when the client sends
              merge-intent headers.
            </p>
          </div>

          <div className="action-cluster">
            <button
              className="ghost-button"
              onClick={() =>
                router.reload({
                  headers: { "X-Inertia-Infinite-Scroll-Merge-Intent": "prepend" },
                  only: ["feed"],
                })
              }
              type="button"
            >
              Prepend feed item
            </button>
            <button
              className="ghost-button"
              onClick={() =>
                router.reload({
                  only: ["feed"],
                  reset: ["feed"],
                })
              }
              type="button"
            >
              Reset feed
            </button>
          </div>

          <ul className="log-list">
            {feed.items.map((item) => (
              <li key={item.id}>
                <strong>{item.id}</strong>
                <span>{item.text}</span>
              </li>
            ))}
          </ul>
        </section>
      </main>
    </>
  );
}
